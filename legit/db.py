"""Snowflake access. Credentials live in ~/.snowflake/connections.toml, never in the repo."""
import platform
import sys

# Microsoft Store Python blocks reading its own python.exe, which crashes
# platform.libc_ver() inside the Snowflake connector. libc is Linux-only anyway.
if sys.platform == "win32":
    platform.libc_ver = lambda *args, **kwargs: ("", "")

import snowflake.connector  # noqa: E402

from . import config  # noqa: E402

PUBLIC = "SNOWFLAKE_PUBLIC_DATA_FREE.PUBLIC_DATA_FREE"
_conn = None


def connection():
    global _conn
    if _conn is None or _conn.is_closed():
        _conn = snowflake.connector.connect(connection_name=config.SNOWFLAKE_CONNECTION)
    return _conn


def query(sql: str, params=None) -> list[dict]:
    """Run parameterized SQL with %(name)s placeholders and return rows as dicts."""
    cur = connection().cursor(snowflake.connector.DictCursor)
    try:
        return cur.execute(sql, params).fetchall()
    finally:
        cur.close()


def close() -> None:
    global _conn
    if _conn is not None and not _conn.is_closed():
        _conn.close()
    _conn = None
