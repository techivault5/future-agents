#!/usr/bin/env python3
"""AI Repo Crawler — daily crawl of top AI repos for new changes.

Reads scripts/ai_crawler/repos.json for the repo list.
Reads/writes scripts/ai_crawler/state.json for last-seen commit SHAs.
Outputs scripts/ai_crawler/changes_YYYY-MM-DD.json with today's findings.

Usage:
    python scripts/ai_crawler/crawl.py
    python scripts/ai_crawler/crawl.py --dry-run   # skip gh calls, print plan
    python scripts/ai_crawler/crawl.py --since 2026-05-01  # override date
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CRAWLER_DIR = ROOT / "scripts" / "ai_crawler"
STATE_FILE = CRAWLER_DIR / "state.json"
REPOS_FILE = CRAWLER_DIR / "repos.json"


# ── GitHub helpers ────────────────────────────────────────────────────────────


def gh(args: list[str], dry_run: bool = False) -> dict | list | None:
    if dry_run:
        print(f"  [dry-run] gh {' '.join(args)}")
        return None
    result = subprocess.run(
        ["gh", "api", "--paginate", *args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  gh error: {result.stderr.strip()}", file=sys.stderr)
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def get_recent_commits(owner: str, repo: str, since: str, dry_run: bool = False) -> list[dict]:
    """Return commits on default branch since ISO date."""
    data = gh(
        [f"repos/{owner}/{repo}/commits", "-F", f"since={since}&per_page=30"],
        dry_run=dry_run,
    )
    if not data or not isinstance(data, list):
        return []
    return [
        {
            "sha": c["sha"][:12],
            "message": c["commit"]["message"].split("\n")[0][:120],
            "author": c["commit"]["author"]["name"],
            "date": c["commit"]["author"]["date"],
            "url": c["html_url"],
        }
        for c in data
    ]


def get_recent_releases(owner: str, repo: str, dry_run: bool = False) -> list[dict]:
    """Return the last 3 releases."""
    data = gh([f"repos/{owner}/{repo}/releases", "-F", "per_page=3"], dry_run=dry_run)
    if not data or not isinstance(data, list):
        return []
    return [
        {
            "tag": r["tag_name"],
            "name": r["name"],
            "published_at": r["published_at"],
            "url": r["html_url"],
            "body_excerpt": (r.get("body") or "")[:300],
        }
        for r in data[:3]
    ]


def get_repo_meta(owner: str, repo: str, dry_run: bool = False) -> dict:
    data = gh([f"repos/{owner}/{repo}"], dry_run=dry_run)
    if not data or not isinstance(data, dict):
        return {}
    return {
        "stars": data.get("stargazers_count", 0),
        "forks": data.get("forks_count", 0),
        "open_issues": data.get("open_issues_count", 0),
        "default_branch": data.get("default_branch", "main"),
        "description": data.get("description", ""),
        "topics": data.get("topics", []),
        "pushed_at": data.get("pushed_at", ""),
    }


# ── State management ──────────────────────────────────────────────────────────


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {"last_crawl": None, "seen_shas": {}, "repo_meta": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Main crawl ────────────────────────────────────────────────────────────────


def crawl_all(since: str, dry_run: bool = False) -> dict:
    repos_data = json.loads(REPOS_FILE.read_text())
    state = load_state()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    findings: dict = {
        "crawl_date": today,
        "since": since,
        "repos_crawled": 0,
        "repos_with_changes": 0,
        "changes": [],
        "errors": [],
    }

    all_repos: list[dict] = []
    for cat, entries in repos_data.get("categories", {}).items():
        for entry in entries:
            all_repos.append({**entry, "category": cat})

    print(f"Crawling {len(all_repos)} repos since {since}...")

    for repo_info in all_repos:
        owner = repo_info["owner"]
        repo = repo_info["repo"]
        slug = f"{owner}/{repo}"
        findings["repos_crawled"] += 1

        print(f"  {slug}...", end=" ", flush=True)

        try:
            commits = get_recent_commits(owner, repo, since, dry_run)
            releases = get_recent_releases(owner, repo, dry_run)
            meta = get_repo_meta(owner, repo, dry_run)
        except Exception as exc:
            findings["errors"].append({"repo": slug, "error": str(exc)})
            print(f"ERROR: {exc}")
            continue

        # Filter out already-seen SHAs
        seen = set(state["seen_shas"].get(slug, []))
        new_commits = [c for c in commits if c["sha"] not in seen]

        if not new_commits and not releases:
            print("no changes")
            continue

        findings["repos_with_changes"] += 1
        change = {
            "repo": slug,
            "category": repo_info["category"],
            "description": repo_info.get("description", ""),
            "tags": repo_info.get("tags", []),
            "meta": meta,
            "new_commits": new_commits,
            "recent_releases": releases,
            "commit_count": len(new_commits),
        }
        findings["changes"].append(change)

        # Update state
        all_shas = [c["sha"] for c in commits]
        state["seen_shas"][slug] = list(set(list(seen) + all_shas))[-100:]  # cap at 100
        state["repo_meta"][slug] = meta

        print(f"{len(new_commits)} new commits, {len(releases)} releases")

    # Save
    state["last_crawl"] = today
    if not dry_run:
        save_state(state)
        out = CRAWLER_DIR / f"changes_{today}.json"
        out.write_text(json.dumps(findings, indent=2))
        print(f"\nSaved: {out.name}  ({findings['repos_with_changes']} repos with changes)")

    return findings


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    p = argparse.ArgumentParser(description="Crawl AI repos for daily changes")
    p.add_argument("--since", help="ISO date to crawl from (default: yesterday)")
    p.add_argument("--dry-run", action="store_true", help="Print plan without calling gh")
    args = p.parse_args()

    if args.since:
        since = args.since
    else:
        from datetime import timedelta

        since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")

    crawl_all(since, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
