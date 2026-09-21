"""Dialect adapters — the per-engine differences that actually bite.

Five engines are supported. What differs between them, and therefore what this
module encodes:

    row limiting      TOP (n) in the projection (T-SQL) vs trailing LIMIT n
    base-table test   sys.tables vs a table_type predicate whose values differ
    comments          extended properties vs COMMENT vs obj_description()
    foreign keys      enforced and queryable (SQL Server, Postgres, MySQL) or
                      informational at best (Snowflake, Databricks)
    sampling          TABLESAMPLE syntax, or none

The last one shapes the whole catalog design: on Snowflake and Databricks the
declared FK graph is unreliable or absent, so join discovery must fall back to
name-based inference plus learned co-occurrence. A design that assumes
information_schema.referential_constraints is populated works on three of these
five engines and silently produces no joins on the other two.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── introspection SQL ────────────────────────────────────────────────────────
#
# Each returns the same column shape so the crawler stays engine-agnostic:
#   schema_name, table_name, column_name, ordinal, data_type, is_nullable,
#   table_comment, column_comment

_COLUMNS_POSTGRES = """
SELECT c.table_schema                                      AS schema_name,
       c.table_name                                        AS table_name,
       c.column_name                                       AS column_name,
       c.ordinal_position                                  AS ordinal,
       c.data_type                                         AS data_type,
       CASE WHEN c.is_nullable = 'YES' THEN 1 ELSE 0 END   AS is_nullable,
       obj_description(pc.oid, 'pg_class')                 AS table_comment,
       col_description(pc.oid, c.ordinal_position)         AS column_comment
  FROM information_schema.columns c
  JOIN information_schema.tables  t
    ON t.table_schema = c.table_schema AND t.table_name = c.table_name
  JOIN pg_class      pc ON pc.relname = c.table_name
  JOIN pg_namespace  pn ON pn.oid = pc.relnamespace AND pn.nspname = c.table_schema
 WHERE t.table_type = 'BASE TABLE'
   AND c.table_schema NOT IN ('pg_catalog', 'information_schema')
 ORDER BY c.table_schema, c.table_name, c.ordinal_position
"""

# sys.tables excludes views by construction — no table_type filter needed, and
# no risk of a view slipping through a mis-cased string comparison.
_COLUMNS_TSQL = """
SELECT s.name                                        AS schema_name,
       t.name                                        AS table_name,
       c.name                                        AS column_name,
       c.column_id                                   AS ordinal,
       ty.name                                       AS data_type,
       CAST(c.is_nullable AS INT)                    AS is_nullable,
       CAST(ep_t.value AS NVARCHAR(MAX))             AS table_comment,
       CAST(ep_c.value AS NVARCHAR(MAX))             AS column_comment
  FROM sys.tables   t
  JOIN sys.schemas  s  ON s.schema_id = t.schema_id
  JOIN sys.columns  c  ON c.object_id = t.object_id
  JOIN sys.types    ty ON ty.user_type_id = c.user_type_id
  LEFT JOIN sys.extended_properties ep_t
    ON ep_t.major_id = t.object_id AND ep_t.minor_id = 0
   AND ep_t.name = 'MS_Description'
  LEFT JOIN sys.extended_properties ep_c
    ON ep_c.major_id = t.object_id AND ep_c.minor_id = c.column_id
   AND ep_c.name = 'MS_Description'
 ORDER BY s.name, t.name, c.column_id
"""

_COLUMNS_SNOWFLAKE = """
SELECT c.table_schema                                      AS schema_name,
       c.table_name                                        AS table_name,
       c.column_name                                       AS column_name,
       c.ordinal_position                                  AS ordinal,
       c.data_type                                         AS data_type,
       CASE WHEN c.is_nullable = 'YES' THEN 1 ELSE 0 END   AS is_nullable,
       t.comment                                           AS table_comment,
       c.comment                                           AS column_comment
  FROM information_schema.columns c
  JOIN information_schema.tables  t
    ON t.table_schema = c.table_schema AND t.table_name = c.table_name
 WHERE t.table_type = 'BASE TABLE'
   AND c.table_schema <> 'INFORMATION_SCHEMA'
 ORDER BY c.table_schema, c.table_name, c.ordinal_position
