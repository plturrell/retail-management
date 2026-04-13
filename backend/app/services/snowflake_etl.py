"""Nightly batch ETL: PostgreSQL (OLTP) → Snowflake star schema (OLAP).

Triggered by Cloud Scheduler → Cloud Tasks → POST /api/etl/run
Each domain is extracted incrementally using updated_at > last_sync watermark.

Star-schema layout (defined in snowflake/schema/):
  Dimensions: DIM_DATE, DIM_STORE, DIM_PRODUCT, DIM_CUSTOMER, DIM_SUPPLIER, DIM_STAFF
  Facts:      FACT_SALES, FACT_PURCHASES, FACT_INVENTORY_SNAPSHOT,
              FACT_EXPENSES, FACT_PAYROLL
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.snowflake_client import get_snowflake, SnowflakeClient

logger = logging.getLogger(__name__)

# Snowflake staging schema (raw extracts land here before MERGE into star schema)
_STG = settings.SNOWFLAKE_ETL_SCHEMA
_ANA = settings.SNOWFLAKE_SCHEMA


# ------------------------------------------------------------------ #
# Watermark helpers                                                    #
# ------------------------------------------------------------------ #

async def _get_last_sync(sf: SnowflakeClient, table: str) -> datetime:
    """Return the last successful sync timestamp for a given table."""
    row = await sf.fetch_one(
        f"SELECT LAST_SYNC_AT FROM {_STG}.ETL_WATERMARKS WHERE TABLE_NAME = %s",
        (table,),
    )
    if row:
        return row["LAST_SYNC_AT"]
    # Default: 30 days ago for first run
    return datetime.now(timezone.utc) - timedelta(days=30)


async def _set_last_sync(sf: SnowflakeClient, table: str, ts: datetime) -> None:
    await sf.execute(
        f"""
        MERGE INTO {_STG}.ETL_WATERMARKS t
        USING (SELECT %s AS TABLE_NAME, %s AS LAST_SYNC_AT) s
        ON t.TABLE_NAME = s.TABLE_NAME
        WHEN MATCHED THEN UPDATE SET LAST_SYNC_AT = s.LAST_SYNC_AT
        WHEN NOT MATCHED THEN INSERT (TABLE_NAME, LAST_SYNC_AT) VALUES (s.TABLE_NAME, s.LAST_SYNC_AT)
        """,
        (table, ts),
    )


# ------------------------------------------------------------------ #
# Extract helpers                                                      #
# ------------------------------------------------------------------ #

async def _pg_fetch(db: AsyncSession, sql: str, params: dict) -> list[dict]:
    result = await db.execute(text(sql), params)
    keys = result.keys()
    return [dict(zip(keys, row)) for row in result.fetchall()]


# ------------------------------------------------------------------ #
# Dimension loaders                                                    #
# ------------------------------------------------------------------ #

async def _load_dim_store(db: AsyncSession, sf: SnowflakeClient, since: datetime) -> int:
    rows = await _pg_fetch(
        db,
        """
        SELECT id::text AS store_id, store_code, name, store_type, city, country,
               currency, is_active, created_at
        FROM stores
        WHERE updated_at > :since
        """,
        {"since": since},
    )
    if not rows:
        return 0

    await sf.execute(f"CREATE SCHEMA IF NOT EXISTS {_STG}")
    await sf.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_STG}.STG_DIM_STORE (
            STORE_ID       VARCHAR(36),
            STORE_CODE     VARCHAR(20),
            NAME           VARCHAR(255),
            STORE_TYPE     VARCHAR(50),
            CITY           VARCHAR(100),
            COUNTRY        VARCHAR(100),
            CURRENCY       VARCHAR(3),
            IS_ACTIVE      BOOLEAN,
            CREATED_AT     TIMESTAMP_TZ
        )
        """
    )
    await sf.execute(f"DELETE FROM {_STG}.STG_DIM_STORE")
    await sf.executemany(
        f"""
        INSERT INTO {_STG}.STG_DIM_STORE VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        [
            (r["store_id"], r["store_code"], r["name"], r["store_type"],
             r["city"], r["country"], r["currency"], r["is_active"], r["created_at"])
            for r in rows
        ],
    )
    await sf.execute(
        f"""
        MERGE INTO {_ANA}.DIM_STORE t
        USING {_STG}.STG_DIM_STORE s ON t.STORE_ID = s.STORE_ID
        WHEN MATCHED THEN UPDATE SET
            STORE_CODE=s.STORE_CODE, NAME=s.NAME, STORE_TYPE=s.STORE_TYPE,
            CITY=s.CITY, COUNTRY=s.COUNTRY, CURRENCY=s.CURRENCY, IS_ACTIVE=s.IS_ACTIVE
        WHEN NOT MATCHED THEN INSERT
            (STORE_ID,STORE_CODE,NAME,STORE_TYPE,CITY,COUNTRY,CURRENCY,IS_ACTIVE,CREATED_AT)
        VALUES
            (s.STORE_ID,s.STORE_CODE,s.NAME,s.STORE_TYPE,s.CITY,s.COUNTRY,
             s.CURRENCY,s.IS_ACTIVE,s.CREATED_AT)
        """
    )
    return len(rows)


async def _load_dim_product(db: AsyncSession, sf: SnowflakeClient, since: datetime) -> int:
    rows = await _pg_fetch(
        db,
        """
        SELECT s.id::text AS sku_id, s.sku_code, s.description,
               c.catg_code AS category_code, c.description AS category_name,
               b.name AS brand, s.gender, s.age_group, s.tax_code,
               s.cost_price, s.use_stock, s.block_sales, s.created_at
        FROM skus s
        LEFT JOIN categories c ON c.id = s.category_id
        LEFT JOIN brands b     ON b.id = s.brand_id
        WHERE s.updated_at > :since
        """,
        {"since": since},
    )
    if not rows:
        return 0
    await sf.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_STG}.STG_DIM_PRODUCT (
            SKU_ID        VARCHAR(36), SKU_CODE VARCHAR(16), DESCRIPTION VARCHAR(255),
            CATEGORY_CODE VARCHAR(50), CATEGORY_NAME VARCHAR(255), BRAND VARCHAR(255),
            GENDER VARCHAR(20), AGE_GROUP VARCHAR(20), TAX_CODE VARCHAR(1),
            COST_PRICE    FLOAT, USE_STOCK BOOLEAN, BLOCK_SALES BOOLEAN, CREATED_AT TIMESTAMP_TZ
        )
        """
    )
    await sf.execute(f"DELETE FROM {_STG}.STG_DIM_PRODUCT")
    await sf.executemany(
        f"INSERT INTO {_STG}.STG_DIM_PRODUCT VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        [(r["sku_id"], r["sku_code"], r["description"], r["category_code"],
          r["category_name"], r["brand"], r["gender"], r["age_group"],
          r["tax_code"], r["cost_price"], r["use_stock"], r["block_sales"], r["created_at"])
         for r in rows],
    )
    await sf.execute(
        f"""
        MERGE INTO {_ANA}.DIM_PRODUCT t USING {_STG}.STG_DIM_PRODUCT s ON t.SKU_ID = s.SKU_ID
        WHEN MATCHED THEN UPDATE SET
            SKU_CODE=s.SKU_CODE, DESCRIPTION=s.DESCRIPTION, CATEGORY_CODE=s.CATEGORY_CODE,
            CATEGORY_NAME=s.CATEGORY_NAME, BRAND=s.BRAND, GENDER=s.GENDER,
            AGE_GROUP=s.AGE_GROUP, TAX_CODE=s.TAX_CODE, COST_PRICE=s.COST_PRICE,
            USE_STOCK=s.USE_STOCK, BLOCK_SALES=s.BLOCK_SALES
        WHEN NOT MATCHED THEN INSERT
            (SKU_ID,SKU_CODE,DESCRIPTION,CATEGORY_CODE,CATEGORY_NAME,BRAND,GENDER,AGE_GROUP,
             TAX_CODE,COST_PRICE,USE_STOCK,BLOCK_SALES,CREATED_AT)
        VALUES (s.SKU_ID,s.SKU_CODE,s.DESCRIPTION,s.CATEGORY_CODE,s.CATEGORY_NAME,s.BRAND,
                s.GENDER,s.AGE_GROUP,s.TAX_CODE,s.COST_PRICE,s.USE_STOCK,s.BLOCK_SALES,s.CREATED_AT)
        """
    )
    return len(rows)


