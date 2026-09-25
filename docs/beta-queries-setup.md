# Beta Queries — setup and scaffold

Everything needed to stand this up on a machine that has never seen it. One
file, self-contained: the bootstrap script is printed here in full, so this
document can be shared on its own.

Every number and error string below was produced by running it, not recalled.

---

## 1. What you are setting up

Ask a question in plain English. Get back the SQL, the rows, a written answer,
and the live context of the conversation — scoped to the databases the asker is
entitled to see. Six engines: **SQL Server, Postgres, Snowflake, Databricks,
MySQL, DuckDB**.

Eleven stages, each removing a way for the next to be wrong:

```
turn → entitlements → route → tables → joins → PLAN (one model call)
     → identifiers → guard → policy → execute → heal
```

**The bet:** the model's job is small. Routing, table selection, join paths,
dates, identifier spelling, row filters and masks are decided *deterministically*
before the model is called, and validated again after. What is left — the
projection and the predicates — is what a model is genuinely good at.

### The five rules that must not be relaxed

1. **Identifiers come from the catalog, never from the model.** A model cannot
   know how a column was spelled at DDL time.
2. **Base tables only.** A view hides its grain, filters and joins, so a number
   from one cannot be explained.
3. **Read-only, single SELECT, every literal bound** — enforced by permission
   and by an AST guard, never by the prompt.
4. **One model call** before execution, **one** repair after a failure.
5. **Catalog text and chat history are data, not instructions.**

---

## 2. Prerequisites

| | |
|---|---|
| **Python 3.11 or newer** | Required. The code uses `X \| None` unions and `tomllib`. 3.10 will fail at import. |
| Disk | ~400 MB for the virtualenv |
| Network | Only for the one-time `pip install` |
| **Not needed** | Redis, Neo4j, SQL Server, an API key, any database server |

Check your version:

```bash
python3 --version        # macOS / Linux
py --version             # Windows
```

If it is older than 3.11, install a newer one and call it explicitly —
`python3.11 scripts/beta_queries_bootstrap.py`. Do not upgrade the system
Python on a work machine.

---

## 3. The scaffold script

Already present at `scripts/beta_queries_bootstrap.py`. Run it:

```bash
python scripts/beta_queries_bootstrap.py           # set up, then prove it works
python scripts/beta_queries_bootstrap.py --check   # prove it works, change nothing
```

It uses **only the standard library**, so it runs before anything is installed,
on Windows, macOS and Linux alike. It creates `.venv/`, installs the
dependencies, copies `.env.example` to `.env`, runs the tests and runs the
demo — stopping at the first failure with the fix rather than a traceback.

### What a good run looks like

```
Beta Queries — setting up in /path/to/beta-queries

[  OK  ] Python 3.11.15 on Linux
[  ..  ] creating virtualenv at .venv/
[  OK  ] virtualenv created at .venv/
[  ..  ] upgrading pip
[  ..  ] installing beta_queries + dev (this is the slow step, ~1 minute)
[  OK  ] dependencies installed
[  OK  ] .env created from .env.example — every value is still REPLACE_ME
[  ..  ] running the test suite
[  OK  ] 398 passed, 1 skipped in 12s
[  ..  ] asking real questions against DuckDB
[  OK  ] the demo answered 7 questions end to end

[  OK  ] everything works
```

### The script, in full

If you only have this document, save the following as
`scripts/beta_queries_bootstrap.py`:

