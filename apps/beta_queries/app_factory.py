"""Build a working orchestrator from the sources config and the crawled catalog.

Until this module there was no production entrypoint: the demo wires one
DuckDB source by hand, and anyone with real databases had to assemble sources,
graph, profiles and entitlements themselves — with the Neo4j and Redis read
paths missing underneath them.

    orch, report = build_orchestrator()
    answer = orch.ask("how many people are in india", principal="me")

Everything the request path needs is loaded into memory here, once. No
question ever waits on Neo4j or Redis.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from beta_queries.agent.providers import LunaProvider, Provider
from beta_queries.catalog.graph import InMemoryGraph
from beta_queries.catalog.load import LoadedCatalog, load_catalog, load_graph_from_neo4j
from beta_queries.dialogue.policy import DialoguePolicy
from beta_queries.entitlements.resolver import InMemoryEntitlements
from beta_queries.orchestrator import DEFAULT_ROW_LIMIT, Orchestrator, Source
from beta_queries.routing.router import SourceProfile
from beta_queries.sql.connect import connector

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "data" / "config"
DEFAULT_SOURCES = CONFIG / "beta_queries_sources.yaml"
DEFAULT_CATALOG = ROOT / ".bq-catalog"

LOCAL_PRINCIPAL = "local"


@dataclass
class BuildReport:
    """What was wired, and what was left out and why — printed, never guessed."""

    ready: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)
    graph_source: str = "catalog files"


def _local_entitlements(catalog: LoadedCatalog, ids: Iterable[str]) -> InMemoryEntitlements:
    """Grant the local user every base table that was loaded.

    **Local development only.** On a laptop, the person asking is the person
    whose credentials are in the DSN, so the database enforces what they can
    read. A shared deployment must resolve real grants — that resolver is
    unchanged and is what `entitlements/resolver.py` is for.
    """
    wanted = set(ids)
    tables = {
        t.fqn
        for ds_id, ds in catalog.datasources.items()
        if ds_id in wanted
        for t in ds.tables
        if not t.is_view
    }
    return InMemoryEntitlements(grants={LOCAL_PRINCIPAL: tables})


def neo4j_runner_from_env() -> Callable[[str, dict[str, Any]], list[dict[str, Any]]]:
    """A Cypher runner from BQ_NEO4J_URI / BQ_NEO4J_USER / BQ_NEO4J_PASSWORD."""
    from neo4j import GraphDatabase  # optional dependency, imported only when asked for

    driver = GraphDatabase.driver(
        os.environ["BQ_NEO4J_URI"],
        auth=(os.environ["BQ_NEO4J_USER"], os.environ["BQ_NEO4J_PASSWORD"]),
    )

    def run(cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        with driver.session() as session:
            return [record.data() for record in session.run(cypher, params)]

    return run


def build_orchestrator(
    sources_yaml: str | Path = DEFAULT_SOURCES,
    catalog_dir: str | Path = DEFAULT_CATALOG,
    provider: Provider | None = None,
    graph_from_neo4j: bool = False,
    graph: InMemoryGraph | None = None,
) -> tuple[Orchestrator, BuildReport]:
    """One orchestrator over every configured source whose catalog and DSN are present."""
    config = yaml.safe_load(Path(sources_yaml).read_text()) or {}
    catalog = load_catalog(catalog_dir)
    report = BuildReport()

    if graph is None and graph_from_neo4j:
        graph = load_graph_from_neo4j(neo4j_runner_from_env())
        report.graph_source = "Neo4j (loaded into memory)"

    sources: list[Source] = []
    for src in config.get("sources") or []:
        sid, dialect, dsn_env = src["id"], src["dialect"], src["dsn_env"]
        if sid not in catalog.datasources:
            report.skipped[sid] = "not crawled yet — run scripts/beta_queries_crawl.py"
            continue
        dsn = os.environ.get(dsn_env)
        if not dsn:
            report.skipped[sid] = f"{dsn_env} is not set"
            continue

        prefix = f"{sid}."
        mine = lambda m: {k: v for k, v in m.items() if k.startswith(prefix)}  # noqa: E731
        profile = catalog.profiles.get(sid) or SourceProfile(datasource_id=sid, dialect=dialect)
        # The config's synonyms win over the crawled copy: they are what the
        # operator edits, and re-crawling just to pick up a synonym is a trap.
        profile.synonyms = {**profile.synonyms, **(src.get("synonyms") or {})}

        # `default_filters` in the config is how a person decides what the
        # crawl could not: `--check` lists status columns it left undecided,
        # and this is where the answer goes. Keyed by `schema.table`.
        filters = {k: list(v) for k, v in mine(catalog.default_filters).items()}
        for relname, expression in (src.get("default_filters") or {}).items():
            chosen = [expression] if isinstance(expression, str) else list(expression)
            filters[f"{sid}.{relname}"] = chosen

        sources.append(
            Source(
                id=sid,
                dialect=dialect,
                profile=profile,
                connect=connector(dialect, dsn),
                column_types=mine(catalog.types),
                default_filters=filters,
                column_values=mine(catalog.values),
                comments=mine(catalog.comments),
            )
        )
        report.ready.append(sid)

    if not sources:
        reasons = [f"{k}: {v}" for k, v in report.skipped.items()]
        detail = "; ".join(reasons) or "no sources configured"
        raise RuntimeError(f"no datasource is ready to answer questions — {detail}")

    dialogue = CONFIG / "beta_queries_dialogue.yaml"
    steps = CONFIG / "beta_queries_steps.yaml"
    errors = CONFIG / "beta_queries_errors.yaml"
    orchestrator = Orchestrator(
        sources=sources,
        graph=graph or catalog.graph,
        entitlements=_local_entitlements(catalog, report.ready),
        provider=provider or LunaProvider(),
        policy=DialoguePolicy.from_file(dialogue) if dialogue.exists() else None,
        steps_config=str(steps) if steps.exists() else None,
        errors_config=str(errors) if errors.exists() else None,
        row_limit=int(os.environ.get("BQ_ROW_LIMIT", DEFAULT_ROW_LIMIT)),
    )
    return orchestrator, report
