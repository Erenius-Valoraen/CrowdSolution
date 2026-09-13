"""Snowflake access.

Locally, credentials live in ~/.snowflake/connections.toml. On a server such as Vercel, set SNOWFLAKE_ACCOUNT,
SNOWFLAKE_USER, and SNOWFLAKE_TOKEN (a programmatic access token) as environment variables. Never commit either."""
import os
import platform
import sys

# Microsoft Store Python blocks reading its own python.exe, which crashes
# platform.libc_ver() inside the Snowflake connector. libc is Linux-only anyway.
if sys.platform == "win32":
    platform.libc_ver = lambda *args, **kwargs: ("", "")

if os.environ.get("VERCEL"):
    # Only /tmp is writable on Vercel; the connector keeps its config lookups and caches under these directories.
    os.environ.setdefault("SNOWFLAKE_HOME", "/tmp/snowflake")
    os.environ.setdefault("SF_OCSP_RESPONSE_CACHE_DIR", "/tmp/snowflake")
    os.environ.setdefault("SF_TEMPORARY_CREDENTIAL_CACHE_DIR", "/tmp/snowflake")

import snowflake.connector  # noqa: E402

from . import config  # noqa: E402

PUBLIC = "SNOWFLAKE_PUBLIC_DATA_FREE.PUBLIC_DATA_FREE"
_conn = None


def connect_params() -> dict:
    """Environment variables when they're set (servers), otherwise the named local connection."""
    if config.SNOWFLAKE_ACCOUNT and config.SNOWFLAKE_USER and config.SNOWFLAKE_TOKEN:
        params = {
            "account": config.SNOWFLAKE_ACCOUNT,
            "user": config.SNOWFLAKE_USER,
            "authenticator": "PROGRAMMATIC_ACCESS_TOKEN",
            "token": config.SNOWFLAKE_TOKEN,
            "role": config.SNOWFLAKE_ROLE,
            "warehouse": config.SNOWFLAKE_WAREHOUSE,
            "database": config.SNOWFLAKE_DATABASE,
            "schema": config.SNOWFLAKE_SCHEMA,
        }
        return {k: v for k, v in params.items() if v}
    return {"connection_name": config.SNOWFLAKE_CONNECTION}


def connection():
    global _conn
    if _conn is None or _conn.is_closed():
        _conn = snowflake.connector.connect(**connect_params())
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
