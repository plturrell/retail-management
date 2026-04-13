-- ==========================================================================
-- RetailSG Snowflake Network Policy
-- Run as VICTORIAENSO (ACCOUNTADMIN) via Snowsight or SnowSQL.
--
-- Account:  NDKTJHV-MH65474  (GCP asia-southeast1)
-- Purpose:  Restrict logins to Cloud Run egress IPs + your admin IP only.
--           Blocks all other source IPs — including public internet.
--
-- BEFORE RUNNING:
--   1. Find your current admin IP:  curl -s https://api.ipify.org
--   2. Replace YOUR_ADMIN_IP below with that IP.
--   3. Optionally add your office/VPN CIDR to ALLOWED_IP_LIST.
--
-- GCP Cloud Run (asia-southeast1) shared egress CIDRs:
--   These are Google's NAT IP ranges for the asia-southeast1 region.
--   Cloud Run jobs share these ranges — there is no fixed per-service IP.
--   The ranges below are sourced from Google's published IP ranges
--   (https://www.gstatic.com/ipranges/cloud.json, cloud: "GOOGLE").
--
--   If you need a FIXED egress IP (recommended for production), set up a
--   Serverless VPC Connector → Cloud NAT with a reserved static IP, then
--   replace the broad CIDR below with that single /32.
--   See: scripts/gcp_setup_static_egress.sh (create to do this).
--
-- ==========================================================================

USE ROLE ACCOUNTADMIN;

-- ──────────────────────────────────────────────────────────────────────────
-- 1. Create the network policy
-- ──────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE NETWORK POLICY RETAILSG_NETWORK_POLICY
    ALLOWED_IP_LIST = (
        -- ── GCP Cloud Run / Cloud Build egress — asia-southeast1 ──────────
        -- Google Cloud NAT shared IP ranges for Singapore region.
        -- Replace with a static NAT IP /32 for tighter security.
        '34.87.0.0/16',        -- GCP asia-southeast1 (Singapore)
        '34.124.0.0/16',       -- GCP asia-southeast1 (Singapore)
        '35.185.176.0/20',     -- GCP asia-southeast1 (Singapore)
        '35.197.128.0/19',     -- GCP asia-southeast1 (Singapore)
        '104.155.192.0/18',    -- GCP asia-southeast1 (Singapore)

        -- ── GCP Cloud Build (same project) ────────────────────────────────
        '34.107.0.0/16',       -- GCP Cloud Build workers (global pool)

        -- ── Admin / developer access ──────────────────────────────────────
        -- Replace with your actual admin IP. Run: curl -s https://api.ipify.org
        '0.0.0.0/0'            -- PLACEHOLDER — replace before running!
    )
    BLOCKED_IP_LIST = ()
    COMMENT = 'RetailSG: allow Cloud Run egress + admin IP only';


-- ──────────────────────────────────────────────────────────────────────────
-- 2. Apply to the service user (narrow scope — safest first)
-- ──────────────────────────────────────────────────────────────────────────
ALTER USER RETAILSG_SVC SET NETWORK_POLICY = RETAILSG_NETWORK_POLICY;


-- ──────────────────────────────────────────────────────────────────────────
-- 3. (Optional) Apply account-wide AFTER verifying service still works
-- ──────────────────────────────────────────────────────────────────────────
-- WARNING: This blocks ALL users (including VICTORIAENSO) from any IP not
-- in the list above. Verify your admin IP is correct first!
--
-- ALTER ACCOUNT SET NETWORK_POLICY = RETAILSG_NETWORK_POLICY;


-- ──────────────────────────────────────────────────────────────────────────
-- 4. Verify
-- ──────────────────────────────────────────────────────────────────────────
SHOW NETWORK POLICIES;
DESCRIBE NETWORK POLICY RETAILSG_NETWORK_POLICY;

-- Check it was applied to the service user:
DESC USER RETAILSG_SVC;


-- ──────────────────────────────────────────────────────────────────────────
-- ROLLBACK (if something goes wrong)
-- ──────────────────────────────────────────────────────────────────────────
-- ALTER USER RETAILSG_SVC UNSET NETWORK_POLICY;
-- ALTER ACCOUNT UNSET NETWORK_POLICY;
-- DROP NETWORK POLICY IF EXISTS RETAILSG_NETWORK_POLICY;
