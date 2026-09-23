# Beta Queries — the QA agent

A standing check that replays real conversations against the pipeline and says
what broke. Run it after any change to `apps/beta_queries/`, or let the git
hook run it for you before every push.

It runs entirely offline — DuckDB as the engine, an in-memory graph and KV, a
canned provider — so it needs no key, no server and no network, and gives the
same answer on every machine.

---

## 1. Why conversations and not questions

The regression that prompted this file was **invisible one question at a
time.** Every turn passed on its own; the chain between them was broken.

Asking "how many people are in India", then "and in Germany?", the second turn
routed to `out_of_scope`. The orchestrator recorded no metric and none of the
user's filters, so the follow-up was rebuilt as *"how many records — now for
Germany"* — a question with no subject in it. 377 tests were green throughout,
because the conversation layer was tested with a context populated by hand and
the orchestrator was tested one turn at a time. **Nobody tested the seam.**

A suite of isolated questions would not have found it, and will not find the
next one.

## 2. Running it

```bash
python scripts/beta_queries_qa.py                 # report; exit 1 on a regression
python scripts/beta_queries_qa.py -v              # show every turn, passing or not
python scripts/beta_queries_qa.py --install-hook  # run it before every push
```

A clean run:

```
QA agent: nothing broken.
  11/11 conversation turns behaved as expected.
```

A regression names the conversation, **the turn number**, the question, and
expected against actual:

```
QA agent: 8 problem(s) in 4 conversation(s).

  a follow-up keeps the subject
    turn 1 — "how many people are in india"
      ctx_metric: expected any metric recorded
                 actual   none
    turn 2 — "and in Germany?"
      scenario: expected pivot
                 actual   out_of_scope
```

The turn number is the point. A failure in turn 3 of a 4-turn conversation that
only says "conversation failed" is not actionable.

## 3. The pre-push hook

```bash
python scripts/beta_queries_qa.py --install-hook
```

Writes `.git/hooks/pre-push`, refusing to overwrite an existing hook without
`--force`. The push is blocked on a regression; `git push --no-verify` bypasses
it when you mean to.

## 4. Adding a scenario

Scenarios live in `data/config/beta_queries_qa_scenarios.yaml` — data, not
code, matching `beta_queries_{steps,dialogue,errors}.yaml`. Each turn's
`expect` block is checked against what the pipeline produced; **absent keys are
not checked**, so state what matters rather than everything.

| Key | Checks |
|---|---|
| `scenario` | exact match on the classified scenario |
| `answer_contains` | substring of the written answer |
| `sql_contains` | every string must appear in the generated SQL |
| `sql_not_contains` | none of these may appear |
| `ctx_filter` | `{column: value}` must be in the context (`null` = any value) |
| `ctx_no_filter` | column must **not** be in the context — the disclosure guard |
| `ctx_metric` | the context recorded a metric |

```yaml
scenarios:
  - name: a follow-up keeps the subject
    why: >
      The orchestrator once recorded no metric and no filters, so every
      follow-up rebuilt a question with no subject and routed nowhere.
    turns:
      - ask: how many people are in india
        expect:
          scenario: new_topic
          answer_contains: "2"
          ctx_metric: true
          ctx_filter: {country_name: India}
      - ask: "and in Germany?"
        expect:
          scenario: pivot
          ctx_filter: {country_name: null}

  - name: row-level security never becomes a chip
    why: >
      An RLS predicate shown as a removable chip discloses a filter the asker
      was never told about, and invites asking to remove it.
    turns:
      - ask: how many people are in india
        expect:
          ctx_filter: {country_name: India}
          ctx_no_filter: [region]
```

Include a `why:` on every scenario. A failing check whose reason nobody
remembers gets deleted rather than fixed.

## 5. What it currently guards

| Conversation | What would break without it |
|---|---|
| a follow-up keeps the subject | the seam bug above — the whole reason this exists |
| row-level security never becomes a chip | an RLS predicate shown as a removable chip discloses a filter the asker was never told about, and `rewrite()` would honour a request to drop it |
| narrowing keeps the standing filters | "add a filter for active only" losing the question it was narrowing |
| a period is not a value swap | "what about last year" asking for `country_name = 'last year'` |
| the reported identifier bug | `report id` written as `report_id`, binding to a different column on a case-insensitive engine |
| a view is refused by name | a number nobody can explain |
| writes are refused | read-only enforced by permission and the guard, never the prompt |
| a greeting never reaches the model | the latency budget — nine of ten response modes never call the model |

## 6. It refuses to pass silently

A scenario file that fails to load, or that contains no scenarios, **exits
non-zero** rather than reporting "0 failures".

This is not hypothetical. Earlier on this branch, CI installed the wrong
dependency extra, six test modules skipped themselves at import, and **177
tests vanished from a green run** — a skipped module reports as one line, not
as the tests inside it. A checker that cannot distinguish "everything passed"
from "nothing ran" is worse than no checker.

## 7. The runner, in full

Shipped at `scripts/beta_queries_qa.py`. Printed here so this document stands
alone; a test asserts the two are byte-identical, so this copy cannot drift.

```python
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
```