async def _load_dim_customer(db: AsyncSession, sf: SnowflakeClient, since: datetime) -> int:
    rows = await _pg_fetch(
        db,
        """
        SELECT c.id::text AS customer_id, c.customer_code,
               la.tier AS loyalty_tier,
               c.gender,
               CASE
                   WHEN c.date_of_birth IS NULL THEN 'Unknown'
                   WHEN EXTRACT(YEAR FROM AGE(c.date_of_birth)) < 25 THEN '18-24'
                   WHEN EXTRACT(YEAR FROM AGE(c.date_of_birth)) < 35 THEN '25-34'
                   WHEN EXTRACT(YEAR FROM AGE(c.date_of_birth)) < 45 THEN '35-44'
                   WHEN EXTRACT(YEAR FROM AGE(c.date_of_birth)) < 55 THEN '45-54'
                   ELSE '55+'
               END AS age_band,
               s.store_code AS registered_store_code,
               c.is_active, c.created_at
        FROM customers c
        LEFT JOIN loyalty_accounts la ON la.customer_id = c.id
        LEFT JOIN stores s            ON s.id = c.registered_store_id
        WHERE c.updated_at > :since
        """,
        {"since": since},
    )
    if not rows:
        return 0
    await sf.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_STG}.STG_DIM_CUSTOMER (
            CUSTOMER_ID VARCHAR(36), CUSTOMER_CODE VARCHAR(30), LOYALTY_TIER VARCHAR(20),
            GENDER VARCHAR(30), AGE_BAND VARCHAR(10), REGISTERED_STORE_CODE VARCHAR(20),
            IS_ACTIVE BOOLEAN, CREATED_AT TIMESTAMP_TZ
        )
        """
    )
    await sf.execute(f"DELETE FROM {_STG}.STG_DIM_CUSTOMER")
    await sf.executemany(
        f"INSERT INTO {_STG}.STG_DIM_CUSTOMER VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        [(r["customer_id"], r["customer_code"], r["loyalty_tier"], r["gender"],
          r["age_band"], r["registered_store_code"], r["is_active"], r["created_at"])
         for r in rows],
    )
    await sf.execute(
        f"""
        MERGE INTO {_ANA}.DIM_CUSTOMER t USING {_STG}.STG_DIM_CUSTOMER s ON t.CUSTOMER_ID = s.CUSTOMER_ID
        WHEN MATCHED THEN UPDATE SET
            LOYALTY_TIER=s.LOYALTY_TIER, GENDER=s.GENDER, AGE_BAND=s.AGE_BAND,
            IS_ACTIVE=s.IS_ACTIVE
        WHEN NOT MATCHED THEN INSERT
            (CUSTOMER_ID,CUSTOMER_CODE,LOYALTY_TIER,GENDER,AGE_BAND,REGISTERED_STORE_CODE,IS_ACTIVE,CREATED_AT)
        VALUES (s.CUSTOMER_ID,s.CUSTOMER_CODE,s.LOYALTY_TIER,s.GENDER,s.AGE_BAND,
                s.REGISTERED_STORE_CODE,s.IS_ACTIVE,s.CREATED_AT)
        """
    )
    return len(rows)


async def _load_dim_supplier(db: AsyncSession, sf: SnowflakeClient, since: datetime) -> int:
    rows = await _pg_fetch(
        db,
        """
        SELECT id::text AS supplier_id, supplier_code, name, country, currency, is_active, created_at
        FROM suppliers WHERE updated_at > :since
        """,
        {"since": since},
    )
    if not rows:
        return 0
    await sf.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_STG}.STG_DIM_SUPPLIER (
            SUPPLIER_ID VARCHAR(36), SUPPLIER_CODE VARCHAR(30), NAME VARCHAR(255),
            COUNTRY VARCHAR(100), CURRENCY VARCHAR(3), IS_ACTIVE BOOLEAN, CREATED_AT TIMESTAMP_TZ
        )
        """
    )
    await sf.execute(f"DELETE FROM {_STG}.STG_DIM_SUPPLIER")
    await sf.executemany(
        f"INSERT INTO {_STG}.STG_DIM_SUPPLIER VALUES (%s,%s,%s,%s,%s,%s,%s)",
        [(r["supplier_id"], r["supplier_code"], r["name"], r["country"],
          r["currency"], r["is_active"], r["created_at"]) for r in rows],
    )
    await sf.execute(
        f"""
        MERGE INTO {_ANA}.DIM_SUPPLIER t USING {_STG}.STG_DIM_SUPPLIER s ON t.SUPPLIER_ID = s.SUPPLIER_ID
        WHEN MATCHED THEN UPDATE SET NAME=s.NAME, COUNTRY=s.COUNTRY, CURRENCY=s.CURRENCY, IS_ACTIVE=s.IS_ACTIVE
        WHEN NOT MATCHED THEN INSERT
            (SUPPLIER_ID,SUPPLIER_CODE,NAME,COUNTRY,CURRENCY,IS_ACTIVE,CREATED_AT)
        VALUES (s.SUPPLIER_ID,s.SUPPLIER_CODE,s.NAME,s.COUNTRY,s.CURRENCY,s.IS_ACTIVE,s.CREATED_AT)
        """
    )
    return len(rows)


