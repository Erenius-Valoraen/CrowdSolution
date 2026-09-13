-- Run as the ACCOUNT OWNER (Abhi) to give a teammate access to the shared account.
-- Replace TEAMMATE_NAME and TEMP_PASSWORD, run, then send them the login details privately
-- (not in the repo, not in a public channel). They must change the password on first login.

USE ROLE ACCOUNTADMIN;

CREATE USER IF NOT EXISTS TEAMMATE_NAME
  PASSWORD = 'TEMP_PASSWORD'
  MUST_CHANGE_PASSWORD = TRUE
  DEFAULT_ROLE = SYSADMIN
  DEFAULT_WAREHOUSE = COMPUTE_WH;

GRANT ROLE SYSADMIN TO USER TEAMMATE_NAME;

-- Let their access token work without an IP network policy (same as 01_account_setup.sql)
ALTER USER TEAMMATE_NAME SET AUTHENTICATION POLICY CROWDSOLUTION.ADMIN.HACK_PAT_POLICY;
