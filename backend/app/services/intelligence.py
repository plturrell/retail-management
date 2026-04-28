"""Hybrid intelligence engine.

Routing logic:
  ┌──────────────────────────────────────────────────────────────────┐
  │  USE CASE                          │  ENGINE                     │
  ├──────────────────────────────────────────────────────────────────┤
  │  Demand forecasting (per SKU)      │  Snowflake Cortex FORECAST  │
  │  Sales anomaly detection           │  Snowflake Cortex ANOMALY   │
  │  Inventory reorder suggestions     │  Snowflake Cortex FORECAST  │
  │  SQL-based KPI summaries           │  Snowflake Cortex COMPLETE  │
  │  Strategic narrative / insights    │  Google GenAI (Gemini)      │
  │  Cross-domain business analysis    │  Google GenAI (Gemini)      │
  │  Customer behaviour narrative      │  Google GenAI (Gemini)      │
  │  Pricing strategy & audit          │  Google GenAI (Gemini)      │
  └──────────────────────────────────────────────────────────────────┘

All Cortex calls hit Snowflake SQL; all GenAI calls go through the
existing ai_gateway for logging, cost tracking, and fallback.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any
from uuid import UUID

from app.services.snowflake_client import get_snowflake, SnowflakeClient
from app.services.ai_gateway import AIRequest, SYNC_TIMEOUT_SECONDS, invoke
from app.config import settings

logger = logging.getLogger(__name__)

_ANA = settings.SNOWFLAKE_SCHEMA


# ------------------------------------------------------------------ #
# Internal helpers                                                     #
# ------------------------------------------------------------------ #

def _cortex_complete(prompt: str, model: str = "mistral-large2") -> str:
    """Build a Snowflake Cortex COMPLETE SQL call."""
    escaped = prompt.replace("'", "\\'")
    return f"SELECT SNOWFLAKE.CORTEX.COMPLETE('{model}', '{escaped}') AS RESPONSE"


# ------------------------------------------------------------------ #
# 1. Demand Forecasting  (Cortex FORECAST)                            #
# ------------------------------------------------------------------ #

async def forecast_demand(
    store_id: str | None = None,
    sku_id: str | None = None,
    horizon_days: int = 30,
) -> list[dict[str, Any]]:
    """Use Cortex FORECAST to predict daily sales qty for the next N days.

    Cortex FORECAST trains a time-series model on FACT_SALES and returns
    predicted quantities with confidence intervals.
    """
    filters = []
    if store_id:
        filters.append(f"STORE_ID = '{store_id}'")
    if sku_id:
        filters.append(f"SKU_ID = '{sku_id}'")
    where = ("WHERE " + " AND ".join(filters)) if filters else ""

    async with get_snowflake() as sf:
        # Build the training view dynamically
        await sf.execute(
            f"""
            CREATE OR REPLACE TEMPORARY VIEW RETAILSG_FORECAST_INPUT AS
            SELECT
                SALE_DATE AS TS,
                SUM(QTY)  AS Y,
                SKU_ID    AS SERIES
            FROM {_ANA}.FACT_SALES
            {where}
            GROUP BY SALE_DATE, SKU_ID
            ORDER BY SALE_DATE
            """
        )

        # Cortex FORECAST — returns predicted rows
        rows = await sf.fetch(
            f"""
            SELECT *
            FROM TABLE(
                SNOWFLAKE.CORTEX.FORECAST(
                    INPUT_DATA        => SYSTEM$REFERENCE('VIEW', 'RETAILSG_FORECAST_INPUT'),
                    TIMESTAMP_COLNAME => 'TS',
                    TARGET_COLNAME    => 'Y',
                    SERIES_COLNAME    => 'SERIES',
                    CONFIG_OBJECT     => {{'prediction_interval': 0.9, 'on_error': 'skip'}},
                    FORECASTING_PERIODS => {horizon_days}
                )
            )
            ORDER BY SERIES, TS
            """
        )
        return rows


# ------------------------------------------------------------------ #
# 2. Sales Anomaly Detection  (Cortex ANOMALY_DETECTION)              #
# ------------------------------------------------------------------ #

async def detect_sales_anomalies(
    store_id: str | None = None,
    lookback_days: int = 90,
) -> list[dict[str, Any]]:
    """Detect unusual spikes or drops in daily revenue using Cortex ANOMALY_DETECTION."""
    store_filter = f"AND STORE_ID = '{store_id}'" if store_id else ""

    async with get_snowflake() as sf:
        await sf.execute(
            f"""
            CREATE OR REPLACE TEMPORARY VIEW RETAILSG_ANOMALY_INPUT AS
            SELECT
                SALE_DATE AS TS,
                SUM(LINE_TOTAL) AS Y
            FROM {_ANA}.FACT_SALES
            WHERE SALE_DATE >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
            {store_filter}
            GROUP BY SALE_DATE
            ORDER BY SALE_DATE
            """
        )

        rows = await sf.fetch(
            f"""
            SELECT *
            FROM TABLE(
                SNOWFLAKE.CORTEX.ANOMALY_DETECTION(
                    INPUT_DATA        => SYSTEM$REFERENCE('VIEW', 'RETAILSG_ANOMALY_INPUT'),
                    TIMESTAMP_COLNAME => 'TS',
                    TARGET_COLNAME    => 'Y',
                    CONFIG_OBJECT     => {{'contamination': 0.05}}
                )
            )
            WHERE IS_ANOMALY = TRUE
            ORDER BY TS
            """
        )
        return rows


# ------------------------------------------------------------------ #
# 3. Inventory Reorder Suggestions  (Cortex FORECAST + rules)         #
# ------------------------------------------------------------------ #

async def get_reorder_suggestions(store_id: str) -> list[dict[str, Any]]:
    """Combine demand forecast with current stock to identify reorder needs."""
    async with get_snowflake() as sf:
        # Current stock levels
        stock = await sf.fetch(
            f"""
            SELECT
                i.SKU_ID,
                p.SKU_CODE,
                p.DESCRIPTION,
                i.QTY_ON_HAND,
                i.REORDER_LEVEL,
                i.REORDER_QTY
            FROM {_ANA}.FACT_INVENTORY_SNAPSHOT i
            JOIN {_ANA}.DIM_PRODUCT p ON p.SKU_ID = i.SKU_ID
            WHERE i.STORE_ID = %s
              AND i.SNAPSHOT_DATE = (
                  SELECT MAX(SNAPSHOT_DATE) FROM {_ANA}.FACT_INVENTORY_SNAPSHOT
                  WHERE STORE_ID = %s
              )
            """,
            (store_id, store_id),
        )

        # Average daily demand (last 30 days actual)
        demand = await sf.fetch(
            f"""
            SELECT
                SKU_ID,
                AVG(DAILY_QTY) AS AVG_DAILY_DEMAND
            FROM (
                SELECT SKU_ID, SALE_DATE, SUM(QTY) AS DAILY_QTY
                FROM {_ANA}.FACT_SALES
                WHERE STORE_ID = %s
                  AND SALE_DATE >= DATEADD(DAY, -30, CURRENT_DATE())
                GROUP BY SKU_ID, SALE_DATE
            )
            GROUP BY SKU_ID
            """,
            (store_id,),
        )
        demand_map = {r["SKU_ID"]: r["AVG_DAILY_DEMAND"] for r in demand}

        suggestions = []
        for item in stock:
            avg_daily = demand_map.get(item["SKU_ID"], 0)
            days_of_stock = (
                item["QTY_ON_HAND"] / avg_daily if avg_daily > 0 else 999
            )
            if item["QTY_ON_HAND"] <= item["REORDER_LEVEL"] or days_of_stock < 14:
                suggestions.append({
                    "sku_id": item["SKU_ID"],
                    "sku_code": item["SKU_CODE"],
                    "description": item["DESCRIPTION"],
                    "qty_on_hand": item["QTY_ON_HAND"],
                    "reorder_level": item["REORDER_LEVEL"],
                    "suggested_order_qty": item["REORDER_QTY"] or max(1, round(avg_daily * 14)),
                    "avg_daily_demand": round(avg_daily, 2),
                    "days_of_stock_remaining": round(days_of_stock, 1),
                    "urgency": "critical" if days_of_stock < 7 else "recommended",
                })

        return sorted(suggestions, key=lambda x: x["days_of_stock_remaining"])


# ------------------------------------------------------------------ #
# 4. KPI Dashboard  (Snowflake SQL aggregations)                      #
# ------------------------------------------------------------------ #

async def get_kpi_summary(
    store_id: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
) -> dict[str, Any]:
    """Pull key business KPIs from Snowflake fact tables."""
    store_filter = f"AND STORE_ID = '{store_id}'" if store_id else ""
    date_filter = ""
    if period_start:
        date_filter += f" AND SALE_DATE >= '{period_start}'"
    if period_end:
        date_filter += f" AND SALE_DATE <= '{period_end}'"

    async with get_snowflake() as sf:
        sales_kpi = await sf.fetch_one(
            f"""
            SELECT
                COUNT(DISTINCT ORDER_ID)  AS total_orders,
                SUM(LINE_TOTAL)           AS total_revenue,
                SUM(DISCOUNT)             AS total_discounts,
                SUM(TAX_AMOUNT)           AS total_gst,
                AVG(LINE_TOTAL)           AS avg_line_value,
                COUNT(DISTINCT CUSTOMER_ID) AS unique_customers,
                SUM(QTY)                  AS units_sold
            FROM {_ANA}.FACT_SALES
            WHERE 1=1 {store_filter} {date_filter}
            """
        )

        expense_kpi = await sf.fetch_one(
            f"""
            SELECT
                SUM(AMOUNT_INCL_TAX) AS total_expenses,
                COUNT(*)             AS expense_count
            FROM {_ANA}.FACT_EXPENSES
            WHERE EXPENSE_STATUS IN ('approved','paid')
            {store_filter.replace('STORE_ID', 'STORE_ID')}
            {date_filter.replace('SALE_DATE', 'EXPENSE_DATE')}
            """
        )

        po_kpi = await sf.fetch_one(
            f"""
            SELECT
                SUM(LINE_TOTAL)  AS total_purchase_cost,
                COUNT(DISTINCT PO_ID) AS total_pos,
                SUM(QTY_ORDERED) AS total_units_ordered,
                SUM(QTY_RECEIVED) AS total_units_received
            FROM {_ANA}.FACT_PURCHASES
            WHERE 1=1 {store_filter}
            {date_filter.replace('SALE_DATE', 'ORDER_DATE')}
            """
        )

        top_products = await sf.fetch(
            f"""
            SELECT
                p.SKU_CODE, p.DESCRIPTION,
                SUM(f.QTY)        AS units_sold,
                SUM(f.LINE_TOTAL) AS revenue
            FROM {_ANA}.FACT_SALES f
            JOIN {_ANA}.DIM_PRODUCT p ON p.SKU_ID = f.SKU_ID
            WHERE 1=1 {store_filter} {date_filter}
            GROUP BY p.SKU_CODE, p.DESCRIPTION
            ORDER BY revenue DESC
            LIMIT 10
            """
        )

    revenue = float(sales_kpi.get("TOTAL_REVENUE") or 0)
    expenses = float(expense_kpi.get("TOTAL_EXPENSES") or 0)
    cogs = float(po_kpi.get("TOTAL_PURCHASE_COST") or 0)

    return {
        "sales": {
            "total_orders": sales_kpi.get("TOTAL_ORDERS"),
            "total_revenue_sgd": revenue,
            "total_discounts_sgd": float(sales_kpi.get("TOTAL_DISCOUNTS") or 0),
            "total_gst_sgd": float(sales_kpi.get("TOTAL_GST") or 0),
            "avg_line_value_sgd": float(sales_kpi.get("AVG_LINE_VALUE") or 0),
            "unique_customers": sales_kpi.get("UNIQUE_CUSTOMERS"),
            "units_sold": sales_kpi.get("UNITS_SOLD"),
        },
        "expenses": {
            "total_sgd": expenses,
            "count": expense_kpi.get("EXPENSE_COUNT"),
        },
        "purchasing": {
            "total_cost_sgd": cogs,
            "total_pos": po_kpi.get("TOTAL_POS"),
            "units_ordered": po_kpi.get("TOTAL_UNITS_ORDERED"),
            "units_received": po_kpi.get("TOTAL_UNITS_RECEIVED"),
        },
        "profitability": {
            "gross_profit_sgd": revenue - cogs,
            "gross_margin_pct": round((revenue - cogs) / revenue * 100, 2) if revenue else 0,
            "operating_profit_sgd": revenue - cogs - expenses,
        },
        "top_products": top_products,
    }


# ------------------------------------------------------------------ #
# 5. Customer Analytics  (Snowflake SQL + Cortex)                     #
# ------------------------------------------------------------------ #

async def get_customer_analytics(store_id: str | None = None) -> dict[str, Any]:
    """Customer LTV, cohort, and segment breakdown from Snowflake."""
    store_filter = f"AND f.STORE_ID = '{store_id}'" if store_id else ""

    async with get_snowflake() as sf:
        ltv = await sf.fetch(
            f"""
            SELECT
                c.LOYALTY_TIER,
                c.GENDER,
                c.AGE_BAND,
                COUNT(DISTINCT f.CUSTOMER_ID) AS customer_count,
                SUM(f.LINE_TOTAL)             AS total_revenue,
                AVG(f.LINE_TOTAL)             AS avg_order_value,
                COUNT(DISTINCT f.ORDER_ID)    AS total_orders
            FROM {_ANA}.FACT_SALES f
            JOIN {_ANA}.DIM_CUSTOMER c ON c.CUSTOMER_ID = f.CUSTOMER_ID
            WHERE f.CUSTOMER_ID IS NOT NULL {store_filter}
            GROUP BY c.LOYALTY_TIER, c.GENDER, c.AGE_BAND
            ORDER BY total_revenue DESC
            """
        )

        repeat_rate = await sf.fetch_one(
            f"""
            SELECT
                COUNT_IF(order_count > 1) AS repeat_customers,
                COUNT(*)                  AS total_customers,
                ROUND(COUNT_IF(order_count > 1) / COUNT(*) * 100, 2) AS repeat_rate_pct
            FROM (
                SELECT CUSTOMER_ID, COUNT(DISTINCT ORDER_ID) AS order_count
                FROM {_ANA}.FACT_SALES
                WHERE CUSTOMER_ID IS NOT NULL {store_filter}
                GROUP BY CUSTOMER_ID
            )
            """
        )

        return {
            "by_segment": ltv,
            "repeat_purchase": repeat_rate,
        }


# ------------------------------------------------------------------ #
# 6. Strategic Narrative  (Google GenAI via ai_gateway)               #
# ------------------------------------------------------------------ #

async def generate_strategic_narrative(
    kpi_data: dict[str, Any],
    period_label: str,
    store_name: str,
    store_id: UUID | None = None,
) -> str:
    """Feed KPI data to Gemini and get a strategic executive summary."""
    prompt = f"""You are the Chief Strategy Officer of RetailSG, a multi-store jewelry retailer in Singapore.