"""

# Unity Catalog reports MANAGED / EXTERNAL / VIEW — so exclude VIEW rather than
# matching 'BASE TABLE', which never appears here.
_COLUMNS_DATABRICKS = """
SELECT c.table_schema                                      AS schema_name,
       c.table_name                                        AS table_name,
       c.column_name                                       AS column_name,
       c.ordinal_position                                  AS ordinal,
       c.full_data_type                                    AS data_type,
       CASE WHEN c.is_nullable = 'YES' THEN 1 ELSE 0 END   AS is_nullable,
       t.comment                                           AS table_comment,
       c.comment                                           AS column_comment
  FROM system.information_schema.columns c
  JOIN system.information_schema.tables  t
    ON t.table_catalog = c.table_catalog
   AND t.table_schema  = c.table_schema
   AND t.table_name    = c.table_name
 WHERE t.table_type <> 'VIEW'
   AND c.table_schema <> 'information_schema'
 ORDER BY c.table_schema, c.table_name, c.ordinal_position
"""

_COLUMNS_MYSQL = """
SELECT c.table_schema                                      AS schema_name,
       c.table_name                                        AS table_name,
       c.column_name                                       AS column_name,
       c.ordinal_position                                  AS ordinal,
       c.data_type                                         AS data_type,
       CASE WHEN c.is_nullable = 'YES' THEN 1 ELSE 0 END   AS is_nullable,
       t.table_comment                                     AS table_comment,
       c.column_comment                                    AS column_comment
  FROM information_schema.columns c
  JOIN information_schema.tables  t
    ON t.table_schema = c.table_schema AND t.table_name = c.table_name
 WHERE t.table_type = 'BASE TABLE'
   AND c.table_schema NOT IN ('mysql', 'sys', 'performance_schema',
                              'information_schema')
 ORDER BY c.table_schema, c.table_name, c.ordinal_position
"""

# DuckDB ships information_schema and follows the ANSI shape. Comments live in
# duckdb_columns(), which is joined in rather than guessed at.
_COLUMNS_DUCKDB = """
SELECT c.table_schema                                      AS schema_name,
       c.table_name                                        AS table_name,
       c.column_name                                       AS column_name,
       c.ordinal_position                                  AS ordinal,
       c.data_type                                         AS data_type,
       CASE WHEN c.is_nullable = 'YES' THEN 1 ELSE 0 END   AS is_nullable,
       NULL                                                AS table_comment,
       dc.comment                                          AS column_comment
  FROM information_schema.columns c
  JOIN information_schema.tables  t
    ON t.table_schema = c.table_schema AND t.table_name = c.table_name
  LEFT JOIN duckdb_columns() dc
    ON dc.schema_name = c.table_schema
   AND dc.table_name  = c.table_name
   AND dc.column_name = c.column_name
 WHERE t.table_type = 'BASE TABLE'
   AND c.table_schema NOT IN ('information_schema', 'pg_catalog')
 ORDER BY c.table_schema, c.table_name, c.ordinal_position
"""

# ── foreign keys ─────────────────────────────────────────────────────────────

_FK_ANSI = """
SELECT kcu.table_schema  AS from_schema, kcu.table_name  AS from_table,
       kcu.column_name   AS from_column,
       ccu.table_schema  AS to_schema,   ccu.table_name  AS to_table,
       ccu.column_name   AS to_column
  FROM information_schema.referential_constraints rc
  JOIN information_schema.key_column_usage kcu
    ON kcu.constraint_name = rc.constraint_name
   AND kcu.constraint_schema = rc.constraint_schema
  JOIN information_schema.constraint_column_usage ccu
    ON ccu.constraint_name = rc.unique_constraint_name
   AND ccu.constraint_schema = rc.unique_constraint_schema
