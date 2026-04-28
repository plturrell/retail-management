-- ==========================================================================
-- RetailSG Snowflake Bootstrap
-- Run ONCE as VICTORIAENSO (ACCOUNTADMIN) via Snowsight or SnowSQL.
--
-- Account:  NDKTJHV-MH65474
-- Org:      NDKTJHV
-- Server:   NDKTJHV-MH65474.snowflakecomputing.com
-- Cloud:    GCP  |  Edition: Standard
--
-- What this script does:
--   1. Creates the RETAILSG database + ANALYTICS and ETL schemas
--   2. Creates RETAILSG_WH virtual warehouse (X-Small, auto-suspend 60s)
--   3. Creates RETAILSG_ROLE with least-privilege grants
--   4. Creates RETAILSG_SVC service user bound to that role
--   5. Grants usage on all future tables so ETL MERGEs work
--
-- After running this script:
--   • Copy the RETAILSG_SVC password you set below into GCP Secret Manager:
--       gcloud secrets versions add retailsg-snowflake-password --data-file=- <<< "YOUR_PASSWORD"
--   • Then deploy: cd backend && gcloud builds submit --config=cloudbuild.yaml .
-- ==========================================================================

USE ROLE ACCOUNTADMIN;

-- ──────────────────────────────────────────────────────────────────────────
-- 1. Database & Schemas
-- ──────────────────────────────────────────────────────────────────────────
CREATE DATABASE IF NOT EXISTS RETAILSG
    DATA_RETENTION_TIME_IN_DAYS = 7
    COMMENT = 'RetailSG analytics data warehouse';

CREATE SCHEMA IF NOT EXISTS RETAILSG.ANALYTICS
    DATA_RETENTION_TIME_IN_DAYS = 7
    COMMENT = 'Star-schema dimensions and facts';

CREATE SCHEMA IF NOT EXISTS RETAILSG.ETL
    DATA_RETENTION_TIME_IN_DAYS = 1
    COMMENT = 'Staging tables and ETL watermarks';


-- ──────────────────────────────────────────────────────────────────────────
-- 2. Virtual Warehouse
-- ──────────────────────────────────────────────────────────────────────────
CREATE WAREHOUSE IF NOT EXISTS RETAILSG_WH
    WAREHOUSE_SIZE   = 'X-SMALL'
    AUTO_SUSPEND     = 60          -- suspend after 60 seconds of inactivity
    AUTO_RESUME      = TRUE
    INITIALLY_SUSPENDED = TRUE
    COMMENT = 'RetailSG API + ETL warehouse';


-- ──────────────────────────────────────────────────────────────────────────
-- 3. Role
-- ──────────────────────────────────────────────────────────────────────────
CREATE ROLE IF NOT EXISTS RETAILSG_ROLE
    COMMENT = 'Least-privilege role for the RetailSG API service account';

-- Warehouse usage
GRANT USAGE ON WAREHOUSE RETAILSG_WH TO ROLE RETAILSG_ROLE;

-- Database + schema usage
GRANT USAGE ON DATABASE RETAILSG TO ROLE RETAILSG_ROLE;
GRANT USAGE ON SCHEMA RETAILSG.ANALYTICS TO ROLE RETAILSG_ROLE;
GRANT USAGE ON SCHEMA RETAILSG.ETL       TO ROLE RETAILSG_ROLE;

-- Full DML on existing tables
GRANT SELECT, INSERT, UPDATE, DELETE, MERGE ON ALL TABLES IN SCHEMA RETAILSG.ANALYTICS TO ROLE RETAILSG_ROLE;
GRANT SELECT, INSERT, UPDATE, DELETE, MERGE ON ALL TABLES IN SCHEMA RETAILSG.ETL       TO ROLE RETAILSG_ROLE;

