"""Catalog sync — keep the graph honest about what the databases actually hold.

A catalog that is right on the day it was built and wrong a month later is
worse than no catalog: it answers confidently about a column that was dropped.
So the crawl runs on a schedule, and every run produces a *diff* rather than a
rewrite.

The diff matters for three reasons:

    cost        a re-crawl of a 40 000-table estate writes 40 000 nodes if you
                rewrite, and a few dozen if you diff.
    safety      a crawl that fails half way through must not look like "every
                table was dropped". A run that sees suspiciously less than the
                last one is quarantined, not applied.
    lineage     "this column disappeared on the 14th" is answerable only if
                someone wrote down that it disappeared.

Nothing here imports Airflow. Airflow calls it; the logic is testable without
a scheduler, which is the only way anyone will ever test it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, Sequence

from beta_queries.catalog.graph import Edge, TableNode

# A crawl that returns less than this fraction of the previous run's tables is
# assumed to have failed part way through. Chosen to tolerate a real quarter's
# worth of decommissioning without tolerating a truncated result set.
SHRINK_GUARD = 0.7


class GraphSink(Protocol):
    def upsert_table(self, table: TableNode) -> None: ...
    def upsert_edge(self, edge: Edge) -> None: ...


@dataclass
class CatalogDiff:
    datasource: str
    added_tables: list[str] = field(default_factory=list)
    removed_tables: list[str] = field(default_factory=list)
    changed_tables: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    added_edges: int = 0
    seen: list[str] = field(default_factory=list)
    quarantined: str = ""
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def safe_to_apply(self) -> bool:
        return not self.quarantined

    @property
    def empty(self) -> bool:
        return not (self.added_tables or self.removed_tables or self.changed_tables)

    def summary(self) -> str:
        if self.quarantined:
            return f"{self.datasource}: QUARANTINED — {self.quarantined}"
        if self.empty:
            return f"{self.datasource}: no change ({len(self.seen)} tables)"
        return (
            f"{self.datasource}: +{len(self.added_tables)} tables, "
            f"-{len(self.removed_tables)}, ~{len(self.changed_tables)} changed, "
            f"{self.added_edges} joins"
        )


def diff_catalog(
    datasource: str,
    previous: dict[str, Sequence[str]],
    current: dict[str, Sequence[str]],
    shrink_guard: float = SHRINK_GUARD,
) -> CatalogDiff:
    """Compare two crawls of one datasource. Both are {relname: [columns]}."""
    diff = CatalogDiff(datasource=datasource, seen=sorted(current))

    if not current:
        diff.quarantined = "crawl returned no tables"
        return diff
    if previous and len(current) < len(previous) * shrink_guard:
        diff.quarantined = (
            f"crawl returned {len(current)} tables against {len(previous)} last run — "
            "treated as a partial crawl, not a mass drop"
        )
        return diff

    diff.added_tables = sorted(set(current) - set(previous))
    diff.removed_tables = sorted(set(previous) - set(current))

    for relname in sorted(set(current) & set(previous)):
        before, after = set(previous[relname]), set(current[relname])
        added, removed = sorted(after - before), sorted(before - after)
        if added or removed:
            diff.changed_tables[relname] = {"added": added, "removed": removed}

    return diff


@dataclass
class SyncResult:
    diff: CatalogDiff
    tables_written: int = 0
    edges_written: int = 0
    pruned: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and self.diff.safe_to_apply


def apply_to_graph(
    graph: GraphSink,
    tables: Sequence[TableNode],
    edges: Sequence[Edge],
    diff: CatalogDiff,
    prune: Any = None,
) -> SyncResult:
    """Write a crawl into the graph, skipping the work the diff says is done.

    A quarantined diff writes nothing at all — including the tables that did
    come back — because a partial crawl cannot be told from a real deletion,
    and half-applying it is how a catalog quietly loses a schema.
    """
    result = SyncResult(diff=diff)
    if not diff.safe_to_apply:
        result.errors.append(diff.quarantined)
        return result

    touched = set(diff.added_tables) | set(diff.changed_tables)
    for table in tables:
        # A table whose columns and flags are unchanged still needs its
        # crawled_at refreshed, or pruning cannot tell stale from absent.
        if touched and table.relname not in touched and table.fqn not in touched:
            continue
        try:
            graph.upsert_table(table)
            result.tables_written += 1
        except Exception as exc:  # noqa: BLE001 - one table must not fail a sync
            result.errors.append(f"{table.fqn}: {exc}")

    for edge in edges:
        try:
            graph.upsert_edge(edge)
            result.edges_written += 1
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"edge {edge.left}->{edge.right}: {exc}")

    if prune is not None and diff.removed_tables:
        try:
            prune(diff.datasource, diff.seen)
            result.pruned = list(diff.removed_tables)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"prune: {exc}")

    return result


def tables_from_crawl(result: Any) -> list[TableNode]:
    """Adapt a `catalog.crawler.CrawlResult` into graph nodes."""
    out: list[TableNode] = []
    ds = result.datasource
    for table in ds.tables:
        out.append(
            TableNode(
                fqn=table.fqn,
                datasource=ds.id,
                schema=table.schema,
                name=table.name,
                columns=[c.name for c in table.columns],
                terms=set((table.comment or "").lower().split()),
                is_view=table.is_view,
                row_estimate=table.row_estimate,
            )
        )
    return out


def edges_from_crawl(result: Any) -> list[Edge]:
    return [
        Edge(
            left=join.left_table,
            left_column=join.left_column,
            right=join.right_table,
            right_column=join.right_column,
            source=join.source,
            cardinality=join.cardinality,
            confidence=join.confidence,
        )
        for join in result.datasource.joins
    ]
