#!/usr/bin/env python3
"""Agent Gatherer Worker — detects coverage gaps, generates skeleton agents, opens PRs.

Checks which agent domains have no implementation or definition, generates
skeleton JSON files for the most important gaps, and opens a draft PR so
Copilot and reviewers can flesh them out.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# Domains we want covered, ordered by importance
TARGET_DOMAINS: dict[str, dict] = {
    "monitoring": {
        "description": "System health monitoring, alerting, and metrics collection",
        "intents": ["monitoring.health", "monitoring.alert", "monitoring.metrics"],
        "importance": "high",
    },
    "security": {
        "description": "Security auditing, vulnerability scanning, and policy enforcement",
        "intents": ["security.audit", "security.scan", "security.policy"],
        "importance": "high",
    },
    "data": {
        "description": "Data transformation, validation, and pipeline management",
        "intents": ["data.transform", "data.validate", "data.pipeline"],
        "importance": "high",
    },
    "notification": {
        "description": "Multi-channel notification routing and escalation",
        "intents": ["notification.send", "notification.route", "notification.escalate"],
        "importance": "medium",
    },
    "analytics": {
        "description": "Reporting, querying, and data aggregation",
        "intents": ["analytics.report", "analytics.query", "analytics.aggregate"],
        "importance": "medium",
    },
    "scheduler": {
        "description": "Task scheduling, planning, and execution tracking",
        "intents": ["scheduler.plan", "scheduler.execute", "scheduler.status"],
        "importance": "medium",
    },
    "ml": {
        "description": "Machine learning model training, prediction, and evaluation",
        "intents": ["ml.train", "ml.predict", "ml.evaluate"],
        "importance": "low",
    },
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def existing_agent_types() -> set[str]:
    """Agent types deduced from *_agent.py filenames."""
    return {
        f.name.replace("_agent.py", "")
        for f in (ROOT / "future_agents" / "agents").glob("*_agent.py")
        if not f.name.startswith("_")
    }


def existing_definition_types() -> set[str]:
    """Agent types from agents/*.json (excluding skeleton stubs)."""
    types: set[str] = set()
    for f in (ROOT / "agents").glob("*.json"):
        try:
            data = json.loads(f.read_text())
            if not data.get("metadata", {}).get("auto_generated"):
                types.add(data.get("type", f.stem))
        except (json.JSONDecodeError, KeyError):
            pass
    return types


def find_gaps() -> list[dict]:
    impl_types = existing_agent_types()
    def_types = existing_definition_types()
    covered = impl_types | def_types

    gaps = []
    for domain, info in TARGET_DOMAINS.items():
        if domain not in covered:
            gaps.append({"domain": domain, **info})
    return gaps


# ── Skeleton generation ───────────────────────────────────────────────────────


def generate_skeleton(gap: dict) -> Path | None:
    domain = gap["domain"]
    out = ROOT / "agents" / f"{domain}.json"
    if out.exists():
        return None  # already exists (maybe from a prior run)

    skeleton = {
        "id": f"{domain}_agent",
        "name": f"{domain.capitalize()} Agent",
        "type": domain,
        "version": "0.1.0",
        "description": gap["description"],
        "skills": [
            {
                "name": intent.replace(".", "_"),
                "description": f"Handles {intent} operations",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "target": {
                            "type": "string",
                            "description": "Target resource or identifier",
                        },
                        "options": {"type": "object", "description": "Additional options"},
                    },
                    "required": ["target"],
                },
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string"},
                        "result": {"type": "object"},
                    },
                },
            }
            for intent in gap["intents"]
        ],
        "constraints": {
            "max_concurrent_tasks": 5,
            "timeout_seconds": 30,
        },
        "metadata": {
            "auto_generated": True,
            "importance": gap["importance"],
            "status": "skeleton — needs implementation",
        },
    }

    out.write_text(json.dumps(skeleton, indent=2) + "\n")
    print(f"  Generated: {out.name}")
    return out


# ── GitHub interactions ───────────────────────────────────────────────────────


def create_pr(gaps: list[dict], files: list[Path]) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    branch = f"feat/skeleton-agents-{today}"

    run(["git", "checkout", "-b", branch])
    for f in files:
        run(["git", "add", str(f)])

    domains = ", ".join(g["domain"] for g in gaps)
    run(["git", "commit", "-m", f"chore: add skeleton agent definitions for {domains}"])
    push = run(["git", "push", "-u", "origin", branch])
    if push.returncode != 0:
        print(f"Push failed: {push.stderr}", file=sys.stderr)
        return

    body_lines = [
        f"## Agent Gatherer: Skeleton Definitions — {today}",
        "",
        "This draft PR was auto-generated by the **Agent Gatherer Worker**.",
        "Review, implement the Python agent classes, and remove the draft flag when ready.",
        "",
        "### Coverage Gaps Addressed",
        "",
    ]
    for gap in gaps:
        body_lines += [
            f"#### `{gap['domain']}` (importance: **{gap['importance']}**)",
            f"> {gap['description']}",
            "",
            f"Intents: {', '.join(f'`{i}`' for i in gap['intents'])}",
            "",
        ]

    body_lines += [
        "### Files Created",
        "",
        *[f"- `{f.relative_to(ROOT)}`" for f in files],
        "",
        "### Implementation Checklist",
        "",
        "- [ ] Create `future_agents/agents/{domain}_agent.py` for each skeleton",
        "- [ ] Register the implementation in `future_agents/system.py`",
        "- [ ] Add tests in `tests/agents/`",
        "- [ ] Remove `auto_generated: true` from the definition metadata",
        "",
        "> 🤖 Auto-generated by **Agent Gatherer Worker** (GitHub Actions).",
        "> @Copilot please review these definitions and suggest implementation details for each agent.",
    ]

    r = run(
        [
            "gh",
            "pr",
            "create",
            "--title",
            f"[Agent Gatherer] Skeleton definitions for {domains}",
            "--body",
            "\n".join(body_lines),
            "--label",
            "automated,agent-gap",
            "--draft",
        ]
    )
    if r.returncode == 0:
        print(f"Draft PR created for: {domains}")
    else:
        print(f"gh pr create failed: {r.stderr}", file=sys.stderr)


def create_gap_issue(gaps: list[dict]) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = "\n".join(f"| `{g['domain']}` | {g['importance']} | {g['description']} |" for g in gaps)
    body = "\n".join(
        [
            f"## Agent Coverage Gaps — {today}",
            "",
            f"**{len(gaps)} domains** have no agent implementation or definition.",
            "",
            "| Domain | Importance | Description |",
            "|--------|-----------|-------------|",
            rows,
            "",
            "Skeleton definitions are being generated in `agents/` via a separate PR.",
            "",
            "> 🤖 Auto-generated by **Agent Gatherer Worker** (GitHub Actions).",
        ]
    )

    r = run(
        [
            "gh",
            "issue",
            "create",
            "--title",
            f"[Agent Coverage] {len(gaps)} uncovered domains ({today})",
            "--body",
            body,
            "--label",
            "automated,agent-gap",
        ]
    )
    if r.returncode == 0:
        print(f"Gap issue created for {len(gaps)} domains")
    else:
        print(f"gh issue create failed: {r.stderr}", file=sys.stderr)


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    print("Running agent gatherer...")
    print(f"  Existing implementations : {sorted(existing_agent_types())}")
    print(f"  Existing definitions     : {sorted(existing_definition_types())}")

    gaps = find_gaps()
    if not gaps:
        print("✓ All target domains are covered!")
        return

    print(f"  Gaps found: {[g['domain'] for g in gaps]}")

    # Generate skeletons for high- and medium-importance gaps (max 3 per run)
    priority_gaps = [g for g in gaps if g["importance"] in ("high", "medium")][:3]
    created_files: list[Path] = []
    for gap in priority_gaps:
        path = generate_skeleton(gap)
        if path:
            created_files.append(path)

    if created_files:
        create_pr(priority_gaps[: len(created_files)], created_files)

    create_gap_issue(gaps)


if __name__ == "__main__":
    main()