async def _load_dim_staff(db: AsyncSession, sf: SnowflakeClient, since: datetime) -> int:
    rows = await _pg_fetch(
        db,
        """
        SELECT u.id::text AS user_id, u.full_name,
               d.name AS department_name, d.code AS department_code,
               jp.title AS job_title,
               ep.employment_type, ep.nationality
        FROM users u
        LEFT JOIN employee_profiles ep ON ep.user_id = u.id
        LEFT JOIN departments d        ON d.id = ep.department_id
        LEFT JOIN job_positions jp     ON jp.id = ep.job_position_id
        WHERE u.updated_at > :since OR ep.updated_at > :since
        """,
        {"since": since},
    )
    if not rows:
        return 0
    await sf.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_STG}.STG_DIM_STAFF (
            USER_ID VARCHAR(36), FULL_NAME VARCHAR(255), DEPARTMENT_CODE VARCHAR(20),
            DEPARTMENT_NAME VARCHAR(255), JOB_TITLE VARCHAR(255),
            EMPLOYMENT_TYPE VARCHAR(20), NATIONALITY VARCHAR(20)
        )
        """
    )
    await sf.execute(f"DELETE FROM {_STG}.STG_DIM_STAFF")
    await sf.executemany(
        f"INSERT INTO {_STG}.STG_DIM_STAFF VALUES (%s,%s,%s,%s,%s,%s,%s)",
        [(r["user_id"], r["full_name"], r["department_code"], r["department_name"],
          r["job_title"], r["employment_type"], r["nationality"]) for r in rows],
    )
    await sf.execute(
        f"""
        MERGE INTO {_ANA}.DIM_STAFF t USING {_STG}.STG_DIM_STAFF s ON t.USER_ID = s.USER_ID
        WHEN MATCHED THEN UPDATE SET
            FULL_NAME=s.FULL_NAME, DEPARTMENT_CODE=s.DEPARTMENT_CODE,
            DEPARTMENT_NAME=s.DEPARTMENT_NAME, JOB_TITLE=s.JOB_TITLE,
            EMPLOYMENT_TYPE=s.EMPLOYMENT_TYPE, NATIONALITY=s.NATIONALITY
        WHEN NOT MATCHED THEN INSERT
            (USER_ID,FULL_NAME,DEPARTMENT_CODE,DEPARTMENT_NAME,JOB_TITLE,EMPLOYMENT_TYPE,NATIONALITY)
        VALUES (s.USER_ID,s.FULL_NAME,s.DEPARTMENT_CODE,s.DEPARTMENT_NAME,
                s.JOB_TITLE,s.EMPLOYMENT_TYPE,s.NATIONALITY)
        """
    )
    return len(rows)


# ------------------------------------------------------------------ #
# Fact loaders                                                         #
# ------------------------------------------------------------------ #

async def _load_fact_sales(db: AsyncSession, sf: SnowflakeClient, since: datetime) -> int:
    rows = await _pg_fetch(
        db,
        """
        SELECT
            oi.id::text AS line_item_id,
            o.id::text  AS order_id,
            o.order_number,
            o.order_date::date AS sale_date,
            o.store_id::text,
            o.customer_id::text,
            o.staff_id::text,
            oi.sku_id::text,
            oi.qty,
            oi.unit_price,
            oi.discount,
            oi.line_total,
            o.tax_total / NULLIF((SELECT COUNT(*) FROM order_items WHERE order_id = o.id), 0) AS tax_amount,
            o.payment_method,
            o.source::text,
            o.status::text AS order_status
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        WHERE o.updated_at > :since
          AND o.status = 'completed'
        """,
        {"since": since},
    )
    if not rows:
        return 0
    await sf.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_STG}.STG_FACT_SALES (
            LINE_ITEM_ID VARCHAR(36), ORDER_ID VARCHAR(36), ORDER_NUMBER VARCHAR(50),
            SALE_DATE DATE, STORE_ID VARCHAR(36), CUSTOMER_ID VARCHAR(36),
            STAFF_ID VARCHAR(36), SKU_ID VARCHAR(36),
            QTY INT, UNIT_PRICE FLOAT, DISCOUNT FLOAT, LINE_TOTAL FLOAT,
            TAX_AMOUNT FLOAT, PAYMENT_METHOD VARCHAR(50), SOURCE VARCHAR(30), ORDER_STATUS VARCHAR(20)
        )
        """
    )
    await sf.execute(f"DELETE FROM {_STG}.STG_FACT_SALES")
    await sf.executemany(
        f"INSERT INTO {_STG}.STG_FACT_SALES VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        [(r["line_item_id"], r["order_id"], r["order_number"], r["sale_date"],
          r["store_id"], r["customer_id"], r["staff_id"], r["sku_id"],
          r["qty"], r["unit_price"], r["discount"], r["line_total"],
          r["tax_amount"], r["payment_method"], r["source"], r["order_status"])
         for r in rows],
    )
    await sf.execute(
        f"""
        MERGE INTO {_ANA}.FACT_SALES t USING {_STG}.STG_FACT_SALES s ON t.LINE_ITEM_ID = s.LINE_ITEM_ID
        WHEN MATCHED THEN UPDATE SET
            QTY=s.QTY, UNIT_PRICE=s.UNIT_PRICE, DISCOUNT=s.DISCOUNT,
            LINE_TOTAL=s.LINE_TOTAL, TAX_AMOUNT=s.TAX_AMOUNT, ORDER_STATUS=s.ORDER_STATUS
        WHEN NOT MATCHED THEN INSERT
            (LINE_ITEM_ID,ORDER_ID,ORDER_NUMBER,SALE_DATE,STORE_ID,CUSTOMER_ID,STAFF_ID,SKU_ID,
             QTY,UNIT_PRICE,DISCOUNT,LINE_TOTAL,TAX_AMOUNT,PAYMENT_METHOD,SOURCE,ORDER_STATUS)
        VALUES (s.LINE_ITEM_ID,s.ORDER_ID,s.ORDER_NUMBER,s.SALE_DATE,s.STORE_ID,s.CUSTOMER_ID,
                s.STAFF_ID,s.SKU_ID,s.QTY,s.UNIT_PRICE,s.DISCOUNT,s.LINE_TOTAL,
                s.TAX_AMOUNT,s.PAYMENT_METHOD,s.SOURCE,s.ORDER_STATUS)
        """
    )
    return len(rows)


