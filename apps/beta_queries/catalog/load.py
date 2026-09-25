"""The read side of the catalog: load what the crawl wrote, into memory.

The crawl writes to three places — Neo4j, Redis, and `.bq-catalog/*.json` —
and until this module nothing read any of them back. `Neo4jGraph` could write
tables and edges but had none of the methods the orchestrator calls, and the
routing profile the DAG publishes to Redis had no reader at all.

The request path therefore runs entirely in memory: load once at startup, then
answer every question without a network hop to the catalog. An in-memory graph
cannot time out over a VPN, and it is the path every test already exercises.

Two sources, one result:

- `load_catalog(directory)` — the JSON the crawl script writes. This is the
  only store that carries **sample values**, which are the single largest
  measured lever on accuracy; Neo4j never stored them.
- `load_graph_from_neo4j(run)` — the graph as Neo4j holds it, for curated
  metrics and learned joins that only exist there. Loaded into memory too.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from beta_queries.catalog.graph import Edge, InMemoryGraph, TableNode
from beta_queries.catalog.models import Column, Datasource, DefaultFilter, JoinEdge, Table
from beta_queries.routing.router import SourceProfile
from beta_queries.sync.plan import edges_from_crawl, tables_from_crawl

# Values shown to the model per column. Research on BIRD found distinct values
# beat raw samples; four is enough to show the shape of a column's content
# without spending the prompt on it.
VALUES_PER_COLUMN = 4


class CatalogNotLoaded(RuntimeError):
    """Nothing to load — the crawl has not run, or ran somewhere else."""


@dataclass
class LoadedCatalog:
    graph: InMemoryGraph
    datasources: dict[str, Datasource] = field(default_factory=dict)
    profiles: dict[str, SourceProfile] = field(default_factory=dict)
    # fqn -> column -> distinct values, in the case the database stores them.
    # Case matters: `WHERE status = 'active'` finds nothing when the column
    # holds 'ACTIVE' on a case-sensitive collation.
    values: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    types: dict[str, dict[str, str]] = field(default_factory=dict)
    comments: dict[str, str] = field(default_factory=dict)
    default_filters: dict[str, list[str]] = field(default_factory=dict)
    # fqn -> questions the crawl could not answer on its own: a status column
    # whose values do not read as "active", so which one to keep by default is
    # a human decision. Never applied; surfaced by `--check`.
    pending_filters: dict[str, list[str]] = field(default_factory=dict)

    def summary(self, source_id: str) -> dict[str, int]:
        """Counts that say whether a source can be routed to and answered from."""
        ds = self.datasources.get(source_id)
        profile = self.profiles.get(source_id)
        tables = [t for t in (ds.tables if ds else []) if not t.is_view]
        fqns = {t.fqn for t in tables}
        return {
            "tables": len(tables),
            "columns": sum(len(t.columns) for t in tables),
            "columns_with_values": sum(
                1 for fqn in fqns for vals in self.values.get(fqn, {}).values() if vals
            ),
            "value_index": len(profile.value_index) if profile else 0,
            "synonyms": len(profile.synonyms) if profile else 0,
            "joins": len(ds.joins) if ds else 0,
            "pending_filters": sum(len(self.pending_filters.get(f, [])) for f in fqns),
        }


# ── JSON → the real dataclasses ──────────────────────────────────────────────
#
# Rebuilt rather than read as dicts, so the graph is produced by the same
# `tables_from_crawl` / `edges_from_crawl` the DAG uses to publish to Neo4j.
# What is loaded here cannot drift from what is written there.


def _column(raw: dict[str, Any]) -> Column:
    return Column(
        name=raw["name"],
        ordinal=raw.get("ordinal", 0),
        data_type=raw.get("data_type", ""),
        nullable=raw.get("nullable", True),
        comment=raw.get("comment"),
        distinct_count=raw.get("distinct_count"),
        null_fraction=raw.get("null_fraction"),
        sample_values=list(raw.get("sample_values") or []),
        is_pii=bool(raw.get("is_pii", False)),
        mask_policy=raw.get("mask_policy"),
    )


def _default_filter(raw: dict[str, Any]) -> DefaultFilter:
    return DefaultFilter(
        id=raw["id"],
        table=raw["table"],
        column=raw["column"],
        expression=raw["expression"],
        rationale=raw.get("rationale", ""),
        kind=raw.get("kind", ""),
        confidence=raw.get("confidence", 1.0),
        editable=raw.get("editable", True),
    )


def _table(raw: dict[str, Any]) -> Table:
    return Table(
        datasource_id=raw["datasource_id"],
        schema=raw["schema"],
        name=raw["name"],
        columns=[_column(c) for c in raw.get("columns") or []],
        comment=raw.get("comment"),
        row_estimate=raw.get("row_estimate"),
        is_view=bool(raw.get("is_view", False)),
        grain=raw.get("grain"),
        default_filters=[_default_filter(f) for f in raw.get("default_filters") or []],
    )


def datasource_from_json(raw: dict[str, Any]) -> Datasource:
    return Datasource(
        id=raw["id"],
        dialect=raw["dialect"],
        description=raw.get("description", ""),
        tables=[_table(t) for t in raw.get("tables") or []],
        joins=[
            JoinEdge(
                left_table=j["left_table"],
                left_column=j["left_column"],
                right_table=j["right_table"],
                right_column=j["right_column"],
                cardinality=j.get("cardinality", "n:1"),
                source=j.get("source", "declared"),
                confidence=j.get("confidence", 1.0),
            )
            for j in raw.get("joins") or []
        ],
        schema_version=raw.get("schema_version", 1),
    )


def profile_from_json(raw: dict[str, Any]) -> SourceProfile:
    # The crawl script serialises sets as sorted lists; turn them back.
    return SourceProfile(
        datasource_id=raw["datasource_id"],
        dialect=raw["dialect"],
        description=raw.get("description", ""),
        subject_areas=list(raw.get("subject_areas") or []),
        table_terms=set(raw.get("table_terms") or []),
        column_terms=set(raw.get("column_terms") or []),
        value_index=dict(raw.get("value_index") or {}),
        metric_names=set(raw.get("metric_names") or []),
        synonyms=dict(raw.get("synonyms") or {}),
        success_count=raw.get("success_count", 0),
    )


def _distinct(values: Iterable[str], limit: int) -> list[str]:
    seen: dict[str, None] = {}
    for v in values:
        s = str(v)
        if s and s not in seen:
            seen[s] = None
        if len(seen) >= limit:
            break
    return list(seen)


def _absorb(out: LoadedCatalog, ds: Datasource) -> None:
    crawl = SimpleNamespace(datasource=ds)
    for node in tables_from_crawl(crawl):
        out.graph.upsert_table(node)
    for edge in edges_from_crawl(crawl):
        out.graph.upsert_edge(edge)

    for table in ds.tables:
        out.types[table.fqn] = {c.name: c.data_type for c in table.columns}
        if table.comment:
            out.comments[table.fqn] = table.comment.strip()
        # Values from PII columns never enter the catalog the prompt is built
        # from. The crawl already declines to index them; this is the second
        # lock, because the prompt goes to a model outside the database.
        per_column = {
            c.name: _distinct(c.sample_values, VALUES_PER_COLUMN)
            for c in table.columns
            if c.sample_values and not c.is_pii
        }
        if per_column:
            out.values[table.fqn] = per_column
        # The crawl records a status column it cannot decide about as a filter
        # with an EMPTY expression — a note for a human, not a predicate. Passed
        # through, the compiler tries to parse '' and rejects every question on
        # the table. Very common with real data: OPEN/PAID/SHIPPED never read
        # as "active".
        applicable = [f.expression for f in table.default_filters if f.expression.strip()]
        undecided = [f.rationale for f in table.default_filters if not f.expression.strip()]
        if applicable:
            out.default_filters[table.fqn] = applicable
        if undecided:
            out.pending_filters[table.fqn] = undecided


def load_catalog(directory: str | Path) -> LoadedCatalog:
    """Everything the orchestrator needs, from the files the crawl writes."""
    root = Path(directory)
    files = sorted(root.glob("*.catalog.json")) if root.is_dir() else []
    if not files:
        # An empty catalog routes every question to "nothing covers that",
        # which reads as the system being broken rather than unconfigured.
        raise CatalogNotLoaded(
            f"no *.catalog.json in {root.resolve()} — run "
            f"`python scripts/beta_queries_crawl.py` first"
        )

    out = LoadedCatalog(graph=InMemoryGraph())
    for path in files:
        ds = datasource_from_json(json.loads(path.read_text()))
        out.datasources[ds.id] = ds
        _absorb(out, ds)
        profile_path = path.with_name(f"{ds.id}.profile.json")
        if profile_path.exists():
            out.profiles[ds.id] = profile_from_json(json.loads(profile_path.read_text()))
    return out


# ── Neo4j → memory ──────────────────────────────────────────────────────────
#
# Property for property the mirror of UPSERT_TABLE and UPSERT_EDGE in
# catalog/graph.py. `datasource` is not a Table property — it lives on the
# (:Datasource)-[:HAS_TABLE]-> relationship — so it is read from there.

READ_TABLES = """
MATCH (d:Datasource)-[:HAS_TABLE]->(t:Table)
OPTIONAL MATCH (t)-[:HAS_COLUMN]->(c:Column)
RETURN d.id AS datasource, t.fqn AS fqn, t.schema AS schema, t.name AS name,
       t.is_view AS is_view, t.row_estimate AS row_estimate, t.terms AS terms,
       t.bi_assets AS bi_assets, t.metrics AS metrics,
       collect(c.name) AS columns
