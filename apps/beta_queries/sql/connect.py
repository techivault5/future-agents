"""Open a connection for a dialect — one place, used by the crawl and the app.

Drivers are imported lazily, inside the branch that needs them, so a machine
with only DuckDB installed can crawl and answer against DuckDB without a SQL
Server or Snowflake driver present. The DSN is read from the environment by
the caller and passed in; nothing here logs or stores it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

SUPPORTED = ("sqlserver", "postgres", "snowflake", "databricks", "mysql", "duckdb")

# What to install when a driver is missing. Only SQL Server has an extra of its
# own; naming a `.[snowflake]` extra that does not exist sends people chasing
# an install that cannot succeed.
INSTALL = {
    "sqlserver": 'pip install -e ".[beta_queries_sqlserver]" plus ODBC Driver 18 for SQL Server',
    "postgres": 'pip install "psycopg[binary]"',
    "snowflake": "pip install snowflake-connector-python",
    "databricks": "pip install databricks-sql-connector",
    "mysql": "pip install mysql-connector-python",
    "duckdb": "pip install duckdb",
}
_CANONICAL = {"mssql": "sqlserver", "postgresql": "postgres", "mariadb": "mysql"}


class DriverMissing(RuntimeError):
    """The dialect is known but its driver is not installed on this machine."""


def connect(dialect: str, dsn: str) -> Any:
    """A PEP-249 connection. Read-only where the driver lets us say so."""
    d = dialect.strip().lower()
    try:
        if d in ("sqlserver", "mssql"):
            import pyodbc

            return pyodbc.connect(dsn, readonly=True)
        if d in ("postgres", "postgresql"):
            import psycopg

            return psycopg.connect(dsn)
        if d == "snowflake":
            import snowflake.connector as sf

            return sf.connect(**json.loads(dsn))
        if d == "databricks":
            from databricks import sql as dbsql

            return dbsql.connect(**json.loads(dsn))
        if d in ("mysql", "mariadb"):
            import mysql.connector as mc

            return mc.connect(**json.loads(dsn))
        if d == "duckdb":
            import duckdb

            # A DSN for DuckDB is just a file path.
            return duckdb.connect(dsn, read_only=True)
    except ImportError as exc:
        how = INSTALL.get(_CANONICAL.get(d, d), f"install the {exc.name} package")
        raise DriverMissing(f"the {dialect} driver is not installed — {how}") from exc
    raise ValueError(f"no driver mapping for dialect {dialect!r}; supported: {SUPPORTED}")


def connector(dialect: str, dsn: str) -> Callable[[], Any]:
    """A zero-argument factory, which is what the executor takes."""
    return lambda: connect(dialect, dsn)


def probe(dialect: str, dsn: str) -> str:
    """Open a connection and run SELECT 1. Returns "" when it works, else why not.

    One call answers four questions a person otherwise discovers one failed
    question at a time: is the driver installed, is the DSN well-formed, is
    the network (VPN) up, and do the credentials work.
    """
    try:
        con = connect(dialect, dsn)
    except DriverMissing as exc:
        return str(exc)
    except Exception as exc:  # noqa: BLE001 — every failure is the answer here
        return f"cannot connect: {type(exc).__name__}: {str(exc).splitlines()[0][:160]}"
    try:
        cur = con.cursor()
        cur.execute("SELECT 1")
        cur.fetchall()
        return ""
    except Exception as exc:  # noqa: BLE001
        return f"connected, but SELECT 1 failed: {str(exc).splitlines()[0][:160]}"
    finally:
        try:
            con.close()
        except Exception:  # noqa: BLE001 — closing a broken connection is best effort
            pass
