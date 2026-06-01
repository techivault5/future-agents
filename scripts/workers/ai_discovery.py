#!/usr/bin/env python3
"""AI Discovery Worker script — uses Claude to discover new patterns and capabilities.

Scans the codebase, queries Claude for improvement opportunities, and creates
a GitHub Issue with findings mentioning @Copilot for follow-up review.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ISSUE_TITLE_PREFIX = "[AI Discovery]"

try:
    import anthropic

    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False


# ── Helpers ───────────────────────────────────────────────────────────────────


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def open_issue_exists(prefix: str) -> bool:
    r = run(["gh", "issue", "list", "--state", "open", "--json", "title", "--limit", "30"])
    if r.returncode != 0:
        return False
    try:
        return any(i["title"].startswith(prefix) for i in json.loads(r.stdout))
    except (json.JSONDecodeError, KeyError):
        return False


# ── Codebase scanning ─────────────────────────────────────────────────────────


def scan_agents() -> list[dict]:
    agents_dir = ROOT / "future_agents" / "agents"
    results = []
    for py_file in sorted(agents_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            base_names = [
                b.id if isinstance(b, ast.Name) else (b.attr if isinstance(b, ast.Attribute) else "")
                for b in node.bases
            ]
            if "BaseAgent" not in base_names:
                continue
            caps: list[str] = []
            agent_type = ""
            for child in ast.walk(node):
                if isinstance(child, ast.FunctionDef):
                    if child.name == "capabilities":
                        for n in ast.walk(child):
                            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                                caps.append(n.value)
                    elif child.name == "agent_type":
                        for n in ast.walk(child):
                            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                                agent_type = n.value
                                break
            results.append(
                {
                    "class": node.name,
                    "file": py_file.name,
                    "agent_type": agent_type,
                    "capabilities": caps,
                }
            )
    return results


def scan_workers() -> list[str]:
    workers_dir = ROOT / "future_agents" / "workers"
    return [f.stem for f in workers_dir.glob("*_worker.py") if not f.name.startswith("_") and f.stem != "base_worker"]


KNOWN_PATTERNS = [
    "ReAct",
    "Reflection",
    "Plan-and-Execute",
    "Tool-Use",
    "Chain-of-Thought",
    "Self-Consistency",
    "Subagent-Delegation",
    "Memory-Augmented",
]


# ── Claude query ──────────────────────────────────────────────────────────────


def query_claude(agents: list[dict], workers: list[str]) -> str:
    if not _ANTHROPIC_AVAILABLE:
        return "anthropic package not installed. Add ANTHROPIC_API_KEY secret and install with: pip install anthropic"

    agent_lines = "\n".join(f"- {a['class']} (type={a['agent_type']}, caps={a['capabilities'][:3]})" for a in agents)
    worker_lines = "\n".join(f"- {w}" for w in workers)
    pattern_lines = "\n".join(f"- {p}" for p in KNOWN_PATTERNS)

    prompt = (
        f"You are analysing a Python multi-agent system called 'future-agents'.\n\n"
        f"## Current Agents\n{agent_lines}\n\n"
        f"## Current Workers\n{worker_lines}\n\n"
        f"## Known Agentic Patterns (already implemented)\n{pattern_lines}\n\n"
        f"Please provide:\n"
        f"1. **3 new agentic patterns or capabilities** not yet implemented that would "
        f"   significantly improve this system. For each, explain what it does and the "
        f"   concrete benefit.\n"
        f"2. **2 new worker types** that would add continuous improvement value.\n"
        f"3. **1 highest-priority implementation recommendation** with concrete steps.\n"
        f"4. **Any architectural improvements** you notice from the agent/worker inventory.\n\n"
        f"Be specific, actionable, and reference the existing codebase structure."
    )

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=3000,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )
    return "\n".join(b.text for b in response.content if hasattr(b, "text"))


# ── Issue creation ────────────────────────────────────────────────────────────


def create_issue(agents: list[dict], workers: list[str], discoveries: str) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title = f"{ISSUE_TITLE_PREFIX} New patterns and capabilities — {today}"

    agent_rows = "\n".join(
        f"| `{a['class']}` | `{a['agent_type']}` | {', '.join(f'`{c}`' for c in a['capabilities'][:3]) or '—'} |"
        for a in agents
    )
    worker_rows = "\n".join(f"- `{w}`" for w in workers)

    body = "\n".join(
        [
            f"## AI Discovery Report — {today}",
            "",
            "This issue was auto-generated by the **AI Discovery Worker** using Claude.",
            "",
            "### Current Agent Inventory",
            "",
            "| Class | Type | Capabilities |",
            "|-------|------|--------------|",
            agent_rows,
            "",
            "### Current Workers",
            "",
            worker_rows,
            "",
            "### Claude's Discoveries & Recommendations",
            "",
            discoveries,
            "",
            "---",
            "> 🤖 Auto-generated by **AI Discovery Worker** (GitHub Actions).",
            "> @Copilot please review these suggestions and help prioritise implementation.",
        ]
    )

    r = run(
        [
            "gh",
            "issue",
            "create",
            "--title",
            title,
            "--body",
            body,
            "--label",
            "automated,ai-discovery",
        ]
    )
    if r.returncode == 0:
        print(f"Issue created: {title}")
    else:
        print(f"gh issue create failed: {r.stderr}", file=sys.stderr)
        sys.exit(1)


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    print("Running AI discovery...")
    agents = scan_agents()
    workers = scan_workers()
    print(f"  Agents found  : {len(agents)}")
    print(f"  Workers found : {len(workers)}")

    if open_issue_exists(ISSUE_TITLE_PREFIX):
        print("Recent AI discovery issue already exists — skipping.")
        return

    print("  Querying Claude for discoveries...")
    discoveries = query_claude(agents, workers)
    print(f"  Discoveries length: {len(discoveries)} chars")

    create_issue(agents, workers, discoveries)


if __name__ == "__main__":
    main()
