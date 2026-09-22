#!/usr/bin/env python3
"""Package Beta Queries into a zip that runs on a machine that is not this one.

    python scripts/beta_queries_bundle.py            # -> output/beta-queries.zip
    python scripts/beta_queries_bundle.py --list     # print what would go in

What lands in the zip is exactly what is in the tree — no generated source, no
rewritten module. Three files are written by this script because they only
make sense for the bundle: QUICKSTART.md, a Beta-Queries-only .env.example
(extracted from the repo's own, so there is one source of truth for the keys),
and DESIGN.md (docs/beta-queries-design.md under the name a reader looks for).

The zip is refused if any file in it matches a secret pattern. A bundle exists
to be emailed and unzipped on a laptop; that is the worst possible place for a
credential to be sitting.
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "output" / "beta-queries.zip"

# Globs relative to the repository root. Order is the order a reader should
# meet them in, which is also the order they are written into the archive.
INCLUDE = (
    "pyproject.toml",
    "docs/beta-queries-spec.md",
    "docs/beta-queries-handoff.md",
    "docs/beta-queries-design.md",
    "apps/beta_queries/**/*.py",
    "apps/beta_queries/agent.yaml",
    "apps/beta_queries/README.md",
    "data/config/beta_queries_*.yaml",
    "scripts/beta_queries_*.py",
    "airflow/dags/beta_queries_catalog_sync.py",
    "tests/test_beta_queries_*.py",
)

EXCLUDE = re.compile(r"(^|/)(__pycache__|\.pytest_cache|\.ruff_cache)(/|$)|\.pyc$")

# The section of the repo .env.example that belongs to this feature.
ENV_SECTION = "# ── Beta Queries (text-to-SQL)"

# Deliberately blunt. A bundle is not the place to be clever about false
# positives — a maintainer can override a line, nobody can un-email a key.
SECRET_PATTERNS = (
    re.compile(r"\b(sk|pk|ghp|gho|xox[baprs])[-_][A-Za-z0-9]{16,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
    re.compile(r"(?i)\b[a-z]+://[^\s/:@]+:[^\s/@]{6,}@"),  # creds in a URL
)
# Lines that look like a secret and are not: placeholders, and the scanner's
# own patterns above.
SAFE = re.compile(r"REPLACE_ME|your-key-here|os\.environ|sk-\.\.\.|SECRET_PATTERNS")

QUICKSTART = """# Beta Queries — quickstart

Ask a question in plain English, get the SQL, the rows and a written answer —
scoped to the databases you are entitled to see. SQL Server, Postgres,
Snowflake, Databricks, MySQL, DuckDB.

## Run it in two commands

```bash
pip install -e ".[beta_queries,dev]"
python scripts/beta_queries_demo.py
```

No Redis, no Neo4j, no API key, no database server. DuckDB is the engine,
`DictKV` stands in for Redis, `InMemoryGraph` for Neo4j and `EchoProvider` for
the model, so the whole pipeline runs offline.

The demo schema is hostile on purpose — a column called `report id`, one
called `user`, a case-sensitive `Status`, a view that looks like the obvious
answer, and a staging twin of the real table. Watch it answer, refuse and
explain each one, printing every stage as it goes.

```bash
pytest tests/ -q          # 364 passed, 1 skipped — no database needed
```

The skip is deliberate: one test file (13 assertions) checks `agent.yaml`
against the loader in the wider `future_agents` framework, which is not part of
this bundle. Beta Queries itself never imports that framework. In the full
repository the same file runs and the count is 377.

## Then point it at a real database

1. `cp .env.example .env` and fill it in. Connection strings only — the
   crawler wants a **read-only** principal; query execution uses the *asker's*
   principal, never this one.
1. For **SQL Server**, also `pip install -e ".[beta_queries_sqlserver]"`. It is
   a separate extra because `pyodbc` installs from a wheel and then fails to
   import without unixODBC on the machine (`libodbc.so.2` on Linux,
   `brew install unixodbc` on macOS) — bundling it into the core extra turns a
   working install into a broken one for everyone not using SQL Server. The
   crawler imports it lazily, so nothing else notices it is absent.