"""

_FK_TSQL = """
SELECT sp.name AS from_schema, tp.name AS from_table, cp.name AS from_column,
       sr.name AS to_schema,   tr.name AS to_table,   cr.name AS to_column
  FROM sys.foreign_keys fk
  JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
  JOIN sys.tables  tp ON tp.object_id = fkc.parent_object_id
  JOIN sys.schemas sp ON sp.schema_id = tp.schema_id
  JOIN sys.columns cp ON cp.object_id = tp.object_id
                     AND cp.column_id = fkc.parent_column_id
  JOIN sys.tables  tr ON tr.object_id = fkc.referenced_object_id
  JOIN sys.schemas sr ON sr.schema_id = tr.schema_id
  JOIN sys.columns cr ON cr.object_id = tr.object_id
                     AND cr.column_id = fkc.referenced_column_id
"""

_FK_MYSQL = """
SELECT table_schema            AS from_schema, table_name  AS from_table,
       column_name             AS from_column,
       referenced_table_schema AS to_schema,
       referenced_table_name   AS to_table,
       referenced_column_name  AS to_column
  FROM information_schema.key_column_usage
 WHERE referenced_table_name IS NOT NULL
"""


# ── views ───────────────────────────────────────────────────────────────────
#
# Views are never queried, but they are crawled: when someone asks for
# `vw_active_headcount` by name, "that is a view, here are the base tables it
# reads" is a far better answer than "no such table".

_VIEWS_TSQL = """
SELECT s.name AS schema_name, v.name AS table_name
  FROM sys.views v
  JOIN sys.schemas s ON s.schema_id = v.schema_id
"""

_VIEWS_ANSI = """
SELECT table_schema AS schema_name, table_name AS table_name
  FROM information_schema.views
"""

_VIEWS_DATABRICKS = """
SELECT table_schema AS schema_name, table_name AS table_name
  FROM system.information_schema.tables
 WHERE table_type = 'VIEW'
