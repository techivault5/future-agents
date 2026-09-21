"""The schema graph — which tables answer this, and how do they join.

Two questions decide whether text-to-SQL works, and neither is a vector search:

    which tables    out of ten thousand, the four this question needs
    how do they     the join path between those four, with the right keys and
    connect         the right cardinality

Both are graph traversals, which is why the catalog lives in a graph and not in
a cache. A cache answers "what did I store under this key"; it cannot answer
"what is the shortest path from `employee` to `invoice`", and that path is the
single thing a model most often invents.

The graph is small — tens of thousands of nodes for a large estate — so the
whole thing fits in memory. `InMemoryGraph` is the reference implementation and
the test target; `Neo4jGraph` runs the identical algorithms as Cypher against a
real server. Both satisfy `SchemaGraph`, so nothing downstream knows which it
has.

Edge trust is explicit and it matters: a declared foreign key is a fact, an
inferred edge is a guess that is usually right, and a learned edge is evidence
that people keep joining these two tables and getting answers they kept. On
Snowflake and Databricks, where constraints are informational, the second and
third are all there is.
"""

from __future__ import annotations

import heapq
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

# How far to trust each kind of edge when choosing between two join paths.
# Lower is better; these are path weights, not probabilities.
EDGE_WEIGHT = {"declared": 1.0, "learned": 1.4, "inferred": 2.2}

# A join path longer than this is almost certainly wrong — a fan-out through a
# hub table rather than a real relationship.
MAX_PATH_LENGTH = 4


# Schemas and name prefixes that mark a copy rather than the thing itself.
# A staging table matches the business words exactly as well as the real table
# does — it is the same data, one step earlier — so nothing lexical separates
# them. This is the tie-break, and without it half the answers come from a
# table nobody is supposed to query.
_STAGING_SCHEMAS = frozenset(
    {
        "stg",
        "staging",
        "raw",
        "landing",
        "tmp",
        "temp",
        "work",
        "scratch",
        "bronze",
        "src",
        "ingest",
        "quarantine",
        "archive",
        "bak",
        "backup",
    }
)
_STAGING_PREFIX = re.compile(r"^(stg|staging|raw|tmp|temp|wrk|work|bak|backup|old|test|dev)_")
_STAGING_SUFFIX = re.compile(r"_(raw|stg|staging|tmp|temp|bak|backup|old|copy|v\d+|\d{8})$")

STAGING_PENALTY = 45.0


def is_staging(schema: str, name: str) -> bool:
    return bool(
        schema.lower() in _STAGING_SCHEMAS
        or _STAGING_PREFIX.match(name.lower())
        or _STAGING_SUFFIX.search(name.lower())
    )


def terms_of(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(t) > 1]


@dataclass
class TableNode:
    fqn: str  # datasource.schema.table
    datasource: str
    schema: str
    name: str
    columns: list[str] = field(default_factory=list)
    terms: set[str] = field(default_factory=set)
    is_view: bool = False
    row_estimate: int | None = None
    # Certified metrics and BI assets that read this table. A table three
    # dashboards depend on is a better answer than an identically named
    # staging copy nobody has opened in a year.
    metrics: set[str] = field(default_factory=set)
    bi_assets: int = 0
    success_count: int = 0

    @property
    def relname(self) -> str:
        return f"{self.schema}.{self.name}"


@dataclass
class Edge:
    left: str  # table fqn
    left_column: str
    right: str
    right_column: str
    source: str = "declared"  # declared | inferred | learned
    cardinality: str = "n:1"
    confidence: float = 1.0
    uses: int = 0

    @property
    def weight(self) -> float:
        base = EDGE_WEIGHT.get(self.source, 2.5)
        # Evidence of repeated successful use pulls an edge toward "declared".
        return max(0.6, base - min(0.5, 0.05 * self.uses))

    def other(self, fqn: str) -> str | None:
        if fqn == self.left:
            return self.right
        if fqn == self.right:
            return self.left
        return None

    def columns_from(self, fqn: str) -> tuple[str, str]:
        return (
            (self.left_column, self.right_column)
            if fqn == self.left
            else (
                self.right_column,
                self.left_column,
            )
        )


