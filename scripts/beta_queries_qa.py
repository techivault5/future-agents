#!/usr/bin/env python3
"""The QA agent: replay real conversations, report what broke.

    python scripts/beta_queries_qa.py                 # report; exit 1 on a regression
    python scripts/beta_queries_qa.py --install-hook  # run it before every push
    python scripts/beta_queries_qa.py -v              # show every turn, passing or not

Runs entirely offline — DuckDB as the engine, an in-memory graph and KV, and a
canned provider — so it needs no key, no server and no network, and gives the
same answer on every machine.

It replays **conversations**, not isolated questions. The regression that
prompted this file was invisible one question at a time: each turn passed
alone, and the chain between them was broken.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / p) for p in ("apps", "packages", "scripts")]

SCENARIOS = ROOT / "data" / "config" / "beta_queries_qa_scenarios.yaml"

HOOK = """#!/bin/sh
# Beta Queries QA agent — installed by scripts/beta_queries_qa.py
# Bypass once with:  git push --no-verify
exec python "$(git rev-parse --show-toplevel)/scripts/beta_queries_qa.py"
"""


@dataclass
class Failure:
    scenario: str
    turn: int
    question: str
    check: str
    expected: str
    actual: str


@dataclass
class Report:
    passed: int = 0
    checks: int = 0
    failures: list[Failure] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def _chip(ctx, column):
    return next((c for c in ctx.filters if c.column == column), None)


def _check_turn(scenario: str, n: int, question: str, expect: dict, answer, ctx) -> list[Failure]:
    out: list[Failure] = []
    sql = answer.sql or ""

    def fail(check: str, expected, actual) -> None:
        out.append(Failure(scenario, n, question, check, str(expected), str(actual)))

    if "scenario" in expect and answer.scenario != expect["scenario"]:
        fail("scenario", expect["scenario"], answer.scenario)

    if "answer_contains" in expect:
        needle = str(expect["answer_contains"])
        if needle not in (answer.text or ""):
            fail("answer_contains", needle, (answer.text or "")[:80] or "(empty)")

    for needle in expect.get("sql_contains", []):
        if needle not in sql:
            fail("sql_contains", needle, sql[:80] or "(no sql)")

    for needle in expect.get("sql_not_contains", []):
        if needle in sql:
            fail("sql_not_contains", f"absent: {needle}", sql[:80])

    if expect.get("ctx_metric") and not ctx.metric:
        fail("ctx_metric", "any metric recorded", "none")

    for column, value in (expect.get("ctx_filter") or {}).items():
        chip = _chip(ctx, column)
        if chip is None:
            fail("ctx_filter", f"{column} present", "absent")
        elif value is not None and str(chip.value) != str(value):
            fail("ctx_filter", f"{column} = {value}", f"{column} = {chip.value}")

    for column in expect.get("ctx_no_filter", []):
        if _chip(ctx, column) is not None:
            fail("ctx_no_filter", f"{column} absent", "present")

    return out


def run(verbose: bool = False) -> Report:
    import yaml
    from beta_queries.context.model import ConversationContext

    try:
        import beta_queries_demo as demo
    except ImportError as exc:  # pragma: no cover - the bundle always ships it
        raise SystemExit(f"cannot import the demo harness: {exc}") from exc

    data = yaml.safe_load(SCENARIOS.read_text()) or {}
    scenarios = data.get("scenarios") or []
    # An empty suite that reports "0 failures" is how a green run stops meaning
    # anything. Refuse rather than pass.
    if not scenarios:
        raise SystemExit(f"no scenarios found in {SCENARIOS} — refusing to report a pass")

    import tempfile

    path = str(Path(tempfile.mkdtemp()) / "qa.duckdb")
    demo.build_database(path)
    orchestrator, _ = demo.build(path)

    report = Report()
    for scenario in scenarios:
        name = scenario.get("name", "(unnamed)")
        ctx = ConversationContext(session_id=f"qa:{name}")
        for n, turn in enumerate(scenario.get("turns", []), 1):
            question = turn.get("ask", "")
            expect = turn.get("expect") or {}
            answer = orchestrator.ask(question, demo.ME, ctx)
            failures = _check_turn(name, n, question, expect, answer, ctx)
            report.checks += 1
            if failures:
                report.failures.extend(failures)
            else:
                report.passed += 1
            if verbose:
                mark = "ok  " if not failures else "FAIL"
                print(f"  [{mark}] {name} · turn {n}: {question}")
    return report


def render(report: Report) -> str:
    if report.ok:
        return (
            f"\nQA agent: nothing broken.\n"
            f"  {report.passed}/{report.checks} conversation turns behaved as expected.\n"
        )

    by_scenario: dict[str, list[Failure]] = {}
    for f in report.failures:
        by_scenario.setdefault(f.scenario, []).append(f)

    lines = [
        f"\nQA agent: {len(report.failures)} problem(s) in {len(by_scenario)} conversation(s).\n"
    ]
    for name, failures in by_scenario.items():
        lines.append(f"  {name}")
        for f in failures:
            lines.append(f'    turn {f.turn} — "{f.question}"')
            lines.append(f"      {f.check}: expected {f.expected}")
            lines.append(f"                 actual   {f.actual}")
        lines.append("")
    lines.append(
        "  A turn that fails mid-conversation usually means the context stopped\n"
        "  carrying what the next turn needs — check what orchestrator.ask()\n"
        "  writes back after a successful turn.\n"
    )
    return "\n".join(lines)


def install_hook(force: bool = False) -> int:
    hooks = ROOT / ".git" / "hooks"
    if not hooks.is_dir():
        print(f"no {hooks} — is this a git checkout?", file=sys.stderr)
        return 1
    target = hooks / "pre-push"
    if target.exists() and not force:
        print(f"{target} already exists. Re-run with --force to replace it.", file=sys.stderr)
        return 1
    target.write_text(HOOK)
    target.chmod(0o755)
    print(f"installed {target}\nIt runs the QA agent before every push; bypass with --no-verify.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--install-hook", action="store_true", help="run this before every git push")
    ap.add_argument("--force", action="store_true", help="replace an existing pre-push hook")
    ap.add_argument("-v", "--verbose", action="store_true", help="show every turn")
    args = ap.parse_args(argv)

    if args.install_hook:
        return install_hook(args.force)

    report = run(verbose=args.verbose)
    print(render(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