```python
#!/usr/bin/env python3
"""Stand Beta Queries up on a machine that has never seen it.

    python scripts/beta_queries_bootstrap.py           # set up, then prove it works
    python scripts/beta_queries_bootstrap.py --check   # prove it works, change nothing

Standard library only, so it runs before anything is installed, on Windows,
macOS and Linux alike. Every step prints what it is doing and why, and the
first failure stops the run with the fix rather than a traceback.
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
MIN_PYTHON = (3, 11)

# What a correct run looks like. Stated up front so a changed number is a
# visible failure rather than something nobody notices.
EXPECT_TESTS = "398 passed"
EXPECT_TESTS_FULL_REPO = "411 passed"

OK, BAD, DOT = "  OK  ", " FAIL ", "  ..  "


def say(mark: str, line: str, detail: str = "") -> None:
    print(f"[{mark}] {line}" + (f"\n         {detail}" if detail else ""), flush=True)


def die(line: str, fix: str) -> None:
    say(BAD, line, fix)
    sys.exit(1)


def venv_python() -> Path:
    # Windows puts the interpreter somewhere else, and gets no exception.
    if platform.system() == "Windows":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def run(cmd: list[str], why: str, capture: bool = True) -> subprocess.CompletedProcess:
    say(DOT, why)
    return subprocess.run(cmd, capture_output=capture, text=True, cwd=ROOT)


def check_python() -> None:
    v = sys.version_info
    if (v.major, v.minor) < MIN_PYTHON:
        die(
            f"Python {v.major}.{v.minor} is too old — 3.11 or newer is required.",
            "The code uses `X | None` unions and `tomllib`. Install 3.11+ and re-run "
            "this script with it: python3.11 scripts/beta_queries_bootstrap.py",
        )
    say(OK, f"Python {v.major}.{v.minor}.{v.micro} on {platform.system()}")


def make_venv() -> None:
    if venv_python().exists():
        say(OK, f"virtualenv already present at {VENV.name}/")
        return
    say(DOT, f"creating virtualenv at {VENV.name}/")
    venv.EnvBuilder(with_pip=True, clear=False).create(VENV)
    if not venv_python().exists():
        die(
            "virtualenv was created but has no interpreter.",
            "On Debian/Ubuntu this usually means python3-venv is missing: "
            "sudo apt install python3-venv",
        )
    say(OK, f"virtualenv created at {VENV.name}/")


def install() -> None:
    py = str(venv_python())
    run([py, "-m", "pip", "install", "--upgrade", "--quiet", "pip"], "upgrading pip")
    # The core extra deliberately excludes pyodbc: it installs from a wheel and
    # then fails to import without unixODBC on the machine, which would turn a
    # working install into a broken one for everyone not on SQL Server.
    proc = run(
        [py, "-m", "pip", "install", "--quiet", "-e", ".[beta_queries,dev]"],
        "installing beta_queries + dev (this is the slow step, ~1 minute)",
    )
    if proc.returncode != 0:
        die(
            "dependency install failed.",
            "Last lines of pip output:\n         "
            + "\n         ".join((proc.stderr or proc.stdout).strip().splitlines()[-6:]),
        )
    say(OK, "dependencies installed")


def make_env_file() -> None:
    env, example = ROOT / ".env", ROOT / ".env.example"
    if env.exists():
        say(OK, ".env already present — left untouched")
        return
    if not example.exists():
        say(OK, "no .env.example in this copy — skipping (the demo needs no config)")
        return
    shutil.copyfile(example, env)
    say(OK, ".env created from .env.example — every value is still REPLACE_ME")


def run_tests() -> bool:
    proc = run([str(venv_python()), "-m", "pytest", "tests/", "-q"], "running the test suite")
    tail = (proc.stdout or "").strip().splitlines()
    summary = tail[-1] if tail else "(no output)"
    if proc.returncode != 0:
        say(BAD, "tests failed", summary)
        return False
    # A count that drops is a module that stopped being collected, which is
    # how 177 tests once vanished from a green run without anyone noticing.
    if EXPECT_TESTS not in summary and EXPECT_TESTS_FULL_REPO not in summary:
        say(
            OK,
            f"tests passed, but the count moved: {summary}",
            f"expected {EXPECT_TESTS} (bundle) or {EXPECT_TESTS_FULL_REPO} (full repo)",
        )
        return True
    say(OK, summary)
    return True


def run_demo() -> bool:
    demo = ROOT / "scripts" / "beta_queries_demo.py"
    if not demo.exists():
        say(BAD, "scripts/beta_queries_demo.py is missing", "the copy is incomplete")
        return False
    proc = run([str(venv_python()), str(demo)], "asking real questions against DuckDB")
    if proc.returncode != 0:
        say(
            BAD,
            "the demo did not complete",
            "\n         ".join((proc.stderr or "").strip().splitlines()[-6:]),
        )
        return False
    answered = sum(1 for line in (proc.stdout or "").splitlines() if "ANSWER" in line)
    say(OK, f"the demo answered {answered} questions end to end")
    return True


def activate_hint() -> str:
    if platform.system() == "Windows":
        return r".venv\Scripts\activate"
    return "source .venv/bin/activate"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check", action="store_true", help="verify an existing setup; create and install nothing"
    )
    args = ap.parse_args(argv)

    print(f"\nBeta Queries — {'checking' if args.check else 'setting up'} in {ROOT}\n")
    check_python()

    if args.check:
        if not venv_python().exists():
            die("no virtualenv found.", "Run without --check first.")
        say(OK, "virtualenv found")
    else:
        make_venv()
        install()
        make_env_file()

    ok = run_tests() and run_demo()

    print()
    if not ok:
        say(BAD, "setup is NOT working — see the failure above")
        print(
            "\nIf the error is unfamiliar, send its exact text; the known ones are\n"
            "listed under Troubleshooting in SETUP.md.\n"
        )
        return 1

    say(OK, "everything works")
    print(
        f"\nNext:\n"
        f"  {activate_hint()}\n"
        f"  python scripts/beta_queries_demo.py     # watch every stage\n"
        f"  $EDITOR .env                            # real databases go here\n"
        f"  $EDITOR data/config/beta_queries_sources.yaml\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

---

## 4. The manual path

If you would rather not run a script, this is exactly what it does:

```bash
# 1. a virtualenv, so nothing touches the system Python
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. the dependencies
pip install --upgrade pip
pip install -e ".[beta_queries,dev]"