@dataclass
class JoinStep:
    left: str
    left_column: str
    right: str
    right_column: str
    source: str
    cardinality: str

    def as_sql(self, aliases: dict[str, str]) -> str:
        la, ra = aliases.get(self.left, self.left), aliases.get(self.right, self.right)
        return f"{la}.{self.left_column} = {ra}.{self.right_column}"


@dataclass
class JoinPlan:
    tables: list[str]
    steps: list[JoinStep] = field(default_factory=list)
    weight: float = 0.0
    unreachable: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unreachable

    @property
    def only_inferred(self) -> bool:
        """True when nothing in this plan is a declared key.

        On Snowflake and Databricks this is the normal case, and it is the
        thing to say out loud rather than hide: the join is a name-based guess.
        """
        return bool(self.steps) and all(s.source == "inferred" for s in self.steps)


@dataclass
class TableCandidate:
    fqn: str
    score: float
    reasons: list[str] = field(default_factory=list)


class SchemaGraph(Protocol):
    def upsert_table(self, table: TableNode) -> None: ...
    def upsert_edge(self, edge: Edge) -> None: ...
    def tables(self) -> list[TableNode]: ...
    def edges(self) -> list[Edge]: ...


class InMemoryGraph:
    """The reference implementation, and what the tests run against."""

    def __init__(self) -> None:
        self._tables: dict[str, TableNode] = {}
        self._edges: dict[tuple[str, str, str, str], Edge] = {}
        self._synonyms: dict[str, str] = {}

    # ── writes ──────────────────────────────────────────────────────────────

    # Fields a crawl cannot know and must never overwrite. A crawl reads the
    # database; these come from BI lineage, the metric layer and from what
    # people actually asked. Losing them on every re-crawl silently degrades
    # ranking: a certified metric is worth +35 and BI assets up to +15, against
    # a staging penalty of 45 — so a re-crawl could drop the curated table
    # below its own staging copy.
    _CURATED = ("metrics", "bi_assets", "success_count")

    def upsert_table(self, table: TableNode) -> None:
        existing = self._tables.get(table.fqn)
        if existing:
            for field_name in self._CURATED:
                incoming = getattr(table, field_name)
                # A crawl leaves these at their empty default; anything the
                # caller did set is a deliberate update and wins.
                if not incoming:
                    setattr(table, field_name, getattr(existing, field_name))
            table.success_count = max(table.success_count, existing.success_count)
        self._tables[table.fqn] = table

    def upsert_edge(self, edge: Edge) -> None:
        key = (edge.left, edge.left_column, edge.right, edge.right_column)
        current = self._edges.get(key)
        if current and EDGE_WEIGHT.get(current.source, 9) <= EDGE_WEIGHT.get(edge.source, 9):
            current.uses = max(current.uses, edge.uses)
            return
        self._edges[key] = edge

    def add_synonyms(self, mapping: dict[str, str]) -> None:
        self._synonyms.update({k.lower(): v.lower() for k, v in mapping.items()})

    def record_success(self, tables: Sequence[str], steps: Sequence[JoinStep] = ()) -> None:
        """Remember that this combination produced an answer somebody kept.

        This is what turns a cold catalog into a warm one: the paths people
        actually use get cheaper, so the next question takes them first.
        """
        for fqn in tables:
            node = self._tables.get(fqn)
            if node:
                node.success_count += 1
        for step in steps:
            key = (step.left, step.left_column, step.right, step.right_column)
            edge = self._edges.get(key)
            if edge:
                edge.uses += 1
            else:
                self.upsert_edge(
                    Edge(
                        left=step.left,
                        left_column=step.left_column,
                        right=step.right,
                        right_column=step.right_column,
                        source="learned",
                        uses=1,
                    )
                )

    # ── reads ───────────────────────────────────────────────────────────────

    def tables(self) -> list[TableNode]:
        return list(self._tables.values())

    def edges(self) -> list[Edge]:
        return list(self._edges.values())

    def table(self, fqn: str) -> TableNode | None:
        return self._tables.get(fqn)

    def neighbours(self, fqn: str) -> list[tuple[str, Edge]]:
        out: list[tuple[str, Edge]] = []
        for edge in self._edges.values():
            other = edge.other(fqn)
            if other is not None:
                out.append((other, edge))
        return out

    # ── the two questions ───────────────────────────────────────────────────

    def candidate_tables(
        self,
        question: str,
        entitled: set[str] | None = None,
        datasource: str | None = None,
        limit: int = 8,
    ) -> list[TableCandidate]:
        """Rank tables against a question. Views never rank.

        The ordering is deliberately not pure text similarity. A table with a
        certified metric on it, or one three dashboards read, is a better
        answer than a lexically closer staging copy — because someone has
        already decided that table is the one that counts.
        """
        asked = set(terms_of(question))
        asked |= {self._synonyms[t] for t in asked if t in self._synonyms}

        out: list[TableCandidate] = []
        for node in self._tables.values():
            if node.is_view:
                continue
            if datasource and node.datasource != datasource:
                continue
            if entitled is not None and node.fqn not in entitled:
                continue

            score = 0.0
            reasons: list[str] = []

            name_hits = asked & set(terms_of(node.name))
            if name_hits:
                score += 30 * len(name_hits)
                reasons.append(f"table name: {', '.join(sorted(name_hits))}")

            term_hits = asked & node.terms
            if term_hits:
                score += 8 * len(term_hits)
                reasons.append(f"described by: {', '.join(sorted(list(term_hits)[:3]))}")

            column_terms = {t for c in node.columns for t in terms_of(c)}
            column_hits = asked & column_terms
            if column_hits:
                score += 6 * len(column_hits)
                reasons.append(f"columns: {', '.join(sorted(list(column_hits)[:3]))}")

            metric_hits = asked & {m.lower() for m in node.metrics}
            if metric_hits:
                score += 35 * len(metric_hits)
                reasons.append(f"certified metric: {', '.join(sorted(metric_hits))}")

            if node.bi_assets and score > 0:
                bump = min(15.0, 3.0 * node.bi_assets)
                score += bump
                reasons.append(f"{node.bi_assets} BI assets read it")

            if node.success_count and score > 0:
                score += min(20.0, 4.0 * node.success_count**0.5)
                reasons.append(f"answered {node.success_count} questions before")

            if score > 0 and is_staging(node.schema, node.name):
                score -= STAGING_PENALTY
                reasons.append("staging copy — demoted")

            if score > 0:
                out.append(TableCandidate(node.fqn, round(score, 2), reasons))

        out.sort(key=lambda c: (-c.score, c.fqn))
        return out[:limit]

    def join_plan(self, tables: Sequence[str]) -> JoinPlan:
        """Connect these tables with the cheapest set of real join paths.

        A greedy Steiner tree: start from the first table, repeatedly attach
        whichever remaining table is cheapest to reach from the tree so far,
        through intermediate tables if that is the only way. Cheapest means
        declared keys before learned ones before name-inferred ones.
        """
        wanted = [t for t in dict.fromkeys(tables) if t in self._tables]
        if len(wanted) <= 1:
            return JoinPlan(tables=list(wanted))

        connected = {wanted[0]}
        ordered = [wanted[0]]
        steps: list[JoinStep] = []
        total = 0.0
        unreachable: list[str] = []

        for target in wanted[1:]:
            if target in connected:
                continue
            path, cost = self._cheapest_path(connected, target)
            if path is None:
                unreachable.append(target)
                continue
            total += cost
            for left, edge in path:
                right = edge.other(left)
                if right is None:  # pragma: no cover - defensive
                    continue
                lc, rc = edge.columns_from(left)
                steps.append(
                    JoinStep(
                        left=left,
                        left_column=lc,
                        right=right,
                        right_column=rc,
                        source=edge.source,
                        cardinality=edge.cardinality,
                    )
                )
                if right not in connected:
                    connected.add(right)
                    ordered.append(right)

        return JoinPlan(
            tables=ordered, steps=steps, weight=round(total, 3), unreachable=unreachable
        )

    def _cheapest_path(
        self, sources: set[str], target: str
    ) -> tuple[list[tuple[str, Edge]] | None, float]:
        """Dijkstra from the connected set to one target, returning the hops."""
        seen: set[str] = set()
        queue: list[tuple[float, int, str, list[tuple[str, Edge]]]] = [
            (0.0, 0, s, []) for s in sources
        ]
        heapq.heapify(queue)
        counter = len(queue)

        while queue:
            cost, _, node, path = heapq.heappop(queue)
            if node == target:
                return path, cost
            if node in seen or len(path) > MAX_PATH_LENGTH:
                continue
            seen.add(node)
            for neighbour, edge in self.neighbours(node):
                if neighbour in seen:
                    continue
                counter += 1
                heapq.heappush(
                    queue, (cost + edge.weight, counter, neighbour, path + [(node, edge)])
                )
        return None, 0.0


