-- ==========================================================================
-- RetailSG — Snowflake Cortex ML views and helper queries
-- Database: RETAILSG  |  Schema: ANALYTICS
--
-- These views expose clean inputs to Cortex ML functions.
-- The ETL intelligence service calls these dynamically, but they are
-- also useful for direct BI tool consumption.
-- ==========================================================================

USE DATABASE RETAILSG;
USE SCHEMA ANALYTICS;


-- --------------------------------------------------------------------------
-- V_DAILY_SALES_TIMESERIES
-- Input view for Cortex FORECAST (demand forecasting)
-- --------------------------------------------------------------------------
CREATE OR REPLACE VIEW V_DAILY_SALES_TIMESERIES AS
SELECT
    f.SALE_DATE                              AS TS,
    f.SKU_ID                                 AS SERIES,
    f.STORE_ID                               AS STORE_ID,
    p.SKU_CODE,
    p.DESCRIPTION,
    p.CATEGORY_NAME,
    SUM(f.QTY)                               AS TOTAL_QTY,
    SUM(f.LINE_TOTAL)                        AS TOTAL_REVENUE,
    COUNT(DISTINCT f.ORDER_ID)               AS ORDER_COUNT
FROM FACT_SALES f
JOIN DIM_PRODUCT p ON p.SKU_ID = f.SKU_ID
GROUP BY f.SALE_DATE, f.SKU_ID, f.STORE_ID, p.SKU_CODE, p.DESCRIPTION, p.CATEGORY_NAME;


-- --------------------------------------------------------------------------
-- V_DAILY_REVENUE_TIMESERIES
-- Input view for Cortex ANOMALY_DETECTION (sales anomaly detection)
-- --------------------------------------------------------------------------
CREATE OR REPLACE VIEW V_DAILY_REVENUE_TIMESERIES AS
SELECT
    SALE_DATE                                AS TS,
    STORE_ID,
    SUM(LINE_TOTAL)                          AS DAILY_REVENUE,
    SUM(QTY)                                 AS DAILY_UNITS,
    COUNT(DISTINCT ORDER_ID)                 AS DAILY_ORDERS,
    SUM(DISCOUNT)                            AS DAILY_DISCOUNTS
FROM FACT_SALES
GROUP BY SALE_DATE, STORE_ID;


-- --------------------------------------------------------------------------
-- V_STORE_MONTHLY_PERFORMANCE
-- Pre-aggregated store KPIs — consumed by Cortex COMPLETE for narrative gen
-- --------------------------------------------------------------------------
CREATE OR REPLACE VIEW V_STORE_MONTHLY_PERFORMANCE AS
SELECT
    DATE_TRUNC('month', f.SALE_DATE)         AS MONTH,
    s.STORE_CODE,
    s.NAME                                   AS STORE_NAME,
    s.STORE_TYPE,
    COUNT(DISTINCT f.ORDER_ID)               AS ORDERS,
    SUM(f.LINE_TOTAL)                        AS REVENUE,
    SUM(f.DISCOUNT)                          AS DISCOUNTS,
    SUM(f.TAX_AMOUNT)                        AS GST_COLLECTED,
    SUM(f.QTY)                               AS UNITS_SOLD,
    COUNT(DISTINCT f.CUSTOMER_ID)            AS UNIQUE_CUSTOMERS,
    AVG(f.LINE_TOTAL)                        AS AVG_LINE_VALUE
FROM FACT_SALES f
JOIN DIM_STORE s ON s.STORE_ID = f.STORE_ID
GROUP BY 1, s.STORE_CODE, s.NAME, s.STORE_TYPE;


-- --------------------------------------------------------------------------
-- V_PRODUCT_PERFORMANCE
-- SKU-level contribution to revenue and margin
-- --------------------------------------------------------------------------
CREATE OR REPLACE VIEW V_PRODUCT_PERFORMANCE AS
SELECT
    p.SKU_CODE,
    p.DESCRIPTION,
    p.CATEGORY_NAME,
    p.BRAND,
    p.GENDER,
    p.AGE_GROUP,
    p.COST_PRICE,
    SUM(f.QTY)                               AS UNITS_SOLD,
    SUM(f.LINE_TOTAL)                        AS TOTAL_REVENUE,
    SUM(f.DISCOUNT)                          AS TOTAL_DISCOUNTS,
    AVG(f.UNIT_PRICE)                        AS AVG_SELLING_PRICE,
    SUM(f.LINE_TOTAL) - (SUM(f.QTY) * p.COST_PRICE) AS GROSS_PROFIT,
    ROUND(
        (SUM(f.LINE_TOTAL) - SUM(f.QTY) * p.COST_PRICE) / NULLIF(SUM(f.LINE_TOTAL), 0) * 100
    , 2)                                      AS GROSS_MARGIN_PCT,
    MIN(f.SALE_DATE)                         AS FIRST_SALE_DATE,
    MAX(f.SALE_DATE)                         AS LAST_SALE_DATE
