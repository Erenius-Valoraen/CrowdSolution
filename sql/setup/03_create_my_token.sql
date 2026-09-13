-- Run as YOURSELF in Snowsight after logging in, to create your personal access token.
-- The TOKEN_SECRET appears once in the result. Copy it, then run:
--     python scripts/configure_snowflake.py
-- Never paste the token into the repo, chat, or Slack.

ALTER USER ADD PROGRAMMATIC ACCESS TOKEN CROWDSOLUTION_DEV
  ROLE_RESTRICTION = 'SYSADMIN'
  DAYS_TO_EXPIRY = 14;

-- Lost it or leaked it? Remove it and create a new one:
-- ALTER USER REMOVE PROGRAMMATIC ACCESS TOKEN CROWDSOLUTION_DEV;
