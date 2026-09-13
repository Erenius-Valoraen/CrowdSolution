-- Every published version of one period's value. Shows how numbers get revised.
-- Example: June 2024 jobs went from 158,609,000 (Aug 2024) to 157,695,000 (Feb 2026).
SET series_id = 'CES0000000001.M_SA';
SET period    = '2024-06-30';

SELECT DATE AS period, VALUE,
       _EFFECTIVE_START_TIMESTAMP AS published,
       _EFFECTIVE_END_TIMESTAMP   AS replaced
FROM SNOWFLAKE_PUBLIC_DATA_FREE.PUBLIC_DATA_FREE.FINANCIAL_ECONOMIC_INDICATORS_TIMESERIES_PIT
WHERE VARIABLE = $series_id
  AND DATE = $period
-- keep only real revisions; drop versions where only the series name changed
QUALIFY VALUE IS DISTINCT FROM LAG(VALUE) OVER (ORDER BY _EFFECTIVE_START_TIMESTAMP)
ORDER BY _EFFECTIVE_START_TIMESTAMP;
