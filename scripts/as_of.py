"""Look up what a statistic said on a given date, using point-in-time history.

Examples:
  # Latest unemployment rate that had been published by 2025-01-15
  python scripts/as_of.py LNS14000000.M_SA --date 2025-01-15

  # Every published version of the June 2024 jobs number (shows revisions)
  python scripts/as_of.py CES0000000001.M_SA --period 2024-06-30

Notes:
  - Point-in-time history starts in 2024 (varies by series). Earlier dates return nothing.
  - Rates are stored as fractions: 0.043 means 4.3%.
  - The free tier lags about one quarter behind the live data.
"""
import argparse

import sf

p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("variable", help="series ID from find_series.py, e.g. LNS14000000.M_SA")
g = p.add_mutually_exclusive_group()
g.add_argument("--date", help="show the latest figure published as of this date (YYYY-MM-DD). Default: now")
g.add_argument("--period", help="show every published version of this period's value (YYYY-MM-DD)")
a = p.parse_args()

T = f"{sf.PUBLIC}.FINANCIAL_ECONOMIC_INDICATORS_TIMESERIES_PIT"

if a.period:
    rows = sf.query(f"""
        SELECT VARIABLE_NAME, TO_VARCHAR(DATE) AS period, VALUE, UNIT,
               TO_VARCHAR(_EFFECTIVE_START_TIMESTAMP, 'YYYY-MM-DD') AS published,
               COALESCE(TO_VARCHAR(_EFFECTIVE_END_TIMESTAMP, 'YYYY-MM-DD'), 'current') AS replaced
        FROM {T}
        WHERE VARIABLE = %(v)s AND DATE = %(period)s
        -- keep only real revisions; drop versions where only the series name changed
        QUALIFY VALUE IS DISTINCT FROM LAG(VALUE) OVER (ORDER BY _EFFECTIVE_START_TIMESTAMP)
        ORDER BY _EFFECTIVE_START_TIMESTAMP""", {"v": a.variable, "period": a.period})
else:
    rows = sf.query(f"""
        SELECT VARIABLE_NAME, TO_VARCHAR(DATE) AS latest_period, VALUE, UNIT,
               TO_VARCHAR(_EFFECTIVE_START_TIMESTAMP, 'YYYY-MM-DD') AS published
        FROM {T}
        WHERE VARIABLE = %(v)s
          AND _EFFECTIVE_START_TIMESTAMP <= COALESCE(%(d)s::TIMESTAMP_TZ, CURRENT_TIMESTAMP())
          AND (_EFFECTIVE_END_TIMESTAMP IS NULL
               OR _EFFECTIVE_END_TIMESTAMP > COALESCE(%(d)s::TIMESTAMP_TZ, CURRENT_TIMESTAMP()))
        ORDER BY DATE DESC
        LIMIT 1""", {"v": a.variable, "d": a.date})
sf.print_rows(rows)
