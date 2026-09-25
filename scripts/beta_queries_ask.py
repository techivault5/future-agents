#!/usr/bin/env python3
"""Ask a question against your real datasources — and see why it answered.

    python scripts/beta_queries_ask.py --check                      # is each source ready?
    python scripts/beta_queries_ask.py "how many people in india"   # ask, routed
    python scripts/beta_queries_ask.py "..." --source hrdb          # pin one source
    python scripts/beta_queries_ask.py "..." --debug                # show every stage

`--debug` is the diagnostic. It prints the route score for every source, the
tables considered, the schema cards exactly as the model saw them, the full
prompt, the raw reply with its stop reason and latency, and the result. The
two common failure modes look nothing alike in that output:

  - the model call failed      -> look at `stop reason` and `latency`
  - the answer is off-question -> look at the route scores and the cards

Loads the catalog the crawl wrote, once. Nothing here calls Neo4j or Redis per
question.
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / p) for p in ("apps", "packages")]

from beta_queries.agent.providers import Completion  # noqa: E402
from beta_queries.app_factory import (  # noqa: E402
    DEFAULT_CATALOG,
    DEFAULT_SOURCES,
    LOCAL_PRINCIPAL,
    build_orchestrator,
)
from beta_queries.catalog.load import CatalogNotLoaded, load_catalog  # noqa: E402
from beta_queries.routing.router import score_source  # noqa: E402
from beta_queries.sql.connect import probe  # noqa: E402

RULE = "─" * 78


class RecordingProvider:
    """Wraps the real provider and keeps what it was sent and what it said."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.calls: list[tuple[str, str, Completion | None, str]] = []

    def complete(self, system: str, user: str, **kw: Any) -> Completion:
        try:
            completion = self.inner.complete(system, user, **kw)
        except Exception as exc:
            self.calls.append((system, user, None, f"{type(exc).__name__}: {exc}"))
            raise
        self.calls.append((system, user, completion, ""))
        return completion


def section(title: str) -> None:
    print(f"\n{RULE}\n{title}\n{RULE}")


def check(sources_yaml: Path, catalog_dir: Path, connect_check: bool = True) -> int:
    """Per source: the counts that decide whether it can be routed to and answered."""
    import os

    import yaml

    try:
        catalog = load_catalog(catalog_dir)
    except CatalogNotLoaded as exc:
        print(f"FAIL  {exc}")
        return 1

    config = yaml.safe_load(sources_yaml.read_text()) or {}
    bad = 0
    header = (
        f"{'source':<14}{'tables':>7}{'cols':>7}{'w/vals':>8}{'values':>8}{'synonyms':>10}  dsn"
    )
    print(header)
    print("-" * len(header))
    for src in config.get("sources") or []:
        sid = src["id"]
        if sid not in catalog.datasources:
            print(f"{sid:<14}  not crawled — run scripts/beta_queries_crawl.py --source {sid}")
            bad += 1
            continue
        s = catalog.summary(sid)
        synonyms = max(s["synonyms"], len(src.get("synonyms") or {}))
        dsn = "set" if os.environ.get(src["dsn_env"]) else f"MISSING {src['dsn_env']}"
        print(
            f"{sid:<14}{s['tables']:>7}{s['columns']:>7}{s['columns_with_values']:>8}"
            f"{s['value_index']:>8}{synonyms:>10}  {dsn}"
        )
        problems = []
        if s["columns_with_values"] == 0:
            problems.append("no column values — the model will guess what columns hold")
        if s["value_index"] == 0:
            problems.append("empty value index — questions naming a value cannot route here")
        if synonyms == 0:
            problems.append("no synonyms — business words will not match your table names")
        if "MISSING" in dsn:
            problems.append(f"set {src['dsn_env']} to query this source")
        elif connect_check:
            # Driver, DSN, network and credentials in one round trip — before
            # a question is asked, not discovered by one.
            failure = probe(src["dialect"], os.environ[src["dsn_env"]])
            if failure:
                problems.append(failure)
            else:
                print(f"{'':<14}  connected — SELECT 1 ok")
        for p in problems:
            print(f"{'':<14}  ! {p}")
        # Advisory, not a failure: these are skipped, never applied.
        for fqn, notes in catalog.pending_filters.items():
            if fqn.startswith(f"{sid}."):
                for note in notes:
                    print(f"{'':<14}  ~ {fqn.split('.', 1)[1]}: {note}")
        bad += bool(problems)
    print()
    print("ok — every source is ready" if not bad else f"{bad} source(s) need attention")
    return 1 if bad else 0


