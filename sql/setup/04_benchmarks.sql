-- Cached benchmark tables used by the legit checker.
-- The census rent series live in a very large shared view that takes 12-16 seconds per lookup.
-- Copying the few series we need into our own database makes lookups take well under a second.
-- Run once as SYSADMIN (or rerun to refresh). Takes about 10 seconds.

USE ROLE SYSADMIN;
CREATE SCHEMA IF NOT EXISTS CROWDSOLUTION.BENCHMARKS;

-- Median gross rent (American Community Survey, 1-year estimates) for US cities, states, and the country,
-- overall and by number of bedrooms.
CREATE OR REPLACE TABLE CROWDSOLUTION.BENCHMARKS.RENT AS
SELECT t.GEO_ID,
       g.GEO_NAME,
       g.LEVEL,
       CASE WHEN g.LEVEL = 'City'  THEN 'geoId/' || SUBSTR(t.GEO_ID, 7, 2)   -- city IDs start with the state FIPS code
            WHEN g.LEVEL = 'State' THEN t.GEO_ID END AS STATE_GEO_ID,
       CASE t.VARIABLE
            WHEN 'B25064_001E_1YR' THEN 'all'
            WHEN 'B25031_002E_1YR' THEN '0'
            WHEN 'B25031_003E_1YR' THEN '1'
            WHEN 'B25031_004E_1YR' THEN '2'
            WHEN 'B25031_005E_1YR' THEN '3'
            WHEN 'B25031_006E_1YR' THEN '4'
            WHEN 'B25031_007E_1YR' THEN '5+' END AS BEDROOMS,
       t.DATE,
       t.VALUE AS MEDIAN_RENT_USD
FROM SNOWFLAKE_PUBLIC_DATA_FREE.PUBLIC_DATA_FREE.AMERICAN_COMMUNITY_SURVEY_TIMESERIES t
JOIN SNOWFLAKE_PUBLIC_DATA_FREE.PUBLIC_DATA_FREE.GEOGRAPHY_INDEX g ON g.GEO_ID = t.GEO_ID
WHERE t.VARIABLE IN ('B25064_001E_1YR', 'B25031_002E_1YR', 'B25031_003E_1YR', 'B25031_004E_1YR',
                     'B25031_005E_1YR', 'B25031_006E_1YR', 'B25031_007E_1YR')
  AND g.LEVEL IN ('City', 'State', 'Country')
  AND t.DATE >= '2022-01-01'
  AND t.VALUE IS NOT NULL;

-- Check: expect roughly 646 cities, 52 states, 1 country.
SELECT LEVEL, COUNT(DISTINCT GEO_ID) AS GEOS, MAX(DATE) AS LATEST FROM CROWDSOLUTION.BENCHMARKS.RENT GROUP BY 1;
