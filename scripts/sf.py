"""Shared Snowflake helper for CrowdSolution scripts.

Reads credentials from ~/.snowflake/connections.toml (section [crowdsolution] by
default; override with the CROWDSOLUTION_SF_CONNECTION environment variable).
Never put tokens in this repo.
"""
import os
import platform
import sys

# Microsoft Store Python blocks reading its own python.exe, which crashes
# platform.libc_ver() inside the Snowflake connector. libc is Linux-only anyway.
if sys.platform == "win32":
    platform.libc_ver = lambda *args, **kwargs: ("", "")

import snowflake.connector  # noqa: E402  (must come after the patch above)

CONNECTION_NAME = os.environ.get("CROWDSOLUTION_SF_CONNECTION", "crowdsolution")
PUBLIC = "SNOWFLAKE_PUBLIC_DATA_FREE.PUBLIC_DATA_FREE"


def connect():
    """Open a connection using the named connection in connections.toml."""
    return snowflake.connector.connect(connection_name=CONNECTION_NAME)


def query(sql, params=None, conn=None):
    """Run SQL and return a list of dicts. Use %(name)s or %s placeholders for params."""
    own = conn is None
    conn = conn or connect()
    try:
        cur = conn.cursor(snowflake.connector.DictCursor)
        return cur.execute(sql, params).fetchall()
    finally:
        if own:
            conn.close()


def print_rows(rows, max_width=90):
    """Print query results as a simple table."""
    if not rows:
        print("(no rows)")
        return
    cols = list(rows[0].keys())
    print(" | ".join(cols))
    for r in rows:
        print(" | ".join(str(r[c])[:max_width] for c in cols))
