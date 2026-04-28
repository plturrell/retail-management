-- ==========================================================================
-- RetailSG Snowflake Star Schema — Fact Tables
-- Database: RETAILSG  |  Schema: ANALYTICS
-- ==========================================================================

USE DATABASE RETAILSG;
USE SCHEMA ANALYTICS;

-- --------------------------------------------------------------------------
-- FACT_SALES  (one row per order line item)
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS FACT_SALES (
    SALE_SK         INT AUTOINCREMENT PRIMARY KEY,
    -- Natural keys (no FK constraints in Snowflake — enforced in ETL)
    LINE_ITEM_ID    VARCHAR(36)   NOT NULL UNIQUE,
    ORDER_ID        VARCHAR(36)   NOT NULL,
    ORDER_NUMBER    VARCHAR(50),
    -- Dimension keys
    SALE_DATE       DATE          NOT NULL,
    STORE_ID        VARCHAR(36),
    CUSTOMER_ID     VARCHAR(36),             -- nullable (walk-in)
    STAFF_ID        VARCHAR(36),             -- nullable (online)
    SKU_ID          VARCHAR(36)   NOT NULL,
    -- Measures
    QTY             INT           NOT NULL,
    UNIT_PRICE      FLOAT         NOT NULL,
    DISCOUNT        FLOAT         DEFAULT 0,
    LINE_TOTAL      FLOAT         NOT NULL,
    TAX_AMOUNT      FLOAT         DEFAULT 0,
    -- Attributes
    PAYMENT_METHOD  VARCHAR(50),
    SOURCE          VARCHAR(30),             -- nec_pos/hipay/airwallex/shopify/manual
    ORDER_STATUS    VARCHAR(20)
)
CLUSTER BY (SALE_DATE, STORE_ID);


-- --------------------------------------------------------------------------
-- FACT_PURCHASES  (one row per PO line item)
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS FACT_PURCHASES (
    PO_SK           INT AUTOINCREMENT PRIMARY KEY,
    PO_ITEM_ID      VARCHAR(36)   NOT NULL UNIQUE,
    PO_ID           VARCHAR(36)   NOT NULL,
    PO_NUMBER       VARCHAR(50),
    ORDER_DATE      DATE          NOT NULL,
    STORE_ID        VARCHAR(36),
    SUPPLIER_ID     VARCHAR(36),
    SKU_ID          VARCHAR(36),
    QTY_ORDERED     INT           NOT NULL,
    QTY_RECEIVED    INT           DEFAULT 0,
    UNIT_COST       FLOAT         NOT NULL,
    LINE_TOTAL      FLOAT         NOT NULL,
    CURRENCY        VARCHAR(3)    DEFAULT 'SGD',
    PO_STATUS       VARCHAR(30)
)
CLUSTER BY (ORDER_DATE, STORE_ID);


-- --------------------------------------------------------------------------
-- FACT_INVENTORY_SNAPSHOT  (nightly full snapshot — append-only)
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS FACT_INVENTORY_SNAPSHOT (
    SNAPSHOT_SK     INT AUTOINCREMENT PRIMARY KEY,
    SNAPSHOT_DATE   DATE          NOT NULL,
    INVENTORY_ID    VARCHAR(36),
    STORE_ID        VARCHAR(36)   NOT NULL,
    SKU_ID          VARCHAR(36)   NOT NULL,
    QTY_ON_HAND     INT           NOT NULL,
    REORDER_LEVEL   INT           DEFAULT 0,
    REORDER_QTY     INT           DEFAULT 0,
    LOCATION_STATUS VARCHAR(20)   DEFAULT 'STORE'
)
CLUSTER BY (SNAPSHOT_DATE, STORE_ID);


-- --------------------------------------------------------------------------
-- FACT_EXPENSES  (one row per expense claim)
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS FACT_EXPENSES (
    EXPENSE_SK      INT AUTOINCREMENT PRIMARY KEY,
    EXPENSE_ID      VARCHAR(36)   NOT NULL UNIQUE,
    EXPENSE_NUMBER  VARCHAR(50),
    STORE_ID        VARCHAR(36)   NOT NULL,
    CATEGORY_CODE   VARCHAR(20),
    CATEGORY_NAME   VARCHAR(255),
    VENDOR_NAME     VARCHAR(255),
    EXPENSE_DATE    DATE          NOT NULL,
    AMOUNT_EXCL_TAX FLOAT         NOT NULL,
    TAX_AMOUNT      FLOAT         DEFAULT 0,
    AMOUNT_INCL_TAX FLOAT         NOT NULL,
    PAYMENT_METHOD  VARCHAR(50),
    EXPENSE_STATUS  VARCHAR(20)
)
CLUSTER BY (EXPENSE_DATE, STORE_ID);


-- --------------------------------------------------------------------------
-- FACT_PAYROLL  (one row per payslip)
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS FACT_PAYROLL (
    PAYROLL_SK      INT AUTOINCREMENT PRIMARY KEY,
    PAYSLIP_ID      VARCHAR(36)   NOT NULL UNIQUE,
    PAYROLL_RUN_ID  VARCHAR(36)   NOT NULL,
    STORE_ID        VARCHAR(36)   NOT NULL,
    USER_ID         VARCHAR(36)   NOT NULL,
    PERIOD_START    DATE          NOT NULL,
    BASIC_SALARY    FLOAT         NOT NULL,
    HOURS_WORKED    FLOAT,
    OVERTIME_HOURS  FLOAT         DEFAULT 0,
    OVERTIME_PAY    FLOAT         DEFAULT 0,
    ALLOWANCES      FLOAT         DEFAULT 0,
    DEDUCTIONS      FLOAT         DEFAULT 0,
    GROSS_PAY       FLOAT         NOT NULL,
    CPF_EMPLOYEE    FLOAT         NOT NULL,
    CPF_EMPLOYER    FLOAT         NOT NULL,
    NET_PAY         FLOAT         NOT NULL
)
CLUSTER BY (PERIOD_START, STORE_ID);


-- ==========================================================================
-- ETL schema — watermarks and staging tables
-- ==========================================================================

CREATE SCHEMA IF NOT EXISTS ETL;

USE SCHEMA ETL;

CREATE TABLE IF NOT EXISTS ETL_WATERMARKS (
    TABLE_NAME    VARCHAR(100)  PRIMARY KEY,
    LAST_SYNC_AT  TIMESTAMP_TZ  NOT NULL
);