# ── Neo4j ────────────────────────────────────────────────────────────────────

CypherRunner = Callable[[str, dict[str, Any]], Sequence[Any]]

# Run once per deployment. Without the constraints a re-crawl duplicates every
# node; without the indexes the term lookup degrades to a full scan.
SCHEMA_STATEMENTS = (
    "CREATE CONSTRAINT bq_table_fqn IF NOT EXISTS FOR (t:Table) REQUIRE t.fqn IS UNIQUE",
    "CREATE CONSTRAINT bq_datasource_id IF NOT EXISTS FOR (d:Datasource) REQUIRE d.id IS UNIQUE",
    "CREATE INDEX bq_table_terms IF NOT EXISTS FOR (t:Table) ON (t.name)",
    "CREATE INDEX bq_column_name IF NOT EXISTS FOR (c:Column) ON (c.name)",
    "CREATE FULLTEXT INDEX bq_table_text IF NOT EXISTS "
    "FOR (t:Table) ON EACH [t.name, t.description]",
)

# `coalesce` on the curated fields is load-bearing: a crawl passes them as null
# and must not erase what BI lineage and usage put there. The final DETACH
# DELETE is the other half — without it a dropped column lives in the graph
# forever, which is exactly the drift a refresh exists to correct.
UPSERT_TABLE = """
MERGE (d:Datasource {id: $datasource})
MERGE (t:Table {fqn: $fqn})
  SET t.schema = $schema, t.name = $name, t.is_view = $is_view,
      t.row_estimate = $row_estimate, t.terms = $terms,
      t.bi_assets = coalesce($bi_assets, t.bi_assets, 0),
      t.metrics   = coalesce($metrics, t.metrics, []),
      t.crawled_at = datetime()
MERGE (d)-[:HAS_TABLE]->(t)
WITH t
UNWIND $columns AS col
  MERGE (c:Column {fqn: t.fqn + '.' + col})
    SET c.name = col, c.seen_at = datetime()
  MERGE (t)-[:HAS_COLUMN]->(c)
WITH DISTINCT t
MATCH (t)-[:HAS_COLUMN]->(gone:Column)
WHERE NOT gone.name IN $columns
DETACH DELETE gone
"""