def debug_report(
    orchestrator: Any, recorder: RecordingProvider, question: str, answer: Any
) -> None:
    section("1. Routing — which source, and why")
    for sid, source in orchestrator.sources.items():
        cand = score_source(question, source.profile)
        mark = "  <- chosen" if sid == answer.datasource else ""
        print(f"  {sid:<14} score {cand.score:6.1f}{mark}")
        for reason in cand.reasons[:4]:
            print(f"  {'':<14}   {reason}")
    if not answer.datasource:
        print("  no source chosen — scores below the floor, or two too close to call")

    if answer.datasource:
        section(f"2. Tables considered in {answer.datasource}")
        # The same set the orchestrator ranked from: this source's base tables.
        entitled = {
            t.fqn
            for t in orchestrator.graph.tables()
            if t.datasource == answer.datasource and not t.is_view
        }
        source = orchestrator.sources[answer.datasource]
        for c in orchestrator.candidates_for(question, source, entitled)[:6]:
            chosen = "  <- used" if c.fqn in answer.tables else ""
            print(f"  {c.score:6.1f}  {c.fqn}{chosen}")
            for reason in c.reasons[:3]:
                print(f"           {reason}")

    if not recorder.calls:
        section("3. Model — not called")
        print("  The turn was answered or refused before the model was needed.")
    for i, (system, user, completion, error) in enumerate(recorder.calls, 1):
        section(f"3.{i} What the model was sent (the schema cards are in here)")
        print(textwrap.indent(user, "  "))
        section(f"4.{i} What the model replied")
        if completion is None:
            print(f"  call FAILED: {error}")
        else:
            print(
                f"  stop reason {completion.stop_reason or '?'} · latency {completion.ms} ms · "
                f"tokens in {completion.input_tokens} / out {completion.output_tokens}"
            )
            if completion.truncated:
                print("  ! TRUNCATED — raise BQ_LLM_MAX_TOKENS")
            print(textwrap.indent(completion.text.strip() or "(empty)", "  "))


def show(answer: Any) -> None:
    section("Answer")
    print(f"  source   {answer.datasource or '-'}")
    print(f"  scenario {answer.scenario}")
    if answer.sql:
        print(f"  sql      {answer.sql}")
    if answer.error:
        print(f"  error    {answer.error.get('kind', '')}: {answer.error.get('technical', '')}")
    if answer.columns:
        print(f"  columns  {answer.columns}")
        for row in answer.rows[:10]:
            print(f"           {row}")
        if len(answer.rows) > 10:
            print(f"           … {len(answer.rows) - 10} more")
    print(f"\n  {answer.text}\n")
    print(f"  {answer.ms} ms · {answer.llm_calls} model call(s)")


def main(argv: list[str] | None = None, provider: Any = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("question", nargs="?", help="the question to ask")
    ap.add_argument("--source", help="pin the question to one datasource id")
    ap.add_argument("--debug", action="store_true", help="show every stage")
    ap.add_argument("--check", action="store_true", help="report whether each source is ready")
    ap.add_argument(
        "--no-connect", action="store_true", help="with --check, skip opening a connection"
    )
    ap.add_argument(
        "--graph-from-neo4j",
        action="store_true",
        help="load the join graph from Neo4j at startup instead of the catalog files",
    )
    ap.add_argument("--config", type=Path, default=DEFAULT_SOURCES)
    ap.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    args = ap.parse_args(argv)

    if args.check:
        return check(args.config, args.catalog, connect_check=not args.no_connect)
    if not args.question:
        ap.error("ask a question, or pass --check")

    try:
        from beta_queries.agent.providers import LunaProvider

        recorder = RecordingProvider(provider or LunaProvider())
        orchestrator, report = build_orchestrator(
            args.config, args.catalog, provider=recorder, graph_from_neo4j=args.graph_from_neo4j
        )
    except (CatalogNotLoaded, RuntimeError) as exc:
        print(f"cannot start: {exc}", file=sys.stderr)
        return 1

    for sid, why in report.skipped.items():
        print(f"  (skipped {sid}: {why})")

    answer = orchestrator.ask(args.question, LOCAL_PRINCIPAL, datasource=args.source)
    if args.debug:
        print(f"  graph from {report.graph_source}; sources ready: {', '.join(report.ready)}")
        debug_report(orchestrator, recorder, args.question, answer)
    show(answer)
    return 0 if answer.error is None else 2


if __name__ == "__main__":
    sys.exit(main())
