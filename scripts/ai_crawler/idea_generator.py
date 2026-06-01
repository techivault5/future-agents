#!/usr/bin/env python3
"""Idea Generator — uses Claude to synthesise patentable ideas from daily crawl findings.

Reads  : scripts/ai_crawler/eval_results_YYYY-MM-DD.json  (from eval_runner.py)
         scripts/ai_crawler/changes_YYYY-MM-DD.json        (raw commits/releases)
Outputs: scripts/ai_crawler/ideas_YYYY-MM-DD.json
         GitHub Issue with 2 patentable ideas + @Copilot mention

Schedule: runs at 07:50 UTC (08:50 Ireland IST/BST) via GitHub Actions.

Usage:
    python scripts/ai_crawler/idea_generator.py
    python scripts/ai_crawler/idea_generator.py --no-issue   # skip GitHub Issue
    python scripts/ai_crawler/idea_generator.py --eval-file path/to/eval_results.json
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
MEMORY_FILE = CRAWLER_DIR / "idea_memory.json"

try:
    import anthropic as _anthropic

    _SDK_OK = True
except ImportError:
    _SDK_OK = False

# ── Prompts ───────────────────────────────────────────────────────────────────

_IDEA_SYSTEM = """\
You are a world-class AI systems architect and patent strategist.
Your job is to synthesise novel, non-obvious, technically concrete ideas that
could be filed as patent applications. Each idea must combine insights from
multiple recent AI developments in a way that is genuinely new.

Rules:
- Ideas must be technically implementable, not vague concepts.
- Each idea must reference specific techniques from the sources provided.
- Focus on systems-level inventions: novel architectures, algorithms, protocols.
- Avoid ideas that are obvious combinations or already widely published.
- Phrase claims in the spirit of patent language: "A system for...", "A method of..."
"""

_IDEA_PROMPT = """\
Today is {today}. You have analysed {repo_count} AI repositories and found
{change_count} with significant new changes. Below is a curated digest.

## High-Priority Findings (most relevant to our system)
{high_priority}

## All Change Summaries
{all_changes}

## Our Existing System Capabilities
- Agentic patterns: ReAct, Reflection, Plan-and-Execute, Tool-Use, Memory-Augmented
- Workers: code improvement, pattern discovery, agent gathering, knowledge synthesis, AI discovery
- Infrastructure: EventBus, AgentRegistry, KnowledgeStore (versioned), MetricTracker, SyncEngine
- Token optimization: exact/fuzzy memory cache, Claude prompt caching (cache_control: ephemeral)
- Digital Worker Agent: Claude-powered, tool-registry, adaptive thinking

## Previously Generated Ideas (do NOT repeat these)
{prior_ideas}

## Task
Generate EXACTLY 2 patentable ideas. Each idea must:
1. Combine techniques from at least 2 different repos in the findings above.
2. Represent a novel architecture or method not currently in our system.
3. Be implementable in Python within 2-4 weeks by a senior engineer.
4. Have clear prior-art differentiation.

For each idea, provide:
- title: short, descriptive (10 words max)
- one_liner: one sentence describing the invention
- problem_solved: what specific pain point this addresses
- technical_description: 3-5 sentences describing the mechanism
- key_claims: list of 3 patent-style claims ("A method of...", "A system for...")
- source_repos: list of repo slugs that inspired this
- implementation_sketch: concrete Python pseudocode or architecture diagram (text)
- novelty_argument: why this is non-obvious over existing art
- estimated_impact: high|medium and why