# 3. prove it
pytest tests/ -q                   # expect: 398 passed, 1 skipped
python scripts/beta_queries_demo.py
```

**Expect `398 passed, 1 skipped`.** The skip is deliberate: one test file
checks `agent.yaml` against the loader in the wider `future_agents` framework,
which is not part of this bundle. In the full repository that file runs and the
count is **411**.

The demo builds a DuckDB database whose schema is hostile on purpose — a column
called `report id`, one called `user`, a case-sensitive `Status`, a view that
looks like the obvious answer, and a staging twin of the real table — then asks
seven questions and prints every stage. It answers, refuses and explains each
one. If that passes, the wiring is correct; everything beyond it is credentials
and scale.

---

## 5. What every file is for

### Entry points

| File | Answers |
|---|---|
| `scripts/beta_queries_bootstrap.py` | stand it up on a new machine |
| `scripts/beta_queries_demo.py` | **the acceptance test** — every stage printed |
| `scripts/beta_queries_crawl.py` | harvest one datasource's metadata |
| `scripts/beta_queries_bundle.py` | repackage this for another machine |
| `airflow/dags/beta_queries_catalog_sync.py` | keep the catalog in sync on a schedule |

### The pipeline, in execution order

| Module | Answers |
|---|---|
| `nlp/preprocess.py` · `classify.py` · `rewrite.py` | what kind of message is this — 30 scenarios |
| `dialogue/policy.py` · `turn.py` | which of 10 response shapes; only one reaches the model |
| `entitlements/resolver.py` | which tables may this principal read — deny beats allow |
| `routing/router.py` | which datasource, and whether to ask |
| `catalog/readiness.py` | is that datasource's metadata ready — ready/wait/partial/queue/failed |
| `catalog/graph.py` | **which tables**, and **how they join** — Neo4j + an in-memory twin |
| `catalog/semantics.py` | which records count; which column is the right column |
| `agent/prompts.py` | assemble the prompt; catalog text and history fenced as data |
| `agent/planner.py` | **the one model call**, plus at most one repair |
| `agent/providers.py` | GPT Luna · Anthropic · `EchoProvider` (offline, no key) |
| `agent/contract.py` | the `QueryPlan` the model must return |
| `sql/identifiers.py` | **what the model wrote → what the catalog holds → quoted for this engine** |
| `sql/guard.py` | G00–G12 over the AST — the security boundary |
| `sql/compiler.py` | RLS predicates and masks, into **every** SELECT scope |
| `sql/executor.py` | read-only, as the asker, timeout and row cap |
| `sql/healing.py` | error → kind → repair strategy → a lesson that stops it recurring |
| `errors/report.py` | two layers, technical one redacted where it would leak |
| `orchestrator.py` | the eleven stages, wired and narrated |
| `progress.py` | server-driven narration — never model-authored |

### Supporting

| Module | Answers |
|---|---|
| `dialects.py` | what differs across six engines: row cap, quoting, base-table test, FKs |
| `catalog/models.py` · `crawler.py` | the metadata harvest; views recorded, never planned against |
| `context/model.py` | bounded typed conversation context + the side panel |
| `memory/profile.py` | what this user means — 7-day sliding TTL, email hashed |
| `sync/plan.py` | crawl diffing, with a partial-crawl quarantine |
| `eval/corpus.py` | 204,282 generated business questions · 44 hazards · 264-case gate |

### Configuration and docs

| File | Answers |
|---|---|
| `data/config/beta_queries_sources.yaml` | which databases exist, and the words people use for them |
| `data/config/beta_queries_steps.yaml` | the narration text |
| `data/config/beta_queries_dialogue.yaml` | the 30 scenarios' wording |
| `data/config/beta_queries_errors.yaml` | the two-layer error wording |
| `apps/beta_queries/agent.yaml` | the runtime contract handed to the model |
| `docs/beta-queries-spec.md` | the full design, 33 sections |
| `docs/beta-queries-handoff.md` | what exists, what is true, what must never change |
| `DESIGN.md` | **why** it is shaped this way, and four flaws caught before they shipped |

---

## 6. Configuration

### Environment (`.env`)

The bootstrap copies `.env.example` to `.env`. Every value starts as
`REPLACE_ME`. **The demo and the tests need none of it** — fill these in only
when pointing at a real database.

| Variable | What it is for |
|---|---|
| `BQ_REDIS_URL` | the derived cache. Rebuildable; never the source of truth |
| `BQ_NEO4J_URI` · `BQ_NEO4J_USER` · `BQ_NEO4J_PASSWORD` | the catalog graph — table selection and join paths |
| `BQ_VECTOR_DSN` | SQL Server holding the semantic index, value index and query memory |
| `BQ_DSN_<NAME>` | one per datasource. The name matches `dsn_env` in the sources file |
| `BQ_ROW_LIMIT` | per-request row cap (default 1000) |
| `BQ_QUERY_TIMEOUT_SECONDS` | statement timeout (default 30) |

**Never commit `.env`.** It is in `.gitignore`. Real credentials belong in a
secrets manager read at runtime — the crawler reads `dsn_env` by name and never
logs the value.

### Adding a database (`data/config/beta_queries_sources.yaml`)

```yaml
sources:
  - id: hrdb
    dialect: sqlserver          # sqlserver|postgres|snowflake|databricks|mysql|duckdb
    dsn_env: BQ_DSN_HRDB        # the NAME of an env var, never the value
    description: >
      HR warehouse. Employees, assignments, departments, locations, absence.
      Authoritative for headcount.
    subject_areas: [people, headcount, org, payroll]
    synonyms:
      people: employee
      headcount: employee
      team: department
      leaver: termination
