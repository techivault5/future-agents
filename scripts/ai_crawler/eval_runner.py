#!/usr/bin/env python3
"""Eval Runner — scores crawled AI repo changes against our eval rubric.

Reads  : scripts/ai_crawler/changes_YYYY-MM-DD.json  (from crawl.py)
         tests/evals/eval_cases.json                 (scoring rubric)
Writes : scripts/ai_crawler/eval_results_YYYY-MM-DD.json

Usage:
    python scripts/ai_crawler/eval_runner.py
    python scripts/ai_crawler/eval_runner.py --changes scripts/ai_crawler/changes_2026-05-24.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CRAWLER_DIR = ROOT / "scripts" / "ai_crawler"
EVALS_FILE = ROOT / "tests" / "evals" / "eval_cases.json"

try:
    import anthropic as _anthropic

    _SDK_OK = True
except ImportError:
    _SDK_OK = False


# ── Scoring ───────────────────────────────────────────────────────────────────

_SCORE_PROMPT = """\
You are an expert AI systems architect evaluating new open-source AI developments.

## Our Existing System
- Multi-agent framework: BaseAgent, EventBus, Orchestrator, AgentRegistry
- Agentic patterns: ReAct, Reflection, Tool-Use, Plan-and-Execute
- Workers: CodeImprovementWorker, PatternDiscoveryWorker, AgentGathererWorker,
  KnowledgeSynthesisWorker, AIDiscoveryWorker
- Token optimization: exact/fuzzy cache, prompt caching, terse system prompts
- Infrastructure: KnowledgeStore, MetricTracker, SyncEngine

## Eval Case
Name: {eval_name}
Description: {eval_description}
Category: {eval_category}

## Repo Change to Evaluate
Repo: {repo}
Category: {repo_category}
Tags: {tags}
Description: {repo_description}
New commits ({commit_count}):
{commits_text}

Recent releases:
{releases_text}

## Task
Score this change against the eval case criteria below. For each criterion,
assign a score 0.0-1.0 and give a one-sentence justification.

Criteria:
{criteria_text}

Respond as valid JSON only:
{{
  "scores": {{"criterion_name": score_float, ...}},
  "justifications": {{"criterion_name": "one sentence", ...}},
  "weighted_total": float,
  "integration_suggestion": "one concrete sentence on how to use this in our system",
  "priority": "high|medium|low"
}}
"""


def score_change_against_eval(change: dict, eval_case: dict, client) -> dict:
    commits_text = "\n".join(f"  - [{c['date'][:10]}] {c['message']}" for c in change["new_commits"][:8])
    releases_text = (
        "\n".join(
            f"  - {r['tag']}: {r['name']} ({r['published_at'][:10]})"
            + (f"\n    {r['body_excerpt'][:150]}" if r.get("body_excerpt") else "")
            for r in change.get("recent_releases", [])[:2]
        )
        or "  (none)"
    )

    criteria_text = "\n".join(
        f"  - {c['criterion']} (weight={c['weight']}): {c['description']}" for c in eval_case["scoring_criteria"]
    )

    prompt = _SCORE_PROMPT.format(
        eval_name=eval_case["name"],
        eval_description=eval_case["description"],
        eval_category=eval_case["category"],
        repo=change["repo"],
        repo_category=change["category"],
        tags=", ".join(change.get("tags", [])),
        repo_description=change.get("description", ""),
        commit_count=change["commit_count"],
        commits_text=commits_text or "  (no new commits)",
        releases_text=releases_text,
        criteria_text=criteria_text,
    )

    try:
        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=1024,
            thinking={"type": "adaptive"},
            system=[
                {
                    "type": "text",
                    "text": "You are an expert AI architect. Respond with valid JSON only.",
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
        # Strip markdown fences if present
        text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        result = json.loads(text)
        result["tokens"] = response.usage.input_tokens + response.usage.output_tokens
        return result
    except Exception as exc:
        return {"error": str(exc), "weighted_total": 0.0, "priority": "low"}


# ── Main ──────────────────────────────────────────────────────────────────────


def format_high_priority_text(eval_results: dict) -> str:
    """Format high-priority eval results for display / prompts."""
    lines = []
    for item in eval_results.get("high_priority", [])[:8]:
        lines.append(f"  {item['repo']} (score={item['score']:.2f}): {item.get('suggestion', '')}")
    return "\n".join(lines) if lines else "No high-priority items."


def run_evals(changes_file: Path) -> dict:
    if not _SDK_OK:
        print("anthropic not installed — run: pip install anthropic", file=sys.stderr)
        sys.exit(1)

    changes_data = json.loads(changes_file.read_text())
    eval_cases = json.loads(EVALS_FILE.read_text())
    client = _anthropic.Anthropic()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    results: dict = {
        "eval_date": today,
        "changes_file": str(changes_file.name),
        "total_repos_evaluated": 0,
        "high_priority": [],
        "medium_priority": [],
        "low_priority": [],
        "all_scores": [],
    }

    changes = changes_data.get("changes", [])
    if not changes:
        print("No changes to evaluate.")
        return results

    print(f"Evaluating {len(changes)} repos against {len(eval_cases)} eval cases...")

    for change in changes:
        repo = change["repo"]
        print(f"\n  {repo}")
        repo_scores = {"repo": repo, "category": change["category"], "evals": []}
        best_score = 0.0
        best_priority = "low"
        best_suggestion = ""

        for eval_case in eval_cases:
            print(f"    eval: {eval_case['name']}...", end=" ", flush=True)
            score = score_change_against_eval(change, eval_case, client)
            score["eval_id"] = eval_case["id"]
            score["eval_name"] = eval_case["name"]
            repo_scores["evals"].append(score)

            wt = score.get("weighted_total", 0.0)
            if wt > best_score:
                best_score = wt
                best_priority = score.get("priority", "low")
                best_suggestion = score.get("integration_suggestion", "")
            print(f"score={wt:.2f} [{score.get('priority', 'low')}]")

        repo_scores["best_score"] = best_score
        repo_scores["priority"] = best_priority
        repo_scores["top_integration_suggestion"] = best_suggestion
        results["all_scores"].append(repo_scores)
        results["total_repos_evaluated"] += 1

        bucket = results[f"{best_priority}_priority"]
        bucket.append(
            {
                "repo": repo,
                "score": best_score,
                "suggestion": best_suggestion,
                "tags": change.get("tags", []),
            }
        )

    out = CRAWLER_DIR / f"eval_results_{today}.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\nSaved: {out.name}")
    print(f"  High priority : {len(results['high_priority'])}")
    print(f"  Medium        : {len(results['medium_priority'])}")
    print(f"  Low           : {len(results['low_priority'])}")
    return results


def main() -> None:
    p = argparse.ArgumentParser(description="Run eval rubric against crawled changes")
    p.add_argument("--changes", help="Path to changes JSON (default: today's file)")
    args = p.parse_args()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    changes_file = Path(args.changes) if args.changes else CRAWLER_DIR / f"changes_{today}.json"

    if not changes_file.exists():
        print(f"Changes file not found: {changes_file}", file=sys.stderr)
        sys.exit(1)

    run_evals(changes_file)


if __name__ == "__main__":
    main()
