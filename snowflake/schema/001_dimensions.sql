-- ==========================================================================
-- RetailSG Snowflake Star Schema — Dimension Tables
-- Database: RETAILSG  |  Schema: ANALYTICS
-- Run once during initial setup. All dims use MERGE in ETL for idempotency.
-- ==========================================================================

USE DATABASE RETAILSG;
USE SCHEMA ANALYTICS;

-- --------------------------------------------------------------------------
-- DIM_DATE  (pre-populated calendar, Singapore context)
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS DIM_DATE (
    DATE_KEY        INT           PRIMARY KEY,   -- YYYYMMDD integer key
    FULL_DATE       DATE          NOT NULL,
    DAY_OF_WEEK     VARCHAR(10)   NOT NULL,       -- 'Monday', etc.
    DAY_NUM         INT           NOT NULL,       -- 1=Mon … 7=Sun
    WEEK_NUM        INT           NOT NULL,       -- ISO week number
    MONTH_NUM       INT           NOT NULL,
    MONTH_NAME      VARCHAR(10)   NOT NULL,
    QUARTER         INT           NOT NULL,
    YEAR            INT           NOT NULL,
    IS_WEEKEND      BOOLEAN       NOT NULL,
    IS_SG_PUBLIC_HOLIDAY BOOLEAN  NOT NULL DEFAULT FALSE,
    HOLIDAY_NAME    VARCHAR(100)
);

-- Populate 10 years of dates (2020-01-01 → 2029-12-31)
INSERT INTO DIM_DATE (DATE_KEY, FULL_DATE, DAY_OF_WEEK, DAY_NUM, WEEK_NUM,
                      MONTH_NUM, MONTH_NAME, QUARTER, YEAR, IS_WEEKEND)
SELECT
    TO_NUMBER(TO_CHAR(d.VALUE::DATE, 'YYYYMMDD'))             AS DATE_KEY,
    d.VALUE::DATE                                              AS FULL_DATE,
    DAYNAME(d.VALUE::DATE)                                    AS DAY_OF_WEEK,
    DAYOFWEEKISO(d.VALUE::DATE)                               AS DAY_NUM,
    WEEKISO(d.VALUE::DATE)                                    AS WEEK_NUM,
    MONTH(d.VALUE::DATE)                                      AS MONTH_NUM,
    MONTHNAME(d.VALUE::DATE)                                  AS MONTH_NAME,
    QUARTER(d.VALUE::DATE)                                    AS QUARTER,
    YEAR(d.VALUE::DATE)                                       AS YEAR,
    DAYOFWEEKISO(d.VALUE::DATE) IN (6,7)                      AS IS_WEEKEND
FROM TABLE(FLATTEN(ARRAY_GENERATE_RANGE(
    DATEDIFF('day', '2020-01-01'::DATE, '2030-01-01'::DATE)
))) d
WHERE NOT EXISTS (SELECT 1 FROM DIM_DATE WHERE DATE_KEY = TO_NUMBER(TO_CHAR(d.VALUE::DATE, 'YYYYMMDD')));

-- Mark Singapore public holidays (add more as needed)
UPDATE DIM_DATE SET IS_SG_PUBLIC_HOLIDAY = TRUE, HOLIDAY_NAME = 'New Year''s Day'
WHERE MONTH_NUM = 1  AND DAY_OF_WEEK NOT IN ('Saturday','Sunday') AND FULL_DATE IN
    ('2024-01-01','2025-01-01','2026-01-01','2027-01-01','2028-01-01','2029-01-01');

UPDATE DIM_DATE SET IS_SG_PUBLIC_HOLIDAY = TRUE, HOLIDAY_NAME = 'National Day'
WHERE MONTH_NUM = 8 AND MONTH_NUM = 9 AND FULL_DATE IN
    ('2024-08-09','2025-08-09','2026-08-09','2027-08-09','2028-08-09','2029-08-09');

UPDATE DIM_DATE SET IS_SG_PUBLIC_HOLIDAY = TRUE, HOLIDAY_NAME = 'Christmas Day'
WHERE FULL_DATE IN
    ('2024-12-25','2025-12-25','2026-12-25','2027-12-25','2028-12-25','2029-12-25');