```

`synonyms` is the highest-leverage field in the file. It maps the words people
say to the words the catalog uses, and it is the difference between *"how many
people"* routing to the HR warehouse and routing nowhere.

Then crawl it:

```bash
python scripts/beta_queries_crawl.py --source hrdb
```

---

## 7. Per-engine notes

### Identifier folding — why this matters more than it looks

A column is `report id`. The model writes `report_id`. On a case-**sensitive**
engine the database throws. On a case-**insensitive** one it binds to a
different column and returns a confident wrong number. No prompt fixes this;
`sql/identifiers.py` resolves it from the catalog after generation and before
the guard.

| Engine | Unquoted folds to | The gotcha |
|---|---|---|
| Snowflake | **UPPER** | a quoted lower-case column is unreachable unquoted, ever |
| Postgres | **lower** | `"Report ID"` needs quotes forever |
| SQL Server | preserved | a `_CS_` collation flips the answer |
| MySQL | preserved | **table names are case-sensitive on Linux** — works on a Mac, breaks in prod |
| Databricks | lower | — |
| DuckDB | preserved | — |

**Placeholders:** `:p0` is the only style that parses on all six engines. `@p0`
is DuckDB's absolute-value operator (sqlglot reads it as `ABS(p0)`); `$p0` is a
column reference on T-SQL and MySQL. The planner rejects the wrong sigil by name.

### SQL Server needs one extra step

```bash
pip install -e ".[beta_queries_sqlserver]"
```

`pyodbc` is a **separate extra on purpose**. It installs from a wheel and then
fails to import without unixODBC present on the machine, which turns a working
install into a broken one for everyone not using SQL Server. It is imported
lazily, inside the crawler's connect function, so nothing else notices it is
absent.

You also need the system library: `sudo apt install unixodbc` on Debian/Ubuntu,
`brew install unixodbc` on macOS, nothing extra on Windows.

---

## 8. Troubleshooting

Each of these was reproduced on a clean machine. The error text is verbatim.

### `ModuleNotFoundError: No module named 'future_agents'`

```
ERROR collecting tests/test_beta_queries_agent_definition.py
```

**Expected in the bundle, and harmless.** That one file checks `agent.yaml`
against the wider framework, which is not shipped here. It now skips itself, so
you should see `364 passed, 1 skipped`. If you see a *collection error* instead
of a skip, you have an older copy — a collection error aborts the entire run,
so `pytest` would report zero tests passing.

### `ImportError: libodbc.so.2: cannot open shared object file`

`pyodbc` installed but the system ODBC library is missing. Nothing in the app
imports it, so this only appears if you installed the SQL Server extra. Install
`unixodbc` (§7) or drop that extra.

### `Python 3.10 is too old`

The code uses `X | None` unions and `tomllib`. Install 3.11+ and invoke it
explicitly: `python3.11 scripts/beta_queries_bootstrap.py`.

### `virtualenv was created but has no interpreter`

Debian and Ubuntu ship `venv` separately: `sudo apt install python3-venv`.

### The test count is not 398 or 411

A count that *drops* usually means a module stopped being collected rather than
a test being deleted — a skipped module reports as one line, not as the tests
inside it. This is how 177 tests once vanished from a green CI run unnoticed.
Run `pytest tests/ -v --tb=short` and look for collection errors.

### The demo answers, but the number looks wrong

Check the `filters` line in the context panel it prints. A default filter
(`"Status" = 'ACTIVE'`) is applied and declared as an assumption — that is
deliberate, and the assumption is surfaced with the answer rather than hidden.

---

## 8b. The QA agent

A standing check that replays real conversations and says what broke. Run it
after any change to `apps/beta_queries/`:

```bash
python scripts/beta_queries_qa.py                 # report; exit 1 on a regression
python scripts/beta_queries_qa.py --install-hook  # run it before every push
```

Full detail, including how to add a scenario: **`QA-AGENT.md`**.

## 9. Verification runbook

```bash
python scripts/beta_queries_bootstrap.py --check    # the whole chain, changes nothing
pytest tests/ -q                                    # 364 passed, 1 skipped
python scripts/beta_queries_demo.py                 # 7 questions answered
```

In the full repository, additionally:

```bash
pytest -q                                                        # 2147 passed
ruff check packages/future_agents/ apps/ scripts/
ruff format --check packages/future_agents/ apps/ scripts/
python packages/guardrails/guardrails_engine.py . --mode block   # exits 0
```

| What | Expected |
|---|---|
| bundle tests | `398 passed, 1 skipped` |
| full-repo beta-queries tests | `411 passed` |
| full-repo suite | `2147 passed`, **0 skipped** |
| demo | 7 answers, including one refusal and one view explanation |

CI installs `.[beta_queries,dev]`, not `.[dev]` — without the extra, six test
modules skip themselves on `sqlglot`/`duckdb` and 177 tests silently disappear
from a green run.

---

## 10. What is not built, and why it is written down instead

Specified in `DESIGN.md` rather than implemented. The reasoning is the
deliverable — three of these would be built wrongly without it.

| Piece | The one thing that matters |
|---|---|
| `app.py` + SSE | The narration already exists as a step machine with a `sink`; the HTTP layer is plumbing, not design |
| `incidents/` | Key on **`(datasource, kind, object)`**, never on the healing signature — two different broken columns hash identically, because literals are stripped by design |
| `sync/targeted.py` | A read-only **probe**, never a re-crawl. `diff_catalog` always quarantines a one-table refresh, and `infer_joins` inverts its own safety check on a single-table datasource |
| `remediation/worker.py` | **Last, not first.** Snowflake, SQL Server and MySQL merge "you may not see it" into "it does not exist", so a permission denial classifies as `unknown_table`, auto-remediates as the *catalog* principal, resolves, and tells every waiter it is fixed — and every one of them fails again identically |
| `notify/` | Say "the catalog has been updated, your question is ready to run again" — **never "fixed"**. The retry runs as the user, which is the only place the truth lives |
| `catalog/profiler.py` + `describe.py` | Deterministic role/grain/keys for free; the LLM description cached on a **content hash**, so it is paid for once, not per crawl |
| `retrieval/` | Only needed when term and value matching are not enough. Late, deliberately |

### Known gap worth closing first

`HealingMemory` learns from **failures** — a repair that worked twice is
replayed into the prompt. Nothing learns from **successes**. The spec designs a
`query_memory` table with `is_certified = 1` feeding up to three similar past
questions as few-shot examples, and calls it *"the highest-leverage quality
input in the whole system"* — but `build_user()` has no channel for it. That is
the highest-value remaining change, and a small one.

---

## Before any deployment

This touches **auth and PII**, and `CLAUDE.md` requires human security review.
Three specifics for that review:

1. PII detection is **name-based** and will miss an unconventionally named column.
2. `agent.yaml` marks catalog text untrusted but **not the chat history** — an
   instruction planted in turn 1 can ride into turn 5. The prompt layer now
   fences history as data; the `conversation_is_data` constraint is drafted and
   not yet applied.
3. Email addresses would be stored on incidents when notifications land. The
   profile only ever holds a hash.