-- Future tables (ETL creates staging tables dynamically)
GRANT SELECT, INSERT, UPDATE, DELETE, MERGE ON FUTURE TABLES IN SCHEMA RETAILSG.ANALYTICS TO ROLE RETAILSG_ROLE;
GRANT SELECT, INSERT, UPDATE, DELETE, MERGE ON FUTURE TABLES IN SCHEMA RETAILSG.ETL       TO ROLE RETAILSG_ROLE;

-- Views (Cortex views created by DDL scripts)
GRANT SELECT ON ALL VIEWS IN SCHEMA RETAILSG.ANALYTICS TO ROLE RETAILSG_ROLE;
GRANT SELECT ON FUTURE VIEWS IN SCHEMA RETAILSG.ANALYTICS TO ROLE RETAILSG_ROLE;

-- Create temp objects (needed for Cortex FORECAST input views)
GRANT CREATE TEMPORARY TABLE ON SCHEMA RETAILSG.ANALYTICS TO ROLE RETAILSG_ROLE;
GRANT CREATE TEMPORARY TABLE ON SCHEMA RETAILSG.ETL       TO ROLE RETAILSG_ROLE;

-- Create tables (ETL creates staging tables on first run)
GRANT CREATE TABLE ON SCHEMA RETAILSG.ANALYTICS TO ROLE RETAILSG_ROLE;
GRANT CREATE TABLE ON SCHEMA RETAILSG.ETL       TO ROLE RETAILSG_ROLE;

-- Create views (intelligence service creates temp forecast views)
GRANT CREATE VIEW ON SCHEMA RETAILSG.ANALYTICS TO ROLE RETAILSG_ROLE;

-- Cortex ML functions (Snowflake built-in — no extra grant needed on Standard edition)
-- GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE RETAILSG_ROLE;


-- ──────────────────────────────────────────────────────────────────────────
-- 4. Service User
-- !!  CHANGE THE PASSWORD BELOW before running  !!
-- ──────────────────────────────────────────────────────────────────────────
CREATE USER IF NOT EXISTS RETAILSG_SVC
    LOGIN_NAME      = 'RETAILSG_SVC'
    DISPLAY_NAME    = 'RetailSG API Service Account'
    PASSWORD        = 'Rsg#Live2026!'    -- << CHANGE THIS before running >>
    DEFAULT_ROLE    = RETAILSG_ROLE
    DEFAULT_WAREHOUSE = RETAILSG_WH
    DEFAULT_NAMESPACE  = RETAILSG.ANALYTICS
    MUST_CHANGE_PASSWORD = FALSE
    COMMENT = 'Service user for Cloud Run API — do not use for human login';

GRANT ROLE RETAILSG_ROLE TO USER RETAILSG_SVC;

-- Revoke SYSADMIN from the service user (defence-in-depth)
-- (New users only inherit PUBLIC by default — this is a no-op but kept for clarity)
REVOKE ROLE SYSADMIN FROM USER RETAILSG_SVC;


-- ──────────────────────────────────────────────────────────────────────────
-- 5. Verify
-- ──────────────────────────────────────────────────────────────────────────
SHOW DATABASES LIKE 'RETAILSG';
SHOW WAREHOUSES LIKE 'RETAILSG_WH';
SHOW ROLES LIKE 'RETAILSG_ROLE';
SHOW USERS LIKE 'RETAILSG_SVC';

-- ──────────────────────────────────────────────────────────────────────────
-- 6. Next steps (run as RETAILSG_SVC to verify access)
-- ──────────────────────────────────────────────────────────────────────────
-- USE ROLE RETAILSG_ROLE;
-- USE WAREHOUSE RETAILSG_WH;
-- USE DATABASE RETAILSG;
-- USE SCHEMA ANALYTICS;
-- SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE();
--
-- Then run the schema DDL files in order:
--   snowflake/schema/001_dimensions.sql
--   snowflake/schema/002_facts.sql
--   snowflake/schema/003_cortex_views.sql
