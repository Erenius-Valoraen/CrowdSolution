-- College benchmark tables for the legit checker, built from the College Scorecard Marketplace listing.
-- Prerequisite: get the "College Scorecard" listing (Vantage Point) from Snowflake Marketplace as database COLLEGE_SCORECARD.
-- The source stores every value as text (with "PS" for privacy-suppressed), so these tables cast to numbers once.
-- Run as SYSADMIN. Takes under a minute.

USE ROLE SYSADMIN;
CREATE SCHEMA IF NOT EXISTS CROWDSOLUTION.BENCHMARKS;

-- One row per currently operating school.
-- SEARCH_NAMES looks like |the university of texas at austin|ut austin| so exact name and alias matches are easy.
CREATE OR REPLACE TABLE CROWDSOLUTION.BENCHMARKS.COLLEGES AS
SELECT
    TRY_TO_NUMBER(UNITID)                                   AS UNITID,
    INSTNM                                                  AS NAME,
    ALIAS,
    CITY,
    STABBR                                                  AS STATE,
    INSTURL                                                 AS URL,
    CASE CONTROL WHEN '1' THEN 'public' WHEN '2' THEN 'private nonprofit' WHEN '3' THEN 'private for-profit' END AS CONTROL,
    TRY_TO_NUMBER(UGDS)                                     AS UNDERGRADS,
    TRY_TO_DOUBLE(ADM_RATE)                                 AS ADMISSION_RATE,
    TRY_TO_NUMBER(SAT_AVG)                                  AS SAT_AVG,
    TRY_TO_NUMBER(TUITIONFEE_IN)                            AS TUITION_IN_STATE,
    TRY_TO_NUMBER(TUITIONFEE_OUT)                           AS TUITION_OUT_OF_STATE,
    TRY_TO_NUMBER(COSTT4_A)                                 AS COST_OF_ATTENDANCE,
    COALESCE(TRY_TO_NUMBER(NPT4_PUB), TRY_TO_NUMBER(NPT4_PRIV)) AS NET_PRICE,
    TRY_TO_DOUBLE(C150_4)                                   AS GRADUATION_RATE,
    TRY_TO_DOUBLE(RET_FT4)                                  AS RETENTION_RATE,
    TRY_TO_NUMBER(MD_EARN_WNE_P6)                           AS EARNINGS_6YR,
    TRY_TO_NUMBER(MD_EARN_WNE_P10)                          AS EARNINGS_10YR,
    TRY_TO_NUMBER(GRAD_DEBT_MDN)                            AS MEDIAN_DEBT,
    TRY_TO_DOUBLE(PCTPELL)                                  AS PELL_SHARE,
    '|' || TRIM(REGEXP_REPLACE(REGEXP_REPLACE(LOWER(INSTNM || '|' || REPLACE(COALESCE(ALIAS, ''), ',', '|')),
                                              '[^a-z0-9|]+', ' '), ' *[|] *', '|'), '| ') || '|' AS SEARCH_NAMES
FROM COLLEGE_SCORECARD.COLLEGE_SCORECARD.MOST_RECENT_COHORTS_INSTITUTION
WHERE CURROPER = '1';

-- One row per school, program (4-digit CIP code), and credential level, where earnings or debt are reported.
CREATE OR REPLACE TABLE CROWDSOLUTION.BENCHMARKS.COLLEGE_PROGRAMS AS
SELECT
    TRY_TO_NUMBER(UNITID)                  AS UNITID,
    INSTNM                                 AS NAME,
    CIPCODE,
    RTRIM(CIPDESC, '.')                    AS PROGRAM,
    TRY_TO_NUMBER(CREDLEV)                 AS CREDLEV,
    CREDDESC                               AS CREDENTIAL,
    TRY_TO_NUMBER(IPEDSCOUNT2)             AS GRADUATES,
    TRY_TO_NUMBER(EARN_MDN_1YR)            AS EARNINGS_1YR,
    TRY_TO_NUMBER(EARN_MDN_4YR)            AS EARNINGS_4YR,
    TRY_TO_NUMBER(EARN_MDN_5YR)            AS EARNINGS_5YR,
    TRY_TO_NUMBER(DEBT_ALL_STGP_EVAL_MDN)  AS MEDIAN_DEBT
FROM COLLEGE_SCORECARD.COLLEGE_SCORECARD.MOST_RECENT_COHORTS_FIELD_OF_STUDY
WHERE COALESCE(TRY_TO_NUMBER(EARN_MDN_1YR), TRY_TO_NUMBER(EARN_MDN_4YR), TRY_TO_NUMBER(EARN_MDN_5YR),
               TRY_TO_NUMBER(DEBT_ALL_STGP_EVAL_MDN)) IS NOT NULL;

-- National picture for a major: the median across schools that report it. Used for "CS majors earn $X" claims.
CREATE OR REPLACE TABLE CROWDSOLUTION.BENCHMARKS.PROGRAM_NATIONAL AS
SELECT
    CIPCODE,
    ANY_VALUE(PROGRAM)       AS PROGRAM,
    CREDLEV,
    ANY_VALUE(CREDENTIAL)    AS CREDENTIAL,
    COUNT(*)                 AS SCHOOLS,
    MEDIAN(EARNINGS_1YR)     AS EARNINGS_1YR,
    MEDIAN(EARNINGS_4YR)     AS EARNINGS_4YR,
    MEDIAN(EARNINGS_5YR)     AS EARNINGS_5YR,
    MEDIAN(MEDIAN_DEBT)      AS MEDIAN_DEBT
FROM CROWDSOLUTION.BENCHMARKS.COLLEGE_PROGRAMS
GROUP BY CIPCODE, CREDLEV;

-- Check: expect about 6,400 schools, tens of thousands of programs.
SELECT 'COLLEGES' AS T, COUNT(*) AS N FROM CROWDSOLUTION.BENCHMARKS.COLLEGES
UNION ALL SELECT 'COLLEGE_PROGRAMS', COUNT(*) FROM CROWDSOLUTION.BENCHMARKS.COLLEGE_PROGRAMS
UNION ALL SELECT 'PROGRAM_NATIONAL', COUNT(*) FROM CROWDSOLUTION.BENCHMARKS.PROGRAM_NATIONAL;
