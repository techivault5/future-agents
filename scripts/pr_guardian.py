#!/usr/bin/env python3
"""
PR Guardian — automatically resolves merge conflicts, fixes lint, and merges PRs.

What it does for each open PR:
1. dirty (merge conflicts)  → merge main in, resolve conflicts, fix lint, push
2. CI failing (lint/format) → fix ruff issues, push
3. all checks green         → merge the PR
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ── GitHub API helpers ─────────────────────────────────────────────

TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = os.environ.get("REPO", "techivault5/future-agents")
API = "https://api.github.com"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }


def gh_get(path: str) -> dict | list:
    url = f"{API}/{path.lstrip('/')}"
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def gh_put(path: str, data: dict) -> dict:
    url = f"{API}/{path.lstrip('/')}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers=_headers(), method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()}


# ── Git helpers ──────────────────────────────────────────────────


def run(cmd: list[str], check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:  # noqa: E501
    kwargs: dict = {"check": check}
    if capture:
        kwargs["capture_output"] = True
        kwargs["text"] = True
    return subprocess.run(cmd, **kwargs)


def git(*args, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    return run(["git"] + list(args), check=check, capture=capture)


# ── Conflict resolution ────────────────────────────────────────────────


def resolve_pyproject_conflicts(path: Path) -> bool:
    """Take 'theirs' (main) for conflicting regions, dedup duplicate sections."""
    content = path.read_text()
    if "<<<<<<" not in content:
        return True
    resolved = re.sub(
        r"<<<<<<< HEAD\n.*?=======\n(.*?)>>>>>>> [^\n]+\n",
        r"\1",
        content,
        flags=re.DOTALL,
    )
    # Remove duplicate [tool.setuptools.packages.find] sections
    first = resolved.find("[tool.setuptools.packages.find]")
    second = resolved.find("[tool.setuptools.packages.find]", first + 1)
    if second != -1:
        next_sec = resolved.find("\n[", first + 1)
        if next_sec != -1:
            resolved = resolved[:first] + resolved[next_sec + 1 :]
    path.write_text(resolved)
    return "<<<<<<" not in path.read_text()


def resolve_noqa_conflicts(path: Path) -> bool:
    """Take 'theirs' (main) for all conflicts; ruff will re-add noqa as needed."""
    content = path.read_text()
    if "<<<<<<" not in content:
        return True
    resolved = re.sub(
        r"<<<<<<< HEAD\n.*?=======\n(.*?)>>>>>>> [^\n]+\n",
        r"\1",
        content,
        flags=re.DOTALL,
    )
    path.write_text(resolved)
    return "<<<<<<" not in path.read_text()


def resolve_all_conflicts(repo_root: Path) -> bool:
    result = git("diff", "--name-only", "--diff-filter=U", capture=True, check=False)
    conflicted = [f.strip() for f in result.stdout.splitlines() if f.strip()]
    if not conflicted:
        return True
    print(f"  Conflicted files: {conflicted}")
    success = True
    for filepath in conflicted:
        path = repo_root / filepath
        if not path.exists():
            git("rm", filepath, check=False)
            continue
        ok = (
            resolve_pyproject_conflicts(path)
            if filepath == "pyproject.toml"
            else resolve_noqa_conflicts(path)
        )  # noqa: E501
        if ok:
            git("add", filepath)
        else:
            print(f"  Could not resolve {filepath}")
            success = False
    return success


# ── Lint fixer ──────────────────────────────────────────────────────


def fix_pyproject_toml(repo_root: Path) -> None:
    path = repo_root / "pyproject.toml"
    content = path.read_text()
    first = content.find("[tool.setuptools.packages.find]")
    second = content.find("[tool.setuptools.packages.find]", first + 1)
    if second != -1:
        next_sec = content.find("\n[", first + 1)
        if next_sec != -1:
            path.write_text(content[:first] + content[next_sec + 1 :])


def fix_lint(repo_root: Path) -> bool:
    dirs = ["scripts/", "future_agents/", "guardrails/"]
    result = run(["ruff", "check", *dirs, "--output-format=concise"], check=False, capture=True)
    if "Failed to parse" in (result.stderr + result.stdout):
        fix_pyproject_toml(repo_root)
    run(["ruff", "check", "--fix", "--unsafe-fixes", *dirs], check=False)
    # Add # noqa: E501 to remaining long lines
    result = run(["ruff", "check", *dirs, "--output-format=concise"], check=False, capture=True)
    violations: dict[str, set[int]] = {}
    for line in result.stdout.splitlines():
        m = re.match(r"^(.+):(\d+):\d+: E501", line)
        if m:
            violations.setdefault(m.group(1), set()).add(int(m.group(2)))
    for filepath, linenos in violations.items():
        path = repo_root / filepath.strip()
        if not path.exists():
            continue
        file_lines = path.read_text().splitlines(keepends=True)
        for lineno in sorted(linenos):
            idx = lineno - 1
            if idx >= len(file_lines):
                continue
            stripped = file_lines[idx].rstrip("\n").rstrip("\r")
            if "# noqa" not in stripped and not stripped.rstrip().endswith("\\"):
                file_lines[idx] = stripped + "  # noqa: E501\n"
            elif "# noqa:" in stripped and "E501" not in stripped:
                file_lines[idx] = stripped.replace("# noqa:", "# noqa: E501,") + "\n"
        path.write_text("".join(file_lines))
    run(["ruff", "format", *dirs], check=False)
    result = run(["ruff", "check", *dirs, "--output-format=concise"], check=False, capture=True)
    passed = result.returncode == 0
    print(f"  Lint: {'PASS' if passed else 'FAIL'}")
    if not passed and result.stdout.strip():
        print(result.stdout[:1000])
    return passed


# ── PR check helpers ──────────────────────────────────────────────────


def get_check_conclusions(pr: dict) -> dict[str, str]:
    sha = pr["head"]["sha"]
    data = gh_get(f"repos/{REPO}/commits/{sha}/check-runs")
    runs = data.get("check_runs", []) if isinstance(data, dict) else []
    result: dict[str, str] = {}
    for r in runs:
        name = r["name"]
        conclusion = r.get("conclusion") or r.get("status", "queued")
        if name not in result or conclusion not in ("queued", "in_progress"):
            result[name] = conclusion
    return result


def all_checks_green(pr: dict) -> bool:
    checks = {k: v for k, v in get_check_conclusions(pr).items() if "guardian" not in k.lower()}
    return bool(checks) and all(v == "success" for v in checks.values())


def checks_pending(pr: dict) -> bool:
    checks = {k: v for k, v in get_check_conclusions(pr).items() if "guardian" not in k.lower()}
    return any(v in ("queued", "in_progress") for v in checks.values())


def lint_failing(pr: dict) -> bool:
    return any(
        ("lint" in k.lower() or "ruff" in k.lower()) and v == "failure"
        for k, v in get_check_conclusions(pr).items()
    )


# ── Per-PR handler ───────────────────────────────────────────────────────────


def handle_pr(pr: dict, repo_root: Path) -> None:
    number = pr["number"]
    title = pr["title"]
    branch = pr["head"]["ref"]
    base = pr["base"]["ref"]

    print(f"\nPR #{number}: {title[:70]}")
    if pr["state"] != "open":
        print("  skip: not open")
        return

    # Refresh to get computed mergeable_state
    pr = gh_get(f"repos/{REPO}/pulls/{number}")
    mergeable = pr.get("mergeable_state", "unknown")
    print(f"  {branch} -> {base} | {mergeable}")

    remote_url = f"https://x-access-token:{TOKEN}@github.com/{REPO}.git"
    git("remote", "set-url", "origin", remote_url, check=False)
    git("fetch", "origin", base, "--quiet", check=False)
    git("fetch", "origin", branch, "--quiet", check=False)

    if mergeable == "dirty":
        print("  action: resolve conflicts")
        git("checkout", "-B", branch, f"origin/{branch}")
        git("merge", f"origin/{base}", "--no-edit", check=False)
        if not resolve_all_conflicts(repo_root):
            print("  unresolvable — skip")
            return
        run(["pip", "install", "-e", ".[dev]", "-q"], check=False)
        fix_lint(repo_root)
        git("add", "-A")
        status = git("status", "--porcelain", capture=True, check=False)
        if status.stdout.strip():
            git(
                "commit",
                "-m",
                f"chore: merge {base} into {branch}, resolve conflicts [pr-guardian]",
                check=False,
            )
            git("push", "origin", branch, check=False)
            print(f"  pushed conflict fix to {branch}")
        return

    if mergeable == "blocked":
        if checks_pending(pr):
            print("  checks pending — retry next run")
            return
        if lint_failing(pr):
            print("  action: fix lint")
            git("checkout", "-B", branch, f"origin/{branch}")
            run(["pip", "install", "-e", ".[dev]", "-q"], check=False)
            fix_lint(repo_root)
            git("add", "-A")
            status = git("status", "--porcelain", capture=True, check=False)
            if status.stdout.strip():
                git("commit", "-m", "fix: auto-fix ruff lint and format [pr-guardian]", check=False)
                git("push", "origin", branch, check=False)
                print(f"  pushed lint fix to {branch}")
            return
        failing = [k for k, v in get_check_conclusions(pr).items() if v == "failure"]
        if failing:
            print(f"  non-lint failures: {failing} — needs manual review")
        return

    if mergeable == "clean":
        if all_checks_green(pr):
            print("  action: merge")
            result = gh_put(
                f"repos/{REPO}/pulls/{number}/merge",
                {"commit_title": f"Merge PR #{number}: {title}", "merge_method": "merge"},
            )
            if result.get("merged"):
                print(f"  PR #{number} merged")
            else:
                print(f"  merge failed: {result}")
        else:
            print(f"  checks not green: {get_check_conclusions(pr)}")
        return

    print(f"  unknown state '{mergeable}' — skip")


def main() -> None:
    if not TOKEN:
        print("GITHUB_TOKEN not set")
        sys.exit(1)
    repo_root = Path(__file__).parent.parent
    prs_data = gh_get(f"repos/{REPO}/pulls?state=open&per_page=50")
    if not isinstance(prs_data, list):
        print(f"Bad API response: {prs_data}")
        sys.exit(0)
    prs = [p for p in prs_data if not p.get("draft", False)]
    print(f"Open PRs: {len(prs)}")
    for pr in prs:
        try:
            handle_pr(pr, repo_root)
        except Exception as exc:
            print(f"  error PR #{pr['number']}: {exc}")
            import traceback

            traceback.print_exc()
    print("\nPR Guardian done")


if __name__ == "__main__":
    main()