FROM FACT_SALES f
JOIN DIM_PRODUCT p ON p.SKU_ID = f.SKU_ID
GROUP BY p.SKU_CODE, p.DESCRIPTION, p.CATEGORY_NAME, p.BRAND,
         p.GENDER, p.AGE_GROUP, p.COST_PRICE;


-- --------------------------------------------------------------------------
-- V_CUSTOMER_LTV
-- Customer lifetime value and purchase behaviour
-- --------------------------------------------------------------------------
CREATE OR REPLACE VIEW V_CUSTOMER_LTV AS
SELECT
    c.CUSTOMER_ID,
    c.CUSTOMER_CODE,
    c.LOYALTY_TIER,
    c.GENDER,
    c.AGE_BAND,
    c.REGISTERED_STORE_CODE,
    COUNT(DISTINCT f.ORDER_ID)               AS TOTAL_ORDERS,
    SUM(f.LINE_TOTAL)                        AS LIFETIME_REVENUE,
    AVG(f.LINE_TOTAL)                        AS AVG_ORDER_VALUE,
    MIN(f.SALE_DATE)                         AS FIRST_PURCHASE_DATE,
    MAX(f.SALE_DATE)                         AS LAST_PURCHASE_DATE,
    DATEDIFF('day', MIN(f.SALE_DATE), MAX(f.SALE_DATE)) AS CUSTOMER_TENURE_DAYS,
    CASE
        WHEN COUNT(DISTINCT f.ORDER_ID) = 1 THEN 'one_time'
        WHEN COUNT(DISTINCT f.ORDER_ID) <= 3 THEN 'occasional'
        WHEN COUNT(DISTINCT f.ORDER_ID) <= 8 THEN 'regular'
        ELSE 'loyal'
    END                                       AS PURCHASE_FREQUENCY_BAND
FROM FACT_SALES f
JOIN DIM_CUSTOMER c ON c.CUSTOMER_ID = f.CUSTOMER_ID
WHERE f.CUSTOMER_ID IS NOT NULL
GROUP BY c.CUSTOMER_ID, c.CUSTOMER_CODE, c.LOYALTY_TIER, c.GENDER,
         c.AGE_BAND, c.REGISTERED_STORE_CODE;


-- --------------------------------------------------------------------------
-- V_INVENTORY_STATUS
-- Latest snapshot with demand context for reorder intelligence
-- --------------------------------------------------------------------------
CREATE OR REPLACE VIEW V_INVENTORY_STATUS AS
WITH latest_snap AS (
    SELECT STORE_ID, SKU_ID, QTY_ON_HAND, REORDER_LEVEL, REORDER_QTY, LOCATION_STATUS
    FROM FACT_INVENTORY_SNAPSHOT
    WHERE SNAPSHOT_DATE = (SELECT MAX(SNAPSHOT_DATE) FROM FACT_INVENTORY_SNAPSHOT)
),
avg_demand AS (
    SELECT SKU_ID, STORE_ID,
           AVG(DAILY_QTY) AS AVG_DAILY_DEMAND,
           STDDEV(DAILY_QTY) AS STD_DAILY_DEMAND
    FROM (
        SELECT SKU_ID, STORE_ID, SALE_DATE, SUM(QTY) AS DAILY_QTY
        FROM FACT_SALES
        WHERE SALE_DATE >= DATEADD(DAY, -30, CURRENT_DATE())
        GROUP BY SKU_ID, STORE_ID, SALE_DATE
    ) GROUP BY SKU_ID, STORE_ID
)
SELECT
    s.STORE_CODE,
    p.SKU_CODE,
    p.DESCRIPTION,
    p.CATEGORY_NAME,
    p.BRAND,
    i.QTY_ON_HAND,
    i.REORDER_LEVEL,
    i.REORDER_QTY,
    i.LOCATION_STATUS,
    ROUND(d.AVG_DAILY_DEMAND, 2)             AS AVG_DAILY_DEMAND,
    CASE
        WHEN d.AVG_DAILY_DEMAND > 0
        THEN ROUND(i.QTY_ON_HAND / d.AVG_DAILY_DEMAND, 1)
        ELSE 999
    END                                       AS DAYS_OF_STOCK,
    CASE
        WHEN i.QTY_ON_HAND <= i.REORDER_LEVEL THEN 'CRITICAL'
        WHEN d.AVG_DAILY_DEMAND > 0 AND i.QTY_ON_HAND / d.AVG_DAILY_DEMAND < 14 THEN 'LOW'
        WHEN d.AVG_DAILY_DEMAND > 0 AND i.QTY_ON_HAND / d.AVG_DAILY_DEMAND < 30 THEN 'ADEQUATE'
        ELSE 'HEALTHY'
    END                                       AS STOCK_STATUS
