"""Airflow: keep the Beta Queries catalog graph in sync with every datasource.

One DAG, one task group per source, driven entirely by
`data/config/beta_queries_sources.yaml`. Adding a database is a pull request
against that file — no DAG code changes, which is the whole point: the person
onboarding a warehouse is not the person who maintains Airflow.

    structure   every base table and column (and the names of the views we
                skip, so the catalog can explain why they are not queryable)
    joins       declared keys where the engine has them, name inference where
                it does not — Snowflake and Databricks do not enforce FKs
    values      low-cardinality columns sampled so "India" resolves to
                `country_code = 'IN'` without a model guessing
    publish     the routing profile into Redis, the graph into Neo4j

Schedules are per source and staggered, because a warehouse that runs its
nightly load at 02:00 should not be crawled at 02:00.

Credentials never appear here. Each source names an environment variable; the
worker reads it at run time. Use a read-only catalog principal — this crawl
reads metadata and samples values, it never answers questions.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

try:
    from airflow.decorators import dag, task, task_group
    from airflow.models import Variable

    HAS_AIRFLOW = True
except ImportError:  # pragma: no cover - lets the repo's test suite import this file
    HAS_AIRFLOW = False

CONFIG_PATH = Path(os.environ.get("BQ_SOURCES_CONFIG", "data/config/beta_queries_sources.yaml"))
DEFAULT_SCHEDULE = "0 5 * * *"
STAGGER_MINUTES = 17  # so ten sources do not all start on the same minute


def load_sources(path: Path = CONFIG_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    return list(data.get("sources") or [])


def schedule_for(index: int, source: dict[str, Any]) -> str:
    """Per-source schedule, staggered so crawls do not pile up."""
    if source.get("schedule"):
        return str(source["schedule"])
    minute = (index * STAGGER_MINUTES) % 60
    hour = 5 + (index * STAGGER_MINUTES) // 60
    return f"{minute} {hour % 24} * * *"


if HAS_AIRFLOW:
    DEFAULT_ARGS = {
        "owner": "data-platform",
        "retries": 2,
        "retry_delay": timedelta(minutes=5),
        "retry_exponential_backoff": True,
        # A crawl that hangs holds a database connection open; kill it rather
        # than let it run into the next scheduled crawl.
        "execution_timeout": timedelta(minutes=45),
        "depends_on_past": False,
    }

    @dag(
        dag_id="beta_queries_catalog_sync",
        description="Crawl every registered datasource and sync the catalog graph",
        schedule=DEFAULT_SCHEDULE,
        start_date=datetime(2026, 1, 1),
        catchup=False,
        max_active_runs=1,
        default_args=DEFAULT_ARGS,
        tags=["beta-queries", "catalog", "text-to-sql"],
        doc_md=__doc__,
    )
    def beta_queries_catalog_sync() -> None:
        sources = load_sources()

        for index, source in enumerate(sources):
            source_id = source["id"]

            @task_group(group_id=f"sync_{source_id}")
            def sync_one(src: dict[str, Any] = source) -> None:
                @task(task_id="crawl")
                def crawl(src: dict[str, Any]) -> dict[str, Any]:
                    from airflow_support.connections import open_connection
                    from beta_queries.catalog import crawler

                    dsn = os.environ.get(src["dsn_env"])
                    if not dsn:
                        raise RuntimeError(
                            f"{src['dsn_env']} is not set on the worker — "
                            "register it as a secret, never in this file"
                        )
                    connection = open_connection(src["dialect"], dsn)
                    try:
                        result = crawler.crawl(
                            src["id"],
                            src["dialect"],
                            crawler.dbapi_runner(connection),
                            description=(src.get("description") or "").strip(),
                            synonyms=src.get("synonyms") or {},
                            subject_areas=src.get("subject_areas") or [],
                        )
                    finally:
                        connection.close()

                    return {
                        "datasource": src["id"],
                        "tables": {
                            t.relname: [c.name for c in t.columns]
                            for t in result.datasource.base_tables
                        },
                        "summary": result.summary,
                        "errors": result.errors,
                        "payload": _serialise(result),
                    }

                @task(task_id="diff")
                def diff(crawled: dict[str, Any]) -> dict[str, Any]:
                    from beta_queries.sync.plan import diff_catalog

                    key = f"bq_catalog_{crawled['datasource']}"
                    previous = json.loads(Variable.get(key, default_var="{}"))
                    result = diff_catalog(crawled["datasource"], previous, crawled["tables"])
                    if result.safe_to_apply:
                        Variable.set(key, json.dumps(crawled["tables"]))
                    return {
                        "summary": result.summary(),
                        "safe": result.safe_to_apply,
                        "quarantined": result.quarantined,
                        "added": result.added_tables,
                        "removed": result.removed_tables,
                        "changed": result.changed_tables,
                        "seen": result.seen,
                    }

                @task(task_id="publish_graph")
                def publish_graph(crawled: dict[str, Any], diffed: dict[str, Any]) -> str:
                    if not diffed["safe"]:
                        # Fail loudly: a quarantined crawl is an incident, not a
                        # no-op, and the next run will retry from a clean state.
                        raise RuntimeError(diffed["quarantined"])

                    from airflow_support.connections import neo4j_runner
                    from beta_queries.catalog.graph import Neo4jGraph
                    from beta_queries.sync.plan import CatalogDiff, apply_to_graph

                    graph = Neo4jGraph(neo4j_runner())
                    graph.install_schema()

                    tables, edges = _deserialise(crawled["payload"])
                    restored = CatalogDiff(
                        datasource=crawled["datasource"],
                        added_tables=diffed["added"],
                        removed_tables=diffed["removed"],
                        changed_tables=diffed["changed"],
                        seen=diffed["seen"],
                    )
                    result = apply_to_graph(graph, tables, edges, restored, prune=graph.prune)
                    if result.errors:
                        raise RuntimeError("; ".join(result.errors[:5]))
                    return (
                        f"{result.tables_written} tables, {result.edges_written} joins, "
                        f"{len(result.pruned)} pruned"
                    )

                @task(task_id="publish_profile")
                def publish_profile(crawled: dict[str, Any]) -> str:
                    """The routing profile goes to Redis: it is read per question."""
                    from airflow_support.connections import redis_client

                    client = redis_client()
                    key = f"bq:profile:source:{crawled['datasource']}"
                    client.set(key, json.dumps(crawled["payload"].get("profile", {})))
                    return key

                crawled = crawl(src)
                diffed = diff(crawled)
                publish_graph(crawled, diffed)
                publish_profile(crawled)

            sync_one()

    beta_queries_catalog_sync()


def _serialise(result: Any) -> dict[str, Any]:
    """Flatten a CrawlResult for XCom. Airflow will not pickle dataclasses."""
    from dataclasses import asdict

    return {
        "tables": [
            {
                "fqn": t.fqn,
                "datasource": t.datasource_id,
                "schema": t.schema,
                "name": t.name,
                "columns": [c.name for c in t.columns],
                "comment": t.comment or "",
                "is_view": t.is_view,
                "row_estimate": t.row_estimate,
            }
            for t in result.datasource.tables
        ],
        "edges": [asdict(j) for j in result.datasource.joins],
        "profile": {
            "datasource_id": result.profile.datasource_id,
            "dialect": result.profile.dialect,
            "description": result.profile.description,
            "table_terms": sorted(result.profile.table_terms),
            "column_terms": sorted(result.profile.column_terms),
            "value_index": result.profile.value_index,
            "metric_names": sorted(result.profile.metric_names),
            "synonyms": result.profile.synonyms,
        },
    }


def _deserialise(payload: dict[str, Any]) -> tuple[list[Any], list[Any]]:
    from beta_queries.catalog.graph import Edge, TableNode

    tables = [
        TableNode(
            fqn=t["fqn"],
            datasource=t["datasource"],
            schema=t["schema"],
            name=t["name"],
            columns=t["columns"],
            terms=set((t.get("comment") or "").lower().split()),
            is_view=t["is_view"],
            row_estimate=t.get("row_estimate"),
        )
        for t in payload.get("tables", [])
    ]
    edges = [
        Edge(
            left=e["left_table"],
            left_column=e["left_column"],
            right=e["right_table"],
            right_column=e["right_column"],
            source=e.get("source", "declared"),
            cardinality=e.get("cardinality", "n:1"),
            confidence=e.get("confidence", 1.0),
        )
        for e in payload.get("edges", [])
    ]
    return tables, edges