async def _load_fact_purchases(db: AsyncSession, sf: SnowflakeClient, since: datetime) -> int:
    rows = await _pg_fetch(
        db,
        """
        SELECT
            poi.id::text AS po_item_id,
            po.id::text  AS po_id,
            po.po_number,
            po.order_date,
            po.store_id::text,
            po.supplier_id::text,
            poi.sku_id::text,
            poi.qty_ordered, poi.qty_received, poi.unit_cost, poi.line_total,
            po.currency, po.status::text AS po_status
        FROM purchase_order_items poi
        JOIN purchase_orders po ON po.id = poi.purchase_order_id
        WHERE po.updated_at > :since
        """,
        {"since": since},
    )
    if not rows:
        return 0
    await sf.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_STG}.STG_FACT_PURCHASES (
            PO_ITEM_ID VARCHAR(36), PO_ID VARCHAR(36), PO_NUMBER VARCHAR(50),
            ORDER_DATE DATE, STORE_ID VARCHAR(36), SUPPLIER_ID VARCHAR(36), SKU_ID VARCHAR(36),
            QTY_ORDERED INT, QTY_RECEIVED INT, UNIT_COST FLOAT, LINE_TOTAL FLOAT,
            CURRENCY VARCHAR(3), PO_STATUS VARCHAR(30)
        )
        """
    )
    await sf.execute(f"DELETE FROM {_STG}.STG_FACT_PURCHASES")
    await sf.executemany(
        f"INSERT INTO {_STG}.STG_FACT_PURCHASES VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        [(r["po_item_id"], r["po_id"], r["po_number"], r["order_date"],
          r["store_id"], r["supplier_id"], r["sku_id"],
          r["qty_ordered"], r["qty_received"], r["unit_cost"], r["line_total"],
          r["currency"], r["po_status"]) for r in rows],
    )
    await sf.execute(
        f"""
        MERGE INTO {_ANA}.FACT_PURCHASES t USING {_STG}.STG_FACT_PURCHASES s ON t.PO_ITEM_ID = s.PO_ITEM_ID
        WHEN MATCHED THEN UPDATE SET
            QTY_RECEIVED=s.QTY_RECEIVED, PO_STATUS=s.PO_STATUS
        WHEN NOT MATCHED THEN INSERT
            (PO_ITEM_ID,PO_ID,PO_NUMBER,ORDER_DATE,STORE_ID,SUPPLIER_ID,SKU_ID,
             QTY_ORDERED,QTY_RECEIVED,UNIT_COST,LINE_TOTAL,CURRENCY,PO_STATUS)
        VALUES (s.PO_ITEM_ID,s.PO_ID,s.PO_NUMBER,s.ORDER_DATE,s.STORE_ID,s.SUPPLIER_ID,s.SKU_ID,
                s.QTY_ORDERED,s.QTY_RECEIVED,s.UNIT_COST,s.LINE_TOTAL,s.CURRENCY,s.PO_STATUS)
        """
    )
    return len(rows)


async def _load_fact_inventory_snapshot(db: AsyncSession, sf: SnowflakeClient) -> int:
    """Full snapshot (not incremental) — captures current stock levels nightly."""
    today = datetime.now(timezone.utc).date()
    rows = await _pg_fetch(
        db,
        """
        SELECT
            i.id::text AS inventory_id,
            i.store_id::text,
            i.sku_id::text,
            i.qty_on_hand, i.reorder_level, i.reorder_qty,
            i.location_status::text,
            :snapshot_date AS snapshot_date
        FROM inventories i
        """,
        {"snapshot_date": today},
    )
    if not rows:
        return 0
    await sf.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_STG}.STG_FACT_INVENTORY (
            INVENTORY_ID VARCHAR(36), STORE_ID VARCHAR(36), SKU_ID VARCHAR(36),
            QTY_ON_HAND INT, REORDER_LEVEL INT, REORDER_QTY INT,
            LOCATION_STATUS VARCHAR(20), SNAPSHOT_DATE DATE
        )
        """
    )
    await sf.execute(f"DELETE FROM {_STG}.STG_FACT_INVENTORY WHERE SNAPSHOT_DATE = %s", (today,))
    await sf.executemany(
        f"INSERT INTO {_STG}.STG_FACT_INVENTORY VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        [(r["inventory_id"], r["store_id"], r["sku_id"],
          r["qty_on_hand"], r["reorder_level"], r["reorder_qty"],
          r["location_status"], r["snapshot_date"]) for r in rows],
    )
    # Inventory is append-only in the fact table (daily snapshot)
    await sf.execute(
        f"""
        INSERT INTO {_ANA}.FACT_INVENTORY_SNAPSHOT
            (INVENTORY_ID,STORE_ID,SKU_ID,QTY_ON_HAND,REORDER_LEVEL,REORDER_QTY,LOCATION_STATUS,SNAPSHOT_DATE)
        SELECT INVENTORY_ID,STORE_ID,SKU_ID,QTY_ON_HAND,REORDER_LEVEL,REORDER_QTY,LOCATION_STATUS,SNAPSHOT_DATE
        FROM {_STG}.STG_FACT_INVENTORY
        WHERE SNAPSHOT_DATE NOT IN (
            SELECT DISTINCT SNAPSHOT_DATE FROM {_ANA}.FACT_INVENTORY_SNAPSHOT
            WHERE SNAPSHOT_DATE = %s
        )
        """,
        (today,),
    )
    return len(rows)


