"""Catalog crawler — harvest structure, then harvest meaning.

Two passes, because they have different costs and different failure modes.

**Structure** is one query per datasource: every base table, every column, every
comment. Cheap, deterministic, safe to run on a schedule.

**Meaning** is the expensive pass: sampling the values of low-cardinality
columns so that "India" can be resolved to `country_code = 'IN'` without a model
guessing at it. This is what makes routing feel effortless, and it is also the
pass that can read personal data — so name-detected PII columns are profiled for
cardinality only and never for values.

The crawler never opens a connection itself. It takes a `run(sql) -> rows`
callable, which keeps this module free of driver imports, makes every path
testable with a dict of fake result sets, and means the caller decides which
principal the crawl runs as (a read-only catalog account, not the app's).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from beta_queries import dialects
from beta_queries.catalog.models import Column, Datasource, JoinEdge, Table
from beta_queries.catalog.semantics import detect_default_filters
from beta_queries.routing.router import SourceProfile, tokenise

Runner = Callable[[str], Sequence[Sequence[Any]]]

# Columns whose values must never enter the value index, however low their
# cardinality. Cardinality alone is not a safety test: a 400-row `email` column
# is low-cardinality and is still personal data.
_PII_PATTERNS = (
    r"email",
    r"e_mail",
    r"phone",
    r"mobile",
    r"ssn",
    r"social_security",
    r"national_id",
    r"passport",
    r"tax_id",
    r"nino",
    r"aadhaar",
    r"pan_no",
    r"dob",
    r"date_of_birth",
    r"birth_date",
    r"address",
    r"postcode",
    r"zip_?code",
    r"salary",
    r"compensation",
    r"bank_?acc",
    r"iban",
    r"card_no",
    r"credit_card",
    r"first_?name",
    r"last_?name",
    r"full_?name",
    r"surname",
)
_PII_RE = re.compile("|".join(_PII_PATTERNS))

# Columns worth sampling: short codes and labels people say out loud.
_VALUE_LOGICALS = ("string",)

_SINGULARISE = (
    (re.compile(r"ies$"), "y"),
    (re.compile(r"ses$"), "s"),
    (re.compile(r"s$"), ""),
)


def is_pii(column_name: str) -> bool:
    return bool(_PII_RE.search(column_name.lower()))


def _singular(name: str) -> str:
    n = name.lower()
    for pattern, repl in _SINGULARISE:
        if pattern.search(n):
            return pattern.sub(repl, n)
    return n


def _strip_prefix(name: str) -> str:
    """dim_employee / fact_sales / tbl_orders -> employee / sales / orders."""
    return re.sub(r"^(dim|fact|fct|stg|raw|tbl|t|v|src|ref|lkp|bridge)_", "", name.lower())


# ── pass 1: structure ────────────────────────────────────────────────────────


def crawl_structure(
    datasource_id: str,
    dialect_name: str,
    run: Runner,
    description: str = "",
) -> Datasource:
    """Every base table and column, plus the names of the views we skipped."""
    d = dialects.get(dialect_name)
    ds = Datasource(id=datasource_id, dialect=d.name, description=description)

    by_relname: dict[str, Table] = {}
    for row in run(d.columns_sql):
        schema, table, col, ordinal, dtype, nullable, tcomment, ccomment = row[:8]
        key = f"{schema}.{table}"
        t = by_relname.get(key)
        if t is None:
            t = Table(
                datasource_id=datasource_id,
                schema=str(schema),
                name=str(table),
                comment=str(tcomment) if tcomment else None,
            )
            by_relname[key] = t
            ds.tables.append(t)
        t.columns.append(
            Column(
                name=str(col),
                ordinal=int(ordinal or 0),
                data_type=str(dtype or ""),
                nullable=bool(nullable),
                comment=str(ccomment) if ccomment else None,
                is_pii=is_pii(str(col)),
            )
        )

    # Views are recorded with no columns: enough to answer "that name is a
    # view", not enough for anything to accidentally plan against one.
    if d.views_sql:
        for row in run(d.views_sql):
            schema, name = row[0], row[1]
            key = f"{schema}.{name}"
            if key in by_relname:
                continue
            view = Table(
                datasource_id=datasource_id,
                schema=str(schema),
                name=str(name),
                is_view=True,
            )
            by_relname[key] = view
            ds.tables.append(view)

    return ds


# ── pass 2: joins ────────────────────────────────────────────────────────────


def declared_joins(ds: Datasource, run: Runner) -> list[JoinEdge]:
    d = dialects.get(ds.dialect)
    if not d.supports_declared_fks or not d.fk_sql:
        return []
    edges: list[JoinEdge] = []
    for row in run(d.fk_sql):
        fs, ft, fc, ts, tt, tc = row[:6]
        left, right = ds.table(f"{fs}.{ft}"), ds.table(f"{ts}.{tt}")
        if left is None or right is None or left.is_view or right.is_view:
            continue
        edges.append(
            JoinEdge(
                left_table=left.fqn,
                left_column=str(fc),
                right_table=right.fqn,
                right_column=str(tc),
                source="declared",
                confidence=1.0,
            )
        )
    return edges


def infer_joins(ds: Datasource, min_confidence: float = 0.6) -> list[JoinEdge]:
    """Name-based join discovery, for the engines that do not enforce FKs.

    `employee.department_id` -> `department.id` / `department.department_id`.
    Two rules, both conservative: the referenced side must look like a key, and
    a column matching more than one table is dropped rather than guessed at.
    """
    base = ds.base_tables
    # candidate key columns, keyed by the entity name they imply
    keys: dict[str, list[tuple[Table, Column]]] = {}
    for t in base:
        entity = _singular(_strip_prefix(t.name))
        for c in t.columns:
            cname = c.name.lower()
            if cname in ("id", f"{entity}_id", f"{entity}_key", f"{entity}_sk"):
                keys.setdefault(entity, []).append((t, c))

    edges: list[JoinEdge] = []
    for t in base:
        t_entity = _singular(_strip_prefix(t.name))
        for c in t.columns:
            cname = c.name.lower()
            m = re.match(r"^(.*?)_(id|key|sk|code)$", cname)
            if not m:
                continue
            entity = _singular(m.group(1))
            if entity == t_entity or entity not in keys:
                continue
            targets = keys[entity]
            if len(targets) != 1:  # ambiguous — a wrong join is worse than none
                continue
            target_table, target_col = targets[0]
            if target_table.fqn == t.fqn:
                continue
            confidence = 0.75 if cname.endswith(("_id", "_key", "_sk")) else 0.6
            if confidence < min_confidence:
                continue
            edges.append(
                JoinEdge(
                    left_table=t.fqn,
                    left_column=c.name,
                    right_table=target_table.fqn,
                    right_column=target_col.name,
                    source="inferred",
                    confidence=confidence,
                )
            )
    return edges


def merge_joins(*groups: Sequence[JoinEdge]) -> list[JoinEdge]:
    """Declared beats inferred beats learned on the same pair of columns."""
    rank = {"declared": 3, "learned": 2, "inferred": 1}
    best: dict[tuple[str, str, str, str], JoinEdge] = {}
    for group in groups:
        for edge in group:
            key = edge.key()
            current = best.get(key)
            if current is None or rank.get(edge.source, 0) > rank.get(current.source, 0):
                best[key] = edge
    return list(best.values())


# ── pass 3: values ───────────────────────────────────────────────────────────


@dataclass
class ProfileOptions:
    max_distinct: int = 200
    max_value_len: int = 64
    sample_limit: int = 25
    # Skip columns that cannot plausibly be said out loud in a question.
    include_logicals: tuple[str, ...] = _VALUE_LOGICALS


def value_count_sql(table: Table, column: Column, dialect_name: str, limit: int) -> str:
    """`SELECT <col>, COUNT(*) ... GROUP BY <col>` in this engine's spelling.

    Every identifier here comes from the engine's own catalog, never from user
    input, and is quoted with the dialect's quoting rules regardless.
    """
    d = dialects.get(dialect_name)
    col = d.quote_ident(column.name)
    rel = f"{d.quote_ident(table.schema)}.{d.quote_ident(table.name)}"
    top = f"TOP ({limit}) " if d.limit_style == "top" else ""
    tail = "" if d.limit_style == "top" else f"\n LIMIT {limit}"
    return (
        f"SELECT {top}{col} AS value, COUNT(*) AS freq\n"
        f"  FROM {rel}\n"
        f" WHERE {col} IS NOT NULL\n"
        f" GROUP BY {col}\n"
        f" ORDER BY COUNT(*) DESC{tail}"
    )


def profile_values(
    ds: Datasource,
    run: Runner,
    options: ProfileOptions | None = None,
    on_error: Callable[[Table, Column, Exception], None] | None = None,
) -> None:
    """Fill `sample_values` and `distinct_count` in place.

    A column that returns more than `max_distinct` groups is a free-text or
    high-cardinality column: its cardinality is recorded and its values are
    discarded, because indexing them would bloat the catalog and match
    everything. Per-column failures are collected, not raised — one permission
    error on one table must not abandon a whole crawl.
    """
    opts = options or ProfileOptions()
    for table in ds.base_tables:
        for column in table.columns:
            if column.logical not in opts.include_logicals:
                continue
            try:
                sql = value_count_sql(table, column, ds.dialect, opts.max_distinct + 1)
                rows = list(run(sql))
            except Exception as exc:  # noqa: BLE001 — one bad column is not a bad crawl
                if on_error:
                    on_error(table, column, exc)
                continue

            if len(rows) > opts.max_distinct:
                column.distinct_count = None  # "more than we index"
                column.sample_values = []
                continue

            column.distinct_count = len(rows)
            if column.is_pii:
                column.sample_values = []
                continue
            values = [str(r[0]).strip() for r in rows if r and r[0] is not None]
            column.sample_values = [
                v for v in values[: opts.sample_limit] if v and len(v) <= opts.max_value_len
            ]


# ── assembly ─────────────────────────────────────────────────────────────────


def attach_default_filters(ds: Datasource) -> None:
    for table in ds.base_tables:
        table.default_filters = detect_default_filters(table, dialect=ds.dialect)


def build_source_profile(
    ds: Datasource,
    synonyms: dict[str, str] | None = None,
    subject_areas: Sequence[str] | None = None,
    success_count: int = 0,
) -> SourceProfile:
    """Collapse a crawled datasource into the summary the router scores."""
    profile = SourceProfile(
        datasource_id=ds.id,
        dialect=ds.dialect,
        description=ds.description,
        subject_areas=list(subject_areas or []),
        synonyms=dict(synonyms or {}),
        success_count=success_count,
    )
    for table in ds.base_tables:
        for term in tokenise(_strip_prefix(table.name).replace("_", " ")):
            profile.table_terms.add(term)
            profile.table_terms.add(_singular(term))
        for column in table.columns:
            for term in tokenise(column.name.replace("_", " ")):
                profile.column_terms.add(term)
            if column.logical in ("integer", "decimal"):
                profile.metric_names.add(column.name.lower())
            for value in column.sample_values:
                key = value.lower()
                # First writer wins: a value that appears in two columns is
                # routed by the first table crawled, which is stable across
                # runs because the catalog query is ordered.
                profile.value_index.setdefault(key, f"{table.relname}.{column.name}")
    return profile


@dataclass
class CrawlResult:
    datasource: Datasource
    profile: SourceProfile
    errors: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        ds = self.datasource
        views = sum(1 for t in ds.tables if t.is_view)
        filters = sum(len(t.default_filters) for t in ds.base_tables)
        return (
            f"{ds.id}: {len(ds.base_tables)} base tables, {views} views skipped, "
            f"{len(ds.joins)} joins, {filters} default filters, "
            f"{len(self.profile.value_index)} indexed values"
        )


def crawl(
    datasource_id: str,
    dialect_name: str,
    run: Runner,
    description: str = "",
    profile: bool = True,
    options: ProfileOptions | None = None,
    synonyms: dict[str, str] | None = None,
    subject_areas: Sequence[str] | None = None,
    learned_joins: Sequence[JoinEdge] = (),
) -> CrawlResult:
    """Full crawl: structure, joins, values, default filters, router profile."""
    errors: list[str] = []
    ds = crawl_structure(datasource_id, dialect_name, run, description=description)

    try:
        declared = declared_joins(ds, run)
    except Exception as exc:  # noqa: BLE001 — FK introspection is often denied
        errors.append(f"foreign keys unavailable: {exc}")
        declared = []
    ds.joins = merge_joins(declared, infer_joins(ds), list(learned_joins))

    if profile:
        profile_values(
            ds,
            run,
            options,
            on_error=lambda t, c, e: errors.append(f"{t.relname}.{c.name}: {e}"),
        )

    attach_default_filters(ds)
    return CrawlResult(
        datasource=ds,
        profile=build_source_profile(ds, synonyms=synonyms, subject_areas=subject_areas),
        errors=errors,
    )


# ── driver adapter ───────────────────────────────────────────────────────────


def dbapi_runner(connection: Any) -> Runner:
    """Wrap any PEP-249 connection (pyodbc, psycopg, snowflake, mysql) as a Runner.

    Kept here rather than in the caller so that the "read-only cursor, fetchall,
    close" shape is identical for all five engines.
    """

    def run(sql: str) -> list[tuple]:
        cursor = connection.cursor()
        try:
            cursor.execute(sql)
            return list(cursor.fetchall())
        finally:
            cursor.close()

    return run
