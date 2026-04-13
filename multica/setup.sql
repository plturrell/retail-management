-- Setup Script: Multica Deployment onto Snowflake SPCS
-- Ensure you are using the ACCOUNTADMIN role or a role with full integration privileges

USE ROLE ACCOUNTADMIN;
USE DATABASE RETAILMANAGEMENT;
USE SCHEMA PUBLIC;

-- 1. Create a dedicated Compute Pool for running AI inferences
-- Using GPU pools is recommended if scaling large LLM operations, but STANDARD_1 is fine for API wrapping
CREATE COMPUTE POOL IF NOT EXISTS multica_pool
    MIN_NODES = 1
    MAX_NODES = 2
    INSTANCE_FAMILY = CPU_X64_S;

-- 2. Create the Image Repository where we will push the Docker container
CREATE IMAGE REPOSITORY IF NOT EXISTS multica_repo;
SHOW IMAGE REPOSITORIES;
-- Note: Use the repository URL from the output above to tag and push the `multica/Dockerfile`

-- 3. Define the Network Rule (For Egress if Multica needs to call out, though we keep it local for security)
-- Expose the API to the public internet temporarily to link with FastAPI backend
CREATE OR REPLACE NETWORK RULE multica_api_ingress_rule
    MODE = INGRESS
    TYPE = HOST_PORT
    VALUE_LIST = ('0.0.0.0:8000');
    
CREATE OR REPLACE EXTERNAL ACCESS INTEGRATION multica_ingress_integration
    ALLOWED_NETWORK_RULES = (multica_api_ingress_rule)
    ENABLED = true;

-- 4. Create the Service (Once the Docker image is pushed to `multica_repo/multica:latest`)
CREATE SERVICE IF NOT EXISTS multica_service
    IN COMPUTE POOL multica_pool
    FROM SPECIFICATION $$
    spec:
      containers:
      - name: multica-api
        image: /retailmanagement/public/multica_repo/multica:latest
        env:
          SNOWFLAKE_WAREHOUSE: COMPUTE_WH
        ports:
        - name: api-port
          port: 8000
      endpoints:
      - name: multica-endpoint
        port: api-port
        public: true
    $$
    MIN_INSTANCES=1
    MAX_INSTANCES=2;

-- 5. Monitor Service Status
CALL SYSTEM$GET_SERVICE_STATUS('multica_service');

-- 6. Retrieve the Secure Public Endpoints to map to `backend/app/config.py`
SHOW ENDPOINTS IN SERVICE multica_service;
