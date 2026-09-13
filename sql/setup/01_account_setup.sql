-- CrowdSolution one-time Snowflake setup. Run the whole thing in a Snowsight worksheet
-- (Projects > Workspaces or Worksheets > + > SQL), then click "Run All".

USE ROLE ACCOUNTADMIN;

-- 1. Free public data (jobs, inflation, GDP, crime, OpenAlex, CFPB, ...)
CREATE DATABASE IF NOT EXISTS SNOWFLAKE_PUBLIC_DATA_FREE FROM LISTING 'GZTSZ290BV255';

-- 2. Allow every Cortex model, keep credit burn low
ALTER ACCOUNT SET CORTEX_ENABLED_CROSS_REGION = 'ANY_REGION';
ALTER WAREHOUSE COMPUTE_WH SET AUTO_SUSPEND = 60;

-- 3. App role gets the data, the warehouse, and a project database
GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE_PUBLIC_DATA_FREE TO ROLE SYSADMIN;
GRANT USAGE ON WAREHOUSE COMPUTE_WH TO ROLE SYSADMIN;
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE SYSADMIN;
CREATE DATABASE IF NOT EXISTS CROWDSOLUTION;
GRANT OWNERSHIP ON DATABASE CROWDSOLUTION TO ROLE SYSADMIN COPY CURRENT GRANTS;
CREATE SCHEMA IF NOT EXISTS CROWDSOLUTION.ADMIN;

-- 4. Let access tokens work without an IP network policy (venue Wi-Fi IPs change)
CREATE AUTHENTICATION POLICY IF NOT EXISTS CROWDSOLUTION.ADMIN.HACK_PAT_POLICY
  PAT_POLICY = (NETWORK_POLICY_EVALUATION = ENFORCED_NOT_REQUIRED);
SET stmt = 'ALTER USER "' || CURRENT_USER() || '" SET AUTHENTICATION POLICY CROWDSOLUTION.ADMIN.HACK_PAT_POLICY';
EXECUTE IMMEDIATE $stmt;

-- 5. Your account identifier and username, for the config file.
--    Run All only shows the LAST result, so to see this one, click inside the SELECT and press Ctrl+Enter.
SELECT CURRENT_ORGANIZATION_NAME() || '-' || CURRENT_ACCOUNT_NAME() AS ACCOUNT_IDENTIFIER,
       CURRENT_USER() AS USERNAME;

-- 6. Create the token. This is last on purpose so Run All shows its result.
--    COPY THE TOKEN_SECRET VALUE RIGHT AWAY; it is shown once. Do not re-run this line (it errors if the token exists).
ALTER USER ADD PROGRAMMATIC ACCESS TOKEN CROWDSOLUTION_DEV
  ROLE_RESTRICTION = 'SYSADMIN'
  DAYS_TO_EXPIRY = 14;