"""

READ_EDGES = """
MATCH (l:Table)-[j:JOINS]->(r:Table)
RETURN l.fqn AS left, r.fqn AS right,
       j.left_column AS left_column, j.right_column AS right_column,
       j.source AS source, j.cardinality AS cardinality, j.confidence AS confidence
"""

CypherRunner = Callable[[str, dict[str, Any]], Iterable[Any]]


def _row(row: Any) -> dict[str, Any]:
    return dict(row) if not isinstance(row, dict) else row


def load_graph_from_neo4j(run: CypherRunner) -> InMemoryGraph:
    """The graph Neo4j holds, loaded into memory once rather than queried per question."""
    graph = InMemoryGraph()
    for raw in run(READ_TABLES, {}):
        r = _row(raw)
        graph.upsert_table(
            TableNode(
                fqn=r["fqn"],
                datasource=r["datasource"],
                schema=r["schema"],
                name=r["name"],
                columns=[c for c in (r.get("columns") or []) if c],
                terms=set(r.get("terms") or []),
                is_view=bool(r.get("is_view")),
                row_estimate=r.get("row_estimate"),
                metrics=set(r.get("metrics") or []),
                bi_assets=r.get("bi_assets") or 0,
            )
        )
    for raw in run(READ_EDGES, {}):
        r = _row(raw)
        graph.upsert_edge(
            Edge(
                left=r["left"],
                left_column=r["left_column"],
                right=r["right"],
                right_column=r["right_column"],
                source=r.get("source") or "declared",
                cardinality=r.get("cardinality") or "n:1",
                confidence=r.get("confidence") or 1.0,
            )
        )
    return graph
