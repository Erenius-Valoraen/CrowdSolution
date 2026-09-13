"""Search the ~170k official statistics series by keywords.

Examples:
  python scripts/find_series.py unemployment rate --frequency Monthly
  python scripts/find_series.py nonfarm "all employees" --source "Bureau of Labor Statistics"
  python scripts/find_series.py "gross domestic product" --frequency Quarterly --limit 10
"""
import argparse

import sf

p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("keywords", nargs="+", help="every keyword must appear in the series name")
p.add_argument("--frequency", help="Monthly, Quarterly, Annual, Weekly, Daily")
p.add_argument("--source", help="e.g. 'Bureau of Labor Statistics', 'Federal Reserve'")
p.add_argument("--limit", type=int, default=25)
a = p.parse_args()

where, params = [], {}
for i, kw in enumerate(a.keywords):
    where.append(f"VARIABLE_NAME ILIKE %(kw{i})s")
    params[f"kw{i}"] = f"%{kw}%"
if a.frequency:
    where.append("FREQUENCY = %(freq)s")
    params["freq"] = a.frequency
if a.source:
    where.append("RELEASE_SOURCE = %(src)s")
    params["src"] = a.source
params["lim"] = a.limit

rows = sf.query(f"""
    SELECT VARIABLE, VARIABLE_NAME, FREQUENCY, UNIT, RELEASE_SOURCE
    FROM {sf.PUBLIC}.FINANCIAL_ECONOMIC_INDICATORS_ATTRIBUTES
    WHERE {' AND '.join(where)}
    ORDER BY LENGTH(VARIABLE_NAME)
    LIMIT %(lim)s""", params)
sf.print_rows(rows)