async def _load_fact_expenses(db: AsyncSession, sf: SnowflakeClient, since: datetime) -> int:
    rows = await _pg_fetch(
        db,
        """
        SELECT
            e.id::text AS expense_id, e.expense_number,
            e.store_id::text,
            ec.code AS category_code, ec.name AS category_name,
            e.vendor_name, e.expense_date,
            e.amount_excl_tax, e.tax_amount, e.amount_incl_tax,
            e.payment_method, e.status::text AS expense_status
        FROM expenses e
        JOIN expense_categories ec ON ec.id = e.category_id
        WHERE e.updated_at > :since
        """,
        {"since": since},
    )
    if not rows:
        return 0
    await sf.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_STG}.STG_FACT_EXPENSES (
            EXPENSE_ID VARCHAR(36), EXPENSE_NUMBER VARCHAR(50), STORE_ID VARCHAR(36),
            CATEGORY_CODE VARCHAR(20), CATEGORY_NAME VARCHAR(255),
            VENDOR_NAME VARCHAR(255), EXPENSE_DATE DATE,
            AMOUNT_EXCL_TAX FLOAT, TAX_AMOUNT FLOAT, AMOUNT_INCL_TAX FLOAT,
            PAYMENT_METHOD VARCHAR(50), EXPENSE_STATUS VARCHAR(20)
        )
        """
    )
    await sf.execute(f"DELETE FROM {_STG}.STG_FACT_EXPENSES")
    await sf.executemany(
        f"INSERT INTO {_STG}.STG_FACT_EXPENSES VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        [(r["expense_id"], r["expense_number"], r["store_id"],
          r["category_code"], r["category_name"], r["vendor_name"], r["expense_date"],
          r["amount_excl_tax"], r["tax_amount"], r["amount_incl_tax"],
          r["payment_method"], r["expense_status"]) for r in rows],
    )
    await sf.execute(
        f"""
        MERGE INTO {_ANA}.FACT_EXPENSES t USING {_STG}.STG_FACT_EXPENSES s ON t.EXPENSE_ID = s.EXPENSE_ID
        WHEN MATCHED THEN UPDATE SET EXPENSE_STATUS=s.EXPENSE_STATUS
        WHEN NOT MATCHED THEN INSERT
            (EXPENSE_ID,EXPENSE_NUMBER,STORE_ID,CATEGORY_CODE,CATEGORY_NAME,
             VENDOR_NAME,EXPENSE_DATE,AMOUNT_EXCL_TAX,TAX_AMOUNT,AMOUNT_INCL_TAX,
             PAYMENT_METHOD,EXPENSE_STATUS)
        VALUES (s.EXPENSE_ID,s.EXPENSE_NUMBER,s.STORE_ID,s.CATEGORY_CODE,s.CATEGORY_NAME,
                s.VENDOR_NAME,s.EXPENSE_DATE,s.AMOUNT_EXCL_TAX,s.TAX_AMOUNT,s.AMOUNT_INCL_TAX,
                s.PAYMENT_METHOD,s.EXPENSE_STATUS)
        """
    )
    return len(rows)


async def _load_fact_payroll(db: AsyncSession, sf: SnowflakeClient, since: datetime) -> int:
    rows = await _pg_fetch(
        db,
        """
        SELECT
            ps.id::text AS payslip_id,
            pr.id::text AS payroll_run_id,
            pr.store_id::text,
            ps.user_id::text,
            pr.period_start,
            ps.basic_salary, ps.hours_worked, ps.overtime_hours, ps.overtime_pay,
            ps.allowances, ps.deductions, ps.gross_pay,
            ps.cpf_employee, ps.cpf_employer, ps.net_pay
        FROM payslips ps
        JOIN payroll_runs pr ON pr.id = ps.payroll_run_id
        WHERE ps.updated_at > :since
        """,
        {"since": since},
    )
    if not rows:
        return 0
    await sf.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_STG}.STG_FACT_PAYROLL (
            PAYSLIP_ID VARCHAR(36), PAYROLL_RUN_ID VARCHAR(36), STORE_ID VARCHAR(36),
            USER_ID VARCHAR(36), PERIOD_START DATE,
            BASIC_SALARY FLOAT, HOURS_WORKED FLOAT, OVERTIME_HOURS FLOAT, OVERTIME_PAY FLOAT,
            ALLOWANCES FLOAT, DEDUCTIONS FLOAT, GROSS_PAY FLOAT,
            CPF_EMPLOYEE FLOAT, CPF_EMPLOYER FLOAT, NET_PAY FLOAT
        )
        """
    )
    await sf.execute(f"DELETE FROM {_STG}.STG_FACT_PAYROLL")
    await sf.executemany(
        f"INSERT INTO {_STG}.STG_FACT_PAYROLL VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        [(r["payslip_id"], r["payroll_run_id"], r["store_id"], r["user_id"], r["period_start"],
          r["basic_salary"], r["hours_worked"], r["overtime_hours"], r["overtime_pay"],
          r["allowances"], r["deductions"], r["gross_pay"],
          r["cpf_employee"], r["cpf_employer"], r["net_pay"]) for r in rows],
    )
    await sf.execute(
        f"""
        MERGE INTO {_ANA}.FACT_PAYROLL t USING {_STG}.STG_FACT_PAYROLL s ON t.PAYSLIP_ID = s.PAYSLIP_ID
        WHEN MATCHED THEN UPDATE SET GROSS_PAY=s.GROSS_PAY, NET_PAY=s.NET_PAY
        WHEN NOT MATCHED THEN INSERT
            (PAYSLIP_ID,PAYROLL_RUN_ID,STORE_ID,USER_ID,PERIOD_START,
             BASIC_SALARY,HOURS_WORKED,OVERTIME_HOURS,OVERTIME_PAY,
             ALLOWANCES,DEDUCTIONS,GROSS_PAY,CPF_EMPLOYEE,CPF_EMPLOYER,NET_PAY)
        VALUES (s.PAYSLIP_ID,s.PAYROLL_RUN_ID,s.STORE_ID,s.USER_ID,s.PERIOD_START,
                s.BASIC_SALARY,s.HOURS_WORKED,s.OVERTIME_HOURS,s.OVERTIME_PAY,
                s.ALLOWANCES,s.DEDUCTIONS,s.GROSS_PAY,s.CPF_EMPLOYEE,s.CPF_EMPLOYER,s.NET_PAY)
        """
    )
    return len(rows)


