-- Find statistics series by name. ~170k series from BLS, the Fed, BEA, and Census.
-- Edit the ILIKE patterns, then run in Snowsight.
--
-- Headline series IDs we already verified:
--   LNS14000000.M_SA          Unemployment rate, monthly, seasonally adjusted (fraction: 0.043 = 4.3%)
--   CES0000000001.M_SA        Total nonfarm jobs, monthly, seasonally adjusted (count)
--   CUSRSA0SA01982-84.M       CPI all items, monthly, seasonally adjusted (index, 1982-84 = 100)
--   BEA_NIPA_1.1.1_A191RL_Q   Real GDP growth, quarterly (percent change, annual rate)

SELECT VARIABLE, VARIABLE_NAME, FREQUENCY, UNIT, RELEASE_SOURCE
FROM SNOWFLAKE_PUBLIC_DATA_FREE.PUBLIC_DATA_FREE.FINANCIAL_ECONOMIC_INDICATORS_ATTRIBUTES
WHERE VARIABLE_NAME ILIKE '%unemployment rate%'
  AND FREQUENCY = 'Monthly'
ORDER BY LENGTH(VARIABLE_NAME)
LIMIT 25;