Respond as valid JSON only:
{{
  "ideas": [
    {{
      "title": "...",
      "one_liner": "...",
      "problem_solved": "...",
      "technical_description": "...",
      "key_claims": ["...", "...", "..."],
      "source_repos": ["owner/repo", ...],
      "implementation_sketch": "...",
      "novelty_argument": "...",
      "estimated_impact": "high|medium",
      "impact_reason": "..."
    }},
    {{ ... second idea ... }}
  ],
  "generation_date": "{today}",
  "repos_analysed": {repo_count}
}}
"""


# ── Helpers ───────────────────────────────────────────────────────────────────


def load_prior_ideas() -> list[str]:
    if not MEMORY_FILE.exists():
        return []
    try:
        data = json.loads(MEMORY_FILE.read_text())
        return [f"[{d}] {t}" for d, t in data.get("titles", {}).items()]
    except Exception:
        return []


def save_idea_titles(titles: list[str], date: str) -> None:
    data: dict = {}
    if MEMORY_FILE.exists():
        try:
            data = json.loads(MEMORY_FILE.read_text())
        except Exception:
            pass
    data.setdefault("titles", {})[date] = titles
    # Keep last 90 days
    if len(data["titles"]) > 90:
        oldest = sorted(data["titles"].keys())[0]
        del data["titles"][oldest]
    MEMORY_FILE.write_text(json.dumps(data, indent=2))


def format_high_priority(eval_results: dict) -> str:
    lines = []
    for item in eval_results.get("high_priority", [])[:8]:
        lines.append(f"### {item['repo']} (score={item['score']:.2f})")
        lines.append(f"Suggestion: {item.get('suggestion', 'N/A')}")
        lines.append(f"Tags: {', '.join(item.get('tags', []))}")
        lines.append("")
    return "\n".join(lines) or "No high-priority items found."


def format_all_changes(changes_data: dict) -> str:
    lines = []
    for change in changes_data.get("changes", [])[:20]:
        repo = change["repo"]
        commits = change.get("new_commits", [])[:3]
        releases = change.get("recent_releases", [])[:1]
        lines.append(f"**{repo}** [{change['category']}]")
        for c in commits:
            lines.append(f"  commit: {c['message'][:100]}")
        for r in releases:
            lines.append(f"  release {r['tag']}: {r['name']}")
            if r.get("body_excerpt"):
                lines.append(f"    {r['body_excerpt'][:200]}")
        lines.append("")
    return "\n".join(lines) or "No changes found."


def generate_ideas(eval_file: Path, changes_file: Path) -> dict:
    if not _SDK_OK:
        print("anthropic not installed — run: pip install anthropic", file=sys.stderr)
        sys.exit(1)

    eval_results = json.loads(eval_file.read_text())
    changes_data = json.loads(changes_file.read_text())
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prior = load_prior_ideas()

    prompt = _IDEA_PROMPT.format(
        today=today,
        repo_count=changes_data.get("repos_crawled", 0),
        change_count=changes_data.get("repos_with_changes", 0),
        high_priority=format_high_priority(eval_results),
        all_changes=format_all_changes(changes_data),
        prior_ideas="\n".join(f"- {p}" for p in prior[-20:]) or "(none yet)",
    )

    client = _anthropic.Anthropic()
    print("Generating ideas with Claude (adaptive thinking)...")
    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        system=[
            {
                "type": "text",
                "text": _IDEA_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": prompt}],
    )

    text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    ideas_data = json.loads(text)
    ideas_data["tokens_used"] = response.usage.input_tokens + response.usage.output_tokens

    # Persist titles for dedup
    titles = [idea["title"] for idea in ideas_data.get("ideas", [])]
    save_idea_titles(titles, today)

    out = CRAWLER_DIR / f"ideas_{today}.json"
    out.write_text(json.dumps(ideas_data, indent=2))
    print(f"Saved: {out.name}  (tokens: {ideas_data['tokens_used']:,})")
    return ideas_data


def post_github_issue(ideas_data: dict) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ideas = ideas_data.get("ideas", [])
    if not ideas:
        print("No ideas to post.", file=sys.stderr)
        return

    lines = [
        f"## 🧠 Daily AI Patent Ideas — {today}",
        "",
        f"Generated by analysing **{ideas_data.get('repos_analysed', 0)} AI repositories**.",
        "",
    ]

    for i, idea in enumerate(ideas, 1):
        lines += [
            "---",
            f"## Idea {i}: {idea['title']}",
            "",
            f"**{idea['one_liner']}**",
            "",
            "### Problem Solved",
            idea["problem_solved"],
            "",
            "### Technical Description",
            idea["technical_description"],
            "",
            "### Key Patent Claims",
            "",
        ]
        for claim in idea.get("key_claims", []):
            lines.append(f"1. {claim}")
        lines += [
            "",
            "### Implementation Sketch",
            "```",
            idea.get("implementation_sketch", ""),
            "```",
            "",
            "### Novelty Argument",
            idea["novelty_argument"],
            "",
            "### Source Repos",
            ", ".join(f"`{r}`" for r in idea.get("source_repos", [])),
            "",
            f"**Estimated Impact:** {idea.get('estimated_impact', 'medium').upper()} — {idea.get('impact_reason', '')}",
            "",
        ]

    lines += [
        "---",
        "> 🤖 Auto-generated by **AI Idea Generator** (GitHub Actions, 07:50 UTC).",
        "> @Copilot please review these ideas and suggest implementation priorities.",
    ]

    body = "\n".join(lines)
    title = f"[Patent Ideas] {' + '.join(idea['title'] for idea in ideas)} — {today}"

    result = subprocess.run(
        [
            "gh",
            "issue",
            "create",
            "--title",
            title,
            "--body",
            body,
            "--label",
            "automated,patent-ideas",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(f"Issue created: {title}")
    else:
        print(f"gh issue create failed: {result.stderr}", file=sys.stderr)


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    p = argparse.ArgumentParser(description="Generate patentable ideas from daily AI crawl")
    p.add_argument("--eval-file", help="Path to eval_results JSON")
    p.add_argument("--changes-file", help="Path to changes JSON")
    p.add_argument("--no-issue", action="store_true", help="Skip creating GitHub Issue")
    args = p.parse_args()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    eval_file = Path(args.eval_file) if args.eval_file else CRAWLER_DIR / f"eval_results_{today}.json"
    changes_file = Path(args.changes_file) if args.changes_file else CRAWLER_DIR / f"changes_{today}.json"

    for f in [eval_file, changes_file]:
        if not f.exists():
            print(f"File not found: {f}", file=sys.stderr)
            sys.exit(1)

    ideas_data = generate_ideas(eval_file, changes_file)

    if not args.no_issue:
        post_github_issue(ideas_data)


if __name__ == "__main__":
    main()