UPSERT_EDGE = """
MATCH (l:Table {fqn: $left}), (r:Table {fqn: $right})
MERGE (l)-[j:JOINS {left_column: $left_column, right_column: $right_column}]->(r)
  SET j.source = $source, j.cardinality = $cardinality,
      j.confidence = $confidence, j.weight = $weight
"""

# Neo4j's shortestPath does the traversal server-side; the weight lives on the
# relationship so a declared key is preferred without post-filtering.
JOIN_PATH = (
    """
MATCH (a:Table {fqn: $left}), (b:Table {fqn: $right})
MATCH path = shortestPath((a)-[:JOINS*1..%d]-(b))
RETURN [rel IN relationships(path) |
        {left_column: rel.left_column, right_column: rel.right_column,
         source: rel.source, cardinality: rel.cardinality}] AS hops,
       [node IN nodes(path) | node.fqn] AS fqns,
       reduce(w = 0.0, rel IN relationships(path) | w + coalesce(rel.weight, 2.0)) AS weight
ORDER BY weight ASC
LIMIT 1
"""
    % MAX_PATH_LENGTH
)

# Deleting what the crawl no longer sees is what keeps a dropped table from
# being offered forever. Scoped to one datasource so a failed crawl of one
# source cannot empty the others.
PRUNE_MISSING = """
MATCH (d:Datasource {id: $datasource})-[:HAS_TABLE]->(t:Table)
WHERE NOT t.fqn IN $seen
DETACH DELETE t
"""