-- --------------------------------------------------------------------------
-- DIM_STORE
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS DIM_STORE (
    STORE_KEY   INT AUTOINCREMENT PRIMARY KEY,
    STORE_ID    VARCHAR(36)   NOT NULL UNIQUE,    -- UUID from PostgreSQL
    STORE_CODE  VARCHAR(20)   NOT NULL,
    NAME        VARCHAR(255)  NOT NULL,
    STORE_TYPE  VARCHAR(50),
    CITY        VARCHAR(100),
    COUNTRY     VARCHAR(100),
    CURRENCY    VARCHAR(3)    DEFAULT 'SGD',
    IS_ACTIVE   BOOLEAN       DEFAULT TRUE,
    CREATED_AT  TIMESTAMP_TZ
);


-- --------------------------------------------------------------------------
-- DIM_PRODUCT
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS DIM_PRODUCT (
    PRODUCT_KEY     INT AUTOINCREMENT PRIMARY KEY,
    SKU_ID          VARCHAR(36)   NOT NULL UNIQUE,
    SKU_CODE        VARCHAR(16)   NOT NULL,
    DESCRIPTION     VARCHAR(255),
    CATEGORY_CODE   VARCHAR(50),
    CATEGORY_NAME   VARCHAR(255),
    BRAND           VARCHAR(255),
    GENDER          VARCHAR(20),
    AGE_GROUP       VARCHAR(20),
    TAX_CODE        VARCHAR(1)    DEFAULT 'G',
    COST_PRICE      FLOAT,
    USE_STOCK       BOOLEAN       DEFAULT TRUE,
    BLOCK_SALES     BOOLEAN       DEFAULT FALSE,
    CREATED_AT      TIMESTAMP_TZ
);


-- --------------------------------------------------------------------------
-- DIM_CUSTOMER
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS DIM_CUSTOMER (
    CUSTOMER_KEY          INT AUTOINCREMENT PRIMARY KEY,
    CUSTOMER_ID           VARCHAR(36)  NOT NULL UNIQUE,
    CUSTOMER_CODE         VARCHAR(30)  NOT NULL,
    LOYALTY_TIER          VARCHAR(20),          -- bronze/silver/gold/platinum
    GENDER                VARCHAR(30),
    AGE_BAND              VARCHAR(10),           -- 18-24, 25-34, …
    REGISTERED_STORE_CODE VARCHAR(20),
    IS_ACTIVE             BOOLEAN      DEFAULT TRUE,
    CREATED_AT            TIMESTAMP_TZ
);


-- --------------------------------------------------------------------------
-- DIM_SUPPLIER
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS DIM_SUPPLIER (
    SUPPLIER_KEY    INT AUTOINCREMENT PRIMARY KEY,
    SUPPLIER_ID     VARCHAR(36)   NOT NULL UNIQUE,
    SUPPLIER_CODE   VARCHAR(30)   NOT NULL,
    NAME            VARCHAR(255)  NOT NULL,
    COUNTRY         VARCHAR(100),
    CURRENCY        VARCHAR(3)    DEFAULT 'SGD',
    IS_ACTIVE       BOOLEAN       DEFAULT TRUE,
    CREATED_AT      TIMESTAMP_TZ
);


-- --------------------------------------------------------------------------
-- DIM_STAFF
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS DIM_STAFF (
    STAFF_KEY       INT AUTOINCREMENT PRIMARY KEY,
    USER_ID         VARCHAR(36)   NOT NULL UNIQUE,
    FULL_NAME       VARCHAR(255)  NOT NULL,
    DEPARTMENT_CODE VARCHAR(20),
    DEPARTMENT_NAME VARCHAR(255),
    JOB_TITLE       VARCHAR(255),
    EMPLOYMENT_TYPE VARCHAR(20),   -- full_time/part_time/contract/intern
    NATIONALITY     VARCHAR(20)    -- citizen/pr/foreigner
);