# ------------------------------------------------------------------ #
# Orchestrator                                                         #
# ------------------------------------------------------------------ #

class ETLResult:
    def __init__(self):
        self.counts: dict[str, int] = {}
        self.errors: dict[str, str] = {}
        self.started_at = datetime.now(timezone.utc)
        self.finished_at: datetime | None = None

    def record(self, name: str, count: int):
        self.counts[name] = count

    def fail(self, name: str, exc: Exception):
        self.errors[name] = str(exc)
        logger.error("ETL table %s failed: %s", name, exc, exc_info=True)

    def finish(self) -> dict:
        self.finished_at = datetime.now(timezone.utc)
        duration_s = (self.finished_at - self.started_at).total_seconds()
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "duration_seconds": duration_s,
            "rows_synced": self.counts,
            "errors": self.errors,
            "success": len(self.errors) == 0,
        }


async def run_nightly_etl(db: AsyncSession) -> dict:
    """Main entry point — called by the ETL Cloud Task handler."""
    result = ETLResult()
    now = datetime.now(timezone.utc)

    async with get_snowflake(schema=settings.SNOWFLAKE_ETL_SCHEMA) as sf:
        # Ensure watermarks table exists
        await sf.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_STG}.ETL_WATERMARKS (
                TABLE_NAME    VARCHAR(100) PRIMARY KEY,
                LAST_SYNC_AT  TIMESTAMP_TZ NOT NULL
            )
            """
        )

        # --- Dimensions (incremental) ---
        for name, loader in [
            ("DIM_STORE",    lambda s: _load_dim_store(db, sf, s)),
            ("DIM_PRODUCT",  lambda s: _load_dim_product(db, sf, s)),
            ("DIM_CUSTOMER", lambda s: _load_dim_customer(db, sf, s)),
            ("DIM_SUPPLIER", lambda s: _load_dim_supplier(db, sf, s)),
            ("DIM_STAFF",    lambda s: _load_dim_staff(db, sf, s)),
        ]:
            try:
                since = await _get_last_sync(sf, name)
                count = await loader(since)
                result.record(name, count)
                await _set_last_sync(sf, name, now)
            except Exception as exc:
                result.fail(name, exc)

        # --- Facts (incremental, except inventory snapshot) ---
        for name, loader in [
            ("FACT_SALES",     lambda s: _load_fact_sales(db, sf, s)),
            ("FACT_PURCHASES", lambda s: _load_fact_purchases(db, sf, s)),
            ("FACT_EXPENSES",  lambda s: _load_fact_expenses(db, sf, s)),
            ("FACT_PAYROLL",   lambda s: _load_fact_payroll(db, sf, s)),
        ]:
            try:
                since = await _get_last_sync(sf, name)
                count = await loader(since)
                result.record(name, count)
                await _set_last_sync(sf, name, now)
            except Exception as exc:
                result.fail(name, exc)

        # Inventory is a full nightly snapshot
        try:
            count = await _load_fact_inventory_snapshot(db, sf)
            result.record("FACT_INVENTORY_SNAPSHOT", count)
        except Exception as exc:
            result.fail("FACT_INVENTORY_SNAPSHOT", exc)

    return result.finish()