class Neo4jGraph:
    """The same algorithms, executed as Cypher.

    Takes a `run(cypher, params) -> rows` callable rather than a driver, for
    the same reasons the crawler does: no driver import here, the caller picks
    the principal, and every statement is testable against a fake.
    """

    def __init__(self, run: CypherRunner) -> None:
        self.run = run

    def install_schema(self) -> None:
        for statement in SCHEMA_STATEMENTS:
            self.run(statement, {})

    def upsert_table(self, table: TableNode) -> None:
        self.run(
            UPSERT_TABLE,
            {
                "datasource": table.datasource,
                "fqn": table.fqn,
                "schema": table.schema,
                "name": table.name,
                "is_view": table.is_view,
                "row_estimate": table.row_estimate,
                "terms": sorted(table.terms),
                # None, not 0/[] — the Cypher coalesces, so "the crawl does
                # not know" is distinct from "the crawl says zero".
                "bi_assets": table.bi_assets or None,
                "metrics": sorted(table.metrics) or None,
                "columns": list(table.columns),
            },
        )

    def upsert_edge(self, edge: Edge) -> None:
        self.run(
            UPSERT_EDGE,
            {
                "left": edge.left,
                "right": edge.right,
                "left_column": edge.left_column,
                "right_column": edge.right_column,
                "source": edge.source,
                "cardinality": edge.cardinality,
                "confidence": edge.confidence,
                "weight": edge.weight,
            },
        )

    def prune(self, datasource: str, seen: Iterable[str]) -> None:
        self.run(PRUNE_MISSING, {"datasource": datasource, "seen": sorted(set(seen))})

    def shortest_join(self, left: str, right: str) -> list[dict[str, Any]]:
        rows = list(self.run(JOIN_PATH, {"left": left, "right": right}))
        if not rows:
            return []
        row = rows[0]
        hops = row["hops"] if isinstance(row, dict) else row[0]
        return list(hops)


# ── module-level entry points ────────────────────────────────────────────────
#
# `agent.yaml` declares tools as `module:function`, so the orchestrator-facing
# surface has to be module-level. These are thin wrappers over the graph's own
# methods; the graph is passed in rather than reached for, because there is no
# global one and a request's graph is scoped to what the asker may see.


def join_paths(tables: Sequence[str], graph: InMemoryGraph) -> dict[str, Any]:
    """The `catalog.join_path` tool: how do these tables connect?

    Returns the plan as plain data — the tool surface is JSON, not objects.
    `unreachable` being non-empty is the honest answer that no relationship
    exists, and the caller must not join those tables anyway.
    """
    plan = graph.join_plan(tables)
    return {
        "tables": plan.tables,
        "steps": [
            {
                "left": step.left,
                "left_column": step.left_column,
                "right": step.right,
                "right_column": step.right_column,
                "source": step.source,
                "cardinality": step.cardinality,
            }
            for step in plan.steps
        ],
        "weight": plan.weight,
        "unreachable": plan.unreachable,
        "only_inferred": plan.only_inferred,
    }
