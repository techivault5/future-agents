#!/usr/bin/env python3
"""Pattern Discovery Worker — analyses the codebase for agent patterns and skills.

Walks the source tree with the stdlib ast module (no extra deps), finds all
BaseAgent subclasses and their capabilities, cross-references JSON definitions,
and creates a daily GitHub Issue with findings.

Mentions @Copilot so GitHub Copilot can suggest architectural improvements.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ISSUE_TITLE_PREFIX = "[Patterns]"


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


# ── Discovery ─────────────────────────────────────────────────────────────────


def discover_agent_implementations() -> list[dict]:
    """Parse agent Python files to extract class names and capabilities."""
    results = []
    agents_dir = ROOT / "future_agents" / "agents"

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


def discover_definitions() -> list[dict]:
    """Load all agent JSON definition files."""
    results = []
    for json_file in sorted((ROOT / "agents").glob("*.json")):
        try:
            data = json.loads(json_file.read_text())
            results.append(
                {
                    "name": data.get("name", json_file.stem),
                    "type": data.get("type", ""),
                    "skills": [s.get("name", "") for s in data.get("skills", [])],
                    "file": json_file.name,
                    "auto_generated": data.get("metadata", {}).get("auto_generated", False),
                }
            )
        except (json.JSONDecodeError, KeyError):
            pass
    return results


def discover_event_types() -> list[str]:
    """Grep for all event type strings in the source tree."""
    event_types: set[str] = set()
    pattern = re.compile(r'type=["\']([a-z][a-z0-9_\.]+)["\']')
    for py_file in ROOT.rglob("*.py"):
        try:
            for m in pattern.finditer(py_file.read_text()):
                event_types.add(m.group(1))
        except (OSError, UnicodeDecodeError):
            pass
    return sorted(event_types)


def discover_skills_in_use() -> dict[str, int]:
    """Count how many times each skill/capability string appears in tests and examples."""
    counts: dict[str, int] = {}
    for py_file in list((ROOT / "tests").rglob("*.py")) + list((ROOT / "examples").rglob("*.py")):
        try:
            src = py_file.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        for m in re.finditer(r'"([a-z]+\.[a-z_]+)"', src):
            counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))


# ── Report ────────────────────────────────────────────────────────────────────


def build_report(
    impls: list[dict],
    defs: list[dict],
    events: list[str],
    skills_used: dict[str, int],
) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"## Pattern Discovery Report — {today}",
        "",
        f"Found **{len(impls)} agent implementations**, "
        f"**{len(defs)} JSON definitions**, "
        f"**{len(events)} event types**.",
        "",
        "### Agent Implementations",
        "",
        "| Class | File | Type | Capabilities |",
        "|-------|------|------|--------------|",
    ]
    for impl in impls:
        caps = ", ".join(f"`{c}`" for c in impl["capabilities"][:3])
        if len(impl["capabilities"]) > 3:
            caps += f" *+{len(impl['capabilities']) - 3} more*"
        lines.append(f"| `{impl['class']}` | `{impl['file']}` | `{impl['agent_type']}` | {caps or '—'} |")

    lines += [
        "",
        "### Agent Definitions",
        "",
        "| Name | File | Skills | Auto-generated |",
        "|------|------|--------|----------------|",
    ]
    for d in defs:
        skills = ", ".join(f"`{s}`" for s in d["skills"][:3])
        lines.append(f"| {d['name']} | `{d['file']}` | {skills or '—'} | {'✅' if d['auto_generated'] else '—'} |")

    # Coverage gaps
    impl_types = {i["agent_type"] for i in impls}
    def_types = {d["type"] for d in defs if not d["auto_generated"]}
    unimplemented = def_types - impl_types
    if unimplemented:
        lines += [
            "",
            "### ⚠️ Definitions Without Implementations",
            "",
            "These definition types have no matching Python implementation:",
            "",
        ]
        for t in sorted(unimplemented):
            lines.append(f"- `{t}`")

    lines += [
        "",
        "### Event Types",
        "",
        "<details><summary>All event types in use</summary>",
        "",
        "```",
    ]
    lines.extend(events[:30])
    if len(events) > 30:
        lines.append(f"… and {len(events) - 30} more")
    lines += ["```", "", "</details>", ""]

    if skills_used:
        lines += [
            "### Most-Used Skills (in tests/examples)",
            "",
            "| Skill | References |",
            "|-------|-----------|",
        ]
        for skill, count in list(skills_used.items())[:10]:
            lines.append(f"| `{skill}` | {count} |")

    lines += [
        "",
        "### Recommendations",
        "",
        "1. Add implementations for any definitions listed above as unimplemented",
        "2. Write tests for capabilities that have zero references",
        "3. Review event naming for consistency (`domain.action` pattern)",
        "",
        "> 🤖 Auto-generated by **Pattern Discovery Worker** (GitHub Actions).",
        "> @Copilot please review the patterns above and suggest architectural improvements.",
    ]
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    print("Running pattern discovery...")

    impls = discover_agent_implementations()
    defs = discover_definitions()
    events = discover_event_types()
    skills_used = discover_skills_in_use()

    print(f"  implementations : {len(impls)}")
    print(f"  definitions     : {len(defs)}")
    print(f"  event types     : {len(events)}")
    print(f"  skills in use   : {len(skills_used)}")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title = f"{ISSUE_TITLE_PREFIX} Agent landscape — {today}"

    if open_issue_exists(ISSUE_TITLE_PREFIX):
        print("Recent pattern issue already exists — skipping.")
        return

    body = build_report(impls, defs, events, skills_used)

    args = [
        "gh",
        "issue",
        "create",
        "--title",
        title,
        "--body",
        body,
        "--label",
        "automated,pattern",
    ]
    r = run(args)
    if r.returncode == 0:
        print(f"Issue created: {title}")
    else:
        print(f"gh issue create failed: {r.stderr}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