REPORTING PERIOD: {period_label}
STORE: {store_name}

KEY PERFORMANCE DATA:
{json.dumps(kpi_data, indent=2, default=str)}

Write a concise executive narrative (3-4 paragraphs) covering:
1. Overall trading performance and headline metrics
2. Notable strengths or opportunities (reference specific data)
3. Risks or areas requiring management attention
4. One specific recommended action for the next 30 days

Tone: professional, data-driven, direct. No bullet points — prose only.
Do not repeat all numbers verbatim; synthesise into insight."""

    resp = await invoke(
        AIRequest(
            prompt=prompt,
            purpose="strategic_narrative",
            timeout_seconds=SYNC_TIMEOUT_SECONDS,
            max_output_tokens=800,
            temperature=0.4,
            store_id=store_id,
        ),
        fallback_text="Strategic narrative temporarily unavailable. Please review the KPI data above.",
    )
    return resp.text


# ------------------------------------------------------------------ #
# 7. Cortex SQL Summary  (in-Snowflake LLM on result sets)            #
# ------------------------------------------------------------------ #

async def cortex_summarise_query_result(
    sql: str,
    question: str,
) -> str:
    """Run a SQL query in Snowflake, then ask Cortex COMPLETE to narrate the results.

    Used for: "Summarise this week's expense breakdown" style queries.
    The SQL runs in Snowflake, the result is serialised to JSON, and
    Cortex generates a plain-English summary entirely within Snowflake —
    no data leaves the warehouse.
    """
    async with get_snowflake() as sf:
        rows = await sf.fetch(sql)
        if not rows:
            return "No data found for the requested query."

        data_json = json.dumps(rows[:50], default=str)  # cap at 50 rows for context
        summary_sql = _cortex_complete(
            f"Question: {question}\n\nData:\n{data_json}\n\n"
            "Answer the question in 2-3 clear sentences based only on the data above."
        )
        result = await sf.fetch_one(summary_sql)
        return result.get("RESPONSE", "Unable to generate summary.") if result else "No response."


# ------------------------------------------------------------------ #
# 8. Expense Anomaly Narrative  (Cortex SQL anomaly → GenAI narrative)#
# ------------------------------------------------------------------ #

async def analyse_expense_anomalies(
    store_id: str,
    store_name: str,
) -> dict[str, Any]:
    """
    Detect unusual expense patterns in Snowflake, then have Gemini
    narrate the findings and recommend actions.
    Hybrid: structured detection in Cortex, narrative in GenAI.
    """
    async with get_snowflake() as sf:
        # Find categories with expense > 2 std deviations from mean
        anomalies = await sf.fetch(
            f"""
            WITH monthly AS (
                SELECT
                    DATE_TRUNC('month', EXPENSE_DATE) AS month,
                    CATEGORY_CODE,
                    CATEGORY_NAME,
                    SUM(AMOUNT_INCL_TAX) AS total
                FROM {_ANA}.FACT_EXPENSES
                WHERE STORE_ID = %s
                  AND EXPENSE_STATUS IN ('approved','paid')
                  AND EXPENSE_DATE >= DATEADD(MONTH, -6, CURRENT_DATE())
                GROUP BY 1,2,3
            ),
            stats AS (
                SELECT
                    CATEGORY_CODE,
                    CATEGORY_NAME,
                    AVG(total) AS mean_spend,
                    STDDEV(total) AS std_spend
                FROM monthly
                GROUP BY 1,2
            ),
            latest AS (
                SELECT * FROM monthly
                WHERE month = DATE_TRUNC('month', DATEADD(MONTH, -1, CURRENT_DATE()))
            )
            SELECT
                l.CATEGORY_NAME,
                l.total AS last_month_spend,
                s.mean_spend,
                s.std_spend,
                ROUND((l.total - s.mean_spend) / NULLIF(s.std_spend, 0), 2) AS z_score
            FROM latest l
            JOIN stats s ON s.CATEGORY_CODE = l.CATEGORY_CODE
            WHERE ABS((l.total - s.mean_spend) / NULLIF(s.std_spend, 0)) > 1.5
            ORDER BY ABS(z_score) DESC
            """,
            (store_id,),
        )

    if not anomalies:
        return {"anomalies": [], "narrative": "No significant expense anomalies detected last month."}

    # GenAI narrative on detected anomalies
    prompt = f"""You are a financial controller reviewing expense anomalies for {store_name}.

ANOMALIES DETECTED (last month vs 6-month average):
{json.dumps(anomalies, default=str, indent=2)}

Z-score > 1.5 means spending is unusually high; < -1.5 means unusually low.

Write a 2-3 sentence explanation of what these anomalies mean and what action management should take."""

    resp = await invoke(
        AIRequest(
            prompt=prompt,
            purpose="expense_anomaly_narrative",
            timeout_seconds=SYNC_TIMEOUT_SECONDS,
            max_output_tokens=400,
            temperature=0.3,
        ),
        fallback_text="Expense anomaly analysis temporarily unavailable.",
    )

    return {"anomalies": anomalies, "narrative": resp.text}
