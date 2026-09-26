"""Connection helpers for the catalog-sync DAG.

Every driver is imported lazily and only for the dialect actually being
crawled, so a worker that only ever touches Snowflake does not need pyodbc
installed. Credentials come from the environment; nothing here logs, returns
or stores one.
"""

from __future__ import annotations

import json
import os
from typing import Any

# Crawl as a read-only catalog principal. It reads metadata and samples values;
# it must never be the principal that answers user questions — those run as the
# asker, so row-level security applies.
READONLY_HINT = "use a read-only catalog principal, never the application account"


def open_connection(dialect: str, dsn: str) -> Any:
    """A PEP-249 connection for any supported engine."""
    key = (dialect or "").strip().lower()

    if key in ("sqlserver", "mssql", "azuresql", "tsql"):
        import pyodbc

        return pyodbc.connect(dsn, readonly=True)
    if key in ("postgres", "postgresql", "pg", "redshift"):
        import psycopg

        return psycopg.connect(dsn)
    if key == "snowflake":
        import snowflake.connector as sf

        return sf.connect(**json.loads(dsn))
    if key in ("databricks", "spark"):
        from databricks import sql as dbsql

        return dbsql.connect(**json.loads(dsn))
    if key in ("mysql", "mariadb"):
        import mysql.connector as mc

        return mc.connect(**json.loads(dsn))
    if key == "duckdb":
        import duckdb

        return duckdb.connect(dsn)
    raise ValueError(f"no driver mapping for dialect {dialect!r}")


def neo4j_runner() -> Any:
    """A `run(cypher, params) -> rows` callable over a Neo4j session."""
    from neo4j import GraphDatabase

    uri = os.environ["BQ_NEO4J_URI"]
    auth = (os.environ["BQ_NEO4J_USER"], os.environ["BQ_NEO4J_PASSWORD"])
    driver = GraphDatabase.driver(uri, auth=auth)

    def run(cypher: str, params: dict[str, Any]) -> list[Any]:
        with driver.session() as session:
            return [record.data() for record in session.run(cypher, **params)]

    return run


def redis_client() -> Any:
    import redis

    return redis.from_url(os.environ["BQ_REDIS_URL"], decode_responses=True)