FROM latest_snap i
JOIN DIM_STORE s ON s.STORE_ID = i.STORE_ID
JOIN DIM_PRODUCT p ON p.SKU_ID = i.SKU_ID
LEFT JOIN avg_demand d ON d.SKU_ID = i.SKU_ID AND d.STORE_ID = i.STORE_ID;


-- --------------------------------------------------------------------------
-- V_STAFF_PRODUCTIVITY
-- Labour cost vs revenue contribution per staff member
-- --------------------------------------------------------------------------
CREATE OR REPLACE VIEW V_STAFF_PRODUCTIVITY AS
SELECT
    st.FULL_NAME,
    st.DEPARTMENT_NAME,
    st.JOB_TITLE,
    st.EMPLOYMENT_TYPE,
    COUNT(DISTINCT f.ORDER_ID)               AS ORDERS_PROCESSED,
    SUM(f.LINE_TOTAL)                        AS REVENUE_GENERATED,
    AVG(pr.GROSS_PAY)                        AS AVG_GROSS_PAY,
    AVG(pr.HOURS_WORKED)                     AS AVG_HOURS_WORKED,
    ROUND(SUM(f.LINE_TOTAL) / NULLIF(AVG(pr.GROSS_PAY), 0), 2) AS REVENUE_TO_COST_RATIO
FROM FACT_SALES f
JOIN DIM_STAFF st ON st.USER_ID = f.STAFF_ID
LEFT JOIN FACT_PAYROLL pr ON pr.USER_ID = f.STAFF_ID
    AND DATE_TRUNC('month', pr.PERIOD_START) = DATE_TRUNC('month', f.SALE_DATE)
WHERE f.STAFF_ID IS NOT NULL
GROUP BY st.FULL_NAME, st.DEPARTMENT_NAME, st.JOB_TITLE, st.EMPLOYMENT_TYPE;


-- --------------------------------------------------------------------------
-- Cortex COMPLETE helper: executive summary of store month
-- Usage: SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large2', <prompt>) ...
-- The intelligence service builds these prompts dynamically.
-- --------------------------------------------------------------------------

-- Example stored procedure for scheduled monthly summaries
CREATE OR REPLACE PROCEDURE GENERATE_MONTHLY_SUMMARY(STORE_CODE VARCHAR, YEAR_MONTH VARCHAR)
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
DECLARE
    kpi_data VARIANT;
    summary  VARCHAR;
BEGIN
    SELECT OBJECT_CONSTRUCT(
        'revenue',   SUM(REVENUE),
        'orders',    SUM(ORDERS),
        'units',     SUM(UNITS_SOLD),
        'customers', SUM(UNIQUE_CUSTOMERS),
        'discounts', SUM(DISCOUNTS)
    ) INTO :kpi_data
    FROM V_STORE_MONTHLY_PERFORMANCE
    WHERE STORE_CODE = :STORE_CODE
      AND TO_CHAR(MONTH, 'YYYY-MM') = :YEAR_MONTH;

    SELECT SNOWFLAKE.CORTEX.COMPLETE(
        'mistral-large2',
        'You are a retail analyst. Summarise this monthly KPI data in 2 sentences: ' || :kpi_data::VARCHAR
    ) INTO :summary;

    RETURN :summary;
END;
$$;