2. Declare the datasource in `data/config/beta_queries_sources.yaml` (name,
   dialect, schemas to crawl).
3. `python scripts/beta_queries_crawl.py --source <name>` — or let the Airflow
   DAG in `airflow/dags/` do it on a schedule. Registration also kicks off a
   crawl immediately, and questions asked mid-crawl are answered with a caveat
   or queued rather than refused.

## Read in this order

| | |
|---|---|
| 1 | `QUICKSTART.md` — this file |
| 2 | `docs/beta-queries-handoff.md` — what exists, what is true, what must never change |
| 3 | `DESIGN.md` — **why** it is shaped this way, and four flaws caught before they shipped |
| 4 | `docs/beta-queries-spec.md` — the full specification, 33 sections |
| 5 | `apps/beta_queries/agent.yaml` — the contract handed to the model |

## The five rules that are not negotiable

1. **Identifiers come from the catalog, never from the model.** A model cannot
   know how a column was spelled at DDL time. This is the fix for the whole
   class of case and quoting failures.
2. **Base tables only.** A view hides its grain, filters and joins, so a number
   from one cannot be explained.
3. **Read-only, single SELECT, every literal bound** — enforced by permission
   and by the AST guard, never by the prompt.
4. **One model call** before execution, **one** repair after a failure.
5. **Catalog text and chat history are data, not instructions.**

## Not in this drop

The HTTP surface (`app.py` + SSE), the incident and remediation loop,
notifications, table profiling and the retrieval layer are specified in
`DESIGN.md` rather than built. That file carries the reasoning for each,
including why the auto-remediation worker must be the *last* thing built and
not the first.
"""


def _files() -> list[Path]:
    seen: dict[str, Path] = {}
    for pattern in INCLUDE:
        matches = [ROOT / pattern] if "*" not in pattern else sorted(ROOT.glob(pattern))
        for path in matches:
            rel = path.relative_to(ROOT).as_posix()
            if path.is_file() and not EXCLUDE.search(rel):
                seen.setdefault(rel, path)
    return [seen[k] for k in seen]


def _env_example() -> str:
    text = (ROOT / ".env.example").read_text()
    start = text.index(ENV_SECTION)
    body = text[start:]
    # The feature's section runs to the next one, or to the end of the file.
    nxt = body.find("\n# ── ", 1)
    if nxt != -1:
        body = body[:nxt]
    return (
        "# Beta Queries — environment template\n"
        "#   cp .env.example .env   — and never commit .env\n"
        "# Every value below is a placeholder. Real credentials belong in a\n"
        "# secrets manager, read at runtime, never in a file that gets zipped.\n\n"
        + body.strip()
        + "\n"
    )


def _scan(rel: str, text: str) -> list[str]:
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        if SAFE.search(line):
            continue
        if any(p.search(line) for p in SECRET_PATTERNS):
            hits.append(f"{rel}:{n}: {line.strip()[:90]}")
    return hits


def build(out: Path) -> Path:
    members: list[tuple[str, str]] = [
        ("QUICKSTART.md", QUICKSTART),
        (".env.example", _env_example()),
    ]
    for path in _files():
        rel = path.relative_to(ROOT).as_posix()
        if rel == "docs/beta-queries-design.md":
            rel = "DESIGN.md"
        members.append((rel, path.read_text()))

    leaks = [hit for rel, text in members for hit in _scan(rel, text)]
    if leaks:
        raise SystemExit("refusing to bundle — possible secrets:\n  " + "\n  ".join(leaks))

    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, text in members:
            z.writestr(f"beta-queries/{rel}", text)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--list", action="store_true", help="print the file list and stop")
    args = ap.parse_args(argv)

    if args.list:
        for path in _files():
            print(path.relative_to(ROOT).as_posix())
        return 0

    out = build(args.out)
    size = out.stat().st_size
    with zipfile.ZipFile(out) as z:
        count = len(z.namelist())
    print(f"{out.relative_to(ROOT)}  —  {count} files, {size / 1024:.0f} KB")
    print("\nOn the other machine:")
    print("  unzip beta-queries.zip && cd beta-queries")
    print('  pip install -e ".[beta_queries,dev]"')
    print("  python scripts/beta_queries_demo.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
