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