"""


@dataclass(frozen=True)
class Dialect:
    """Everything the rest of the system needs to know about an engine."""

    name: str
    sqlglot: str
    quote: str  # identifier quote character(s); '[' means bracket-quoting
    limit_style: str  # "top" | "limit"
    columns_sql: str
    fk_sql: str | None
    supports_declared_fks: bool
    max_identifier_len: int
    # Engines that fold unquoted identifiers to one case. Matters when the
    # crawler writes a catalog the planner later has to match against.
    identifier_case: str  # "upper" | "lower" | "preserve"
    sample_clause: str = ""
    views_sql: str | None = None
    # How the *driver* wants placeholders. Strictly a driver property, not an
    # engine one, but there is one obvious driver per engine and getting it
    # wrong turns every bound literal into a syntax error — so it lives with
    # the other per-engine facts rather than being rediscovered at each call.
    param_style: str = "qmark"  # qmark (?) | pyformat (%s) | numeric (:1)
    # Statements that make the session read-only and time-bounded. Run before
    # the query, best-effort: an engine that rejects one is not a reason to
    # refuse to answer, because permissions are the real boundary anyway.
    session_sql: tuple[str, ...] = ()
    notes: str = ""
    forbidden_tokens: tuple[str, ...] = field(default_factory=tuple)

    def quote_ident(self, ident: str) -> str:
        if self.quote == "[":
            return "[" + ident.replace("]", "]]") + "]"
        q = self.quote
        return q + ident.replace(q, q + q) + q

    def normalise_ident(self, ident: str) -> str:
        """Fold an unquoted identifier the way this engine would."""
        if self.identifier_case == "upper":
            return ident.upper()
        if self.identifier_case == "lower":
            return ident.lower()
        return ident


POSTGRES = Dialect(
    name="postgres",
    sqlglot="postgres",
    quote='"',
    limit_style="limit",
    columns_sql=_COLUMNS_POSTGRES,
    fk_sql=_FK_ANSI,
    supports_declared_fks=True,
    max_identifier_len=63,
    identifier_case="lower",
    sample_clause="TABLESAMPLE SYSTEM ({pct})",
    views_sql=_VIEWS_ANSI,
    param_style="pyformat",
    session_sql=(
        "SET TRANSACTION READ ONLY",
        "SET statement_timeout = {timeout_ms}",
    ),
)

SQLSERVER = Dialect(
    name="sqlserver",
    sqlglot="tsql",
    quote="[",
    limit_style="top",
    columns_sql=_COLUMNS_TSQL,
    fk_sql=_FK_TSQL,
    supports_declared_fks=True,
    max_identifier_len=128,
    identifier_case="preserve",
    sample_clause="TABLESAMPLE ({pct} PERCENT)",
    views_sql=_VIEWS_TSQL,
    forbidden_tokens=("xp_", "sp_", "openrowset", "openquery", "opendatasource"),
    param_style="qmark",
    session_sql=(
        "SET LOCK_TIMEOUT {timeout_ms}",
        "SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED",
    ),
)

SNOWFLAKE = Dialect(
    name="snowflake",
    sqlglot="snowflake",
    quote='"',
    limit_style="limit",
    columns_sql=_COLUMNS_SNOWFLAKE,
    fk_sql=None,
    supports_declared_fks=False,
    max_identifier_len=255,
    identifier_case="upper",
    sample_clause="SAMPLE ({pct})",
    views_sql=_VIEWS_ANSI,
    notes="FKs are declarative only and rarely populated; joins come from "
    "inference plus learned co-occurrence.",
    param_style="pyformat",
    session_sql=("ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = {timeout_s}",),
)

DATABRICKS = Dialect(
    name="databricks",
    sqlglot="databricks",
    quote="`",
    limit_style="limit",
    columns_sql=_COLUMNS_DATABRICKS,
    fk_sql=None,
    supports_declared_fks=False,
    max_identifier_len=255,
    identifier_case="lower",
    sample_clause="TABLESAMPLE ({pct} PERCENT)",
    views_sql=_VIEWS_DATABRICKS,
    notes="Unity Catalog constraints are informational; same inference "
    "fallback as Snowflake. table_type is MANAGED/EXTERNAL/VIEW.",
    param_style="pyformat",
    session_sql=(),
)

MYSQL = Dialect(
    name="mysql",
    sqlglot="mysql",
    quote="`",
    limit_style="limit",
    columns_sql=_COLUMNS_MYSQL,
    fk_sql=_FK_MYSQL,
    supports_declared_fks=True,
    max_identifier_len=64,
    identifier_case="preserve",
    views_sql=_VIEWS_ANSI,
    param_style="pyformat",
    session_sql=(
        "SET SESSION TRANSACTION READ ONLY",
        "SET SESSION max_execution_time = {timeout_ms}",
    ),
)

DUCKDB = Dialect(
    name="duckdb",
    sqlglot="duckdb",
    quote='"',
    limit_style="limit",
    columns_sql=_COLUMNS_DUCKDB,
    fk_sql=_FK_ANSI,
    supports_declared_fks=True,
    max_identifier_len=255,
    # Case-insensitive but case-preserving: a column created `Report ID` keeps
    # that spelling and is reachable however you type it. The odd one out.
    identifier_case="preserve",
    sample_clause="USING SAMPLE {pct}%",
    views_sql=_VIEWS_ANSI,
    notes="Embedded; often the local test target for the other five.",
    param_style="qmark",
    session_sql=(),
)

REGISTRY: dict[str, Dialect] = {
    d.name: d for d in (POSTGRES, SQLSERVER, SNOWFLAKE, DATABRICKS, MYSQL, DUCKDB)
}

# Accept the spellings people actually type in config files.
_ALIASES = {
    "mssql": "sqlserver",
    "sql_server": "sqlserver",
    "tsql": "sqlserver",
    "azuresql": "sqlserver",
    "pg": "postgres",
    "postgresql": "postgres",
    "redshift": "postgres",
    "spark": "databricks",
    "sparksql": "databricks",
    "mariadb": "mysql",
    "duck": "duckdb",
    "duckdb_local": "duckdb",
}


def get(name: str) -> Dialect:
    key = name.strip().lower().replace("-", "_")
    key = _ALIASES.get(key, key)
    if key not in REGISTRY:
        raise KeyError(f"unknown dialect {name!r}; known: {sorted(REGISTRY)}")
    return REGISTRY[key]
