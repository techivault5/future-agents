"""Tests for the AI crawler pipeline — no network, no API key required."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from ai_crawler.crawl import load_state, save_state  # noqa: E402
from ai_crawler.eval_runner import format_high_priority_text  # noqa: E402
from ai_crawler.idea_generator import (  # noqa: E402
    format_all_changes,
    format_high_priority,
    load_prior_ideas,
    save_idea_titles,
)

EVALS_FILE = ROOT / "tests" / "evals" / "eval_cases.json"
REPOS_FILE = ROOT / "scripts" / "ai_crawler" / "repos.json"


# ── repos.json validation ─────────────────────────────────────────────────────


def test_repos_json_loads():
    data = json.loads(REPOS_FILE.read_text())
    assert "categories" in data
    assert "version" in data


def test_repos_json_has_minimum_count():
    data = json.loads(REPOS_FILE.read_text())
    total = sum(len(v) for v in data["categories"].values())
    assert total >= 40, f"Expected ≥40 repos, got {total}"


def test_repos_json_entries_have_required_fields():
    data = json.loads(REPOS_FILE.read_text())
    for cat, entries in data["categories"].items():
        for entry in entries:
            assert "owner" in entry, f"{cat}: missing owner"
            assert "repo" in entry, f"{cat}: missing repo"
            assert "description" in entry, f"{cat}: missing description"


def test_repos_json_has_key_categories():
    data = json.loads(REPOS_FILE.read_text())
    cats = set(data["categories"].keys())
    required = {"agent_frameworks", "llm_sdks", "rag_and_vector", "eval_frameworks"}
    assert required.issubset(cats), f"Missing categories: {required - cats}"


def test_repos_json_contains_known_repos():
    data = json.loads(REPOS_FILE.read_text())
    all_slugs = {
        f"{e['owner']}/{e['repo']}" for entries in data["categories"].values() for e in entries
    }
    must_have = {"crewAIInc/crewAI", "microsoft/autogen", "langchain-ai/langchain"}
    for slug in must_have:
        assert slug in all_slugs, f"Missing expected repo: {slug}"


# ── eval_cases.json validation ────────────────────────────────────────────────


def test_eval_cases_loads():
    cases = json.loads(EVALS_FILE.read_text())
    assert isinstance(cases, list)
    assert len(cases) >= 8


def test_eval_cases_have_required_fields():
    cases = json.loads(EVALS_FILE.read_text())
    for case in cases:
        assert "id" in case
        assert "name" in case
        assert "category" in case
        assert "scoring_criteria" in case
        assert isinstance(case["scoring_criteria"], list)
        assert len(case["scoring_criteria"]) >= 2


def test_eval_case_weights_sum_to_one():
    cases = json.loads(EVALS_FILE.read_text())
    for case in cases:
        total = sum(c["weight"] for c in case["scoring_criteria"])
        assert abs(total - 1.0) < 0.01, f"Case '{case['id']}': weights sum to {total:.3f}"


def test_eval_cases_cover_required_categories():
    cases = json.loads(EVALS_FILE.read_text())
    cats = {c["category"] for c in cases}
    required = {"token_efficiency", "agent_patterns", "novelty"}
    assert required.issubset(cats)


# ── crawl.py unit tests ───────────────────────────────────────────────────────


def test_state_round_trip(tmp_path):
    state = {"last_crawl": "2026-05-24", "seen_shas": {"a/b": ["abc"]}, "repo_meta": {}}
    state_file = tmp_path / "state.json"

    with patch("ai_crawler.crawl.STATE_FILE", state_file):
        save_state(state)
        loaded = load_state()

    assert loaded["last_crawl"] == "2026-05-24"
    assert loaded["seen_shas"]["a/b"] == ["abc"]


def test_load_state_missing_file(tmp_path):
    with patch("ai_crawler.crawl.STATE_FILE", tmp_path / "nonexistent.json"):
        state = load_state()
    assert state["last_crawl"] is None
    assert state["seen_shas"] == {}


def test_load_state_corrupt_file(tmp_path):
    f = tmp_path / "state.json"
    f.write_text("{corrupt json")
    with patch("ai_crawler.crawl.STATE_FILE", f):
        state = load_state()
    assert state["last_crawl"] is None


# ── idea_generator.py unit tests ──────────────────────────────────────────────


def test_idea_memory_round_trip(tmp_path):
    mem = tmp_path / "idea_memory.json"
    with patch("ai_crawler.idea_generator.MEMORY_FILE", mem):
        save_idea_titles(["Idea Alpha", "Idea Beta"], "2026-05-24")
        prior = load_prior_ideas()
    assert any("Idea Alpha" in p for p in prior)
    assert any("Idea Beta" in p for p in prior)


def test_idea_memory_dedup_across_days(tmp_path):
    mem = tmp_path / "idea_memory.json"
    with patch("ai_crawler.idea_generator.MEMORY_FILE", mem):
        save_idea_titles(["Day 1 Idea"], "2026-05-23")
        save_idea_titles(["Day 2 Idea"], "2026-05-24")
        prior = load_prior_ideas()
    assert len(prior) == 2


def test_format_high_priority_empty():
    text = format_high_priority({"high_priority": []})
    assert "No high-priority" in text


def test_format_high_priority_with_items():
    eval_results = {
        "high_priority": [
            {
                "repo": "openai/evals",
                "score": 0.9,
                "suggestion": "Add to eval pipeline",
                "tags": ["evals"],
            },
        ]
    }
    text = format_high_priority(eval_results)
    assert "openai/evals" in text
    assert "0.90" in text


def test_format_all_changes_empty():
    text = format_all_changes({"changes": []})
    assert "No changes" in text


def test_format_all_changes_with_data():
    changes_data = {
        "changes": [
            {
                "repo": "crewAIInc/crewAI",
                "category": "agent_frameworks",
                "new_commits": [
                    {"date": "2026-05-24T06:00:00Z", "message": "feat: add parallel task execution"}
                ],
                "recent_releases": [],
            }
        ]
    }
    text = format_all_changes(changes_data)
    assert "crewAIInc/crewAI" in text
    assert "parallel task execution" in text


# ── eval_runner.py unit tests ─────────────────────────────────────────────────


def test_format_high_priority_text_from_runner():
    results = {
        "high_priority": [
            {
                "repo": "mem0ai/mem0",
                "score": 0.95,
                "suggestion": "Integrate with KnowledgeStore",
                "tags": ["memory"],
            },
            {
                "repo": "vllm-project/vllm",
                "score": 0.88,
                "suggestion": "Use for local inference",
                "tags": ["llm"],
            },
        ]
    }
    text = format_high_priority_text(results)
    assert "mem0ai/mem0" in text
    assert "vllm-project/vllm" in text
