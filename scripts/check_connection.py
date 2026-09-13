"""Smoke test for the Snowflake connection. Never prints the token.

Usage:  python scripts/check_connection.py
"""
import sys

import sf

CHECKS = [
    ("identity", "SELECT CURRENT_ACCOUNT_NAME() AS account, CURRENT_USER() AS user_name, "
                 "CURRENT_ROLE() AS role, CURRENT_WAREHOUSE() AS warehouse"),
    ("public data", "SELECT COUNT(*) AS tables FROM SNOWFLAKE_PUBLIC_DATA_FREE.INFORMATION_SCHEMA.TABLES "
                    "WHERE TABLE_SCHEMA = 'PUBLIC_DATA_FREE'"),
    ("point-in-time lookup", f"SELECT VALUE FROM {sf.PUBLIC}.FINANCIAL_ECONOMIC_INDICATORS_TIMESERIES "
                             "WHERE VARIABLE = 'LNS14000000.M_SA' ORDER BY DATE DESC LIMIT 1"),
]

try:
    conn = sf.connect()
except Exception as e:  # noqa: BLE001
    print("CONNECT FAILED:", type(e).__name__, str(e)[:300])
    print("See docs/DATA_ACCESS.md, section Troubleshooting.")
    sys.exit(1)

ok = True
for name, sql in CHECKS:
    try:
        print(f"[pass] {name}: {sf.query(sql, conn=conn)[0]}")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"[FAIL] {name}: {str(e).splitlines()[0][:300]}")

# Cortex AI is blocked on trial accounts; report it without failing the check.
try:
    sf.query("SELECT AI_COMPLETE('llama3.1-8b', 'Reply with exactly: ok') AS r", conn=conn)
    print("[pass] cortex ai: available")
except Exception as e:  # noqa: BLE001
    print(f"[info] cortex ai: unavailable ({str(e).splitlines()[0][:120]})")

conn.close()
sys.exit(0 if ok else 1)
