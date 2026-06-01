"""15 tests for the standalone token_saver.py — imports only that single file.

All tests run without an ANTHROPIC_API_KEY; the Anthropic client is mocked.
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest

# ── Import the standalone file directly (as if it was dropped into any project) ─
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import token_saver as ts
from token_saver import TokenSaverAgent


# ── Shared helpers ────────────────────────────────────────────────────────────


def _mock_response(answer: str, tokens: int):
    block = types.SimpleNamespace(type="text", text=answer)
    usage = types.SimpleNamespace(input_tokens=tokens // 2, output_tokens=tokens // 2)
    return types.SimpleNamespace(content=[block], usage=usage)


def _inject(agent: TokenSaverAgent, answer: str, tokens: int = 30) -> None:
    """Inject a mock Anthropic client and enable the SDK flag."""
    agent._client = types.SimpleNamespace(
        messages=types.SimpleNamespace(create=lambda **kw: _mock_response(answer, tokens))
    )
    ts._SDK_OK = True


@pytest.fixture(autouse=True)
def _restore_sdk():
    yield
    ts._SDK_OK = False


@pytest.fixture
def agent(tmp_path):
    return TokenSaverAgent(memory_file=tmp_path / "memory.json")


# ── Test 1: brand-new agent has empty stats ───────────────────────────────────


def test_01_empty_stats(agent):
    s = agent.stats()
    assert s["cached_entries"] == 0
    assert s["tokens_used"] == 0
    assert s["tokens_saved"] == 0
    assert s["savings_pct"] == 0.0
    assert s["total_hits"] == 0


# ── Test 2: list_cached on empty agent returns [] ─────────────────────────────


def test_02_list_cached_empty(agent):
    assert agent.list_cached() == []


# ── Test 3: clear on empty agent returns 0 ───────────────────────────────────


def test_03_clear_empty(agent):
    assert agent.clear() == 0


# ── Test 4: fresh call returns the correct answer ────────────────────────────


def test_04_fresh_call_returns_answer(agent):
    _inject(agent, "Paris", tokens=20)
    r = agent.ask("Capital of France?")
    assert r.answer == "Paris"
    assert r.cached is False
    assert r.tokens == 20
    assert r.savings == 0


# ── Test 5: fresh call stores result in cache ────────────────────────────────


def test_05_fresh_call_stores_to_cache(agent):
    _inject(agent, "42", tokens=10)
    agent.ask("Answer to life?")
    assert agent.stats()["cached_entries"] == 1


# ── Test 6: exact-match hit uses zero tokens ─────────────────────────────────


def test_06_exact_cache_hit_zero_tokens(agent):
    _inject(agent, "Python", tokens=15)
    agent.ask("Best language?")

    r = agent.ask("Best language?")  # identical
    assert r.cached is True
    assert r.tokens == 0


# ── Test 7: exact-match hit reports correct savings ──────────────────────────


def test_07_exact_cache_savings_equals_original_tokens(agent):
    _inject(agent, "ruff", tokens=18)
    agent.ask("Best linter?")

    r = agent.ask("Best linter?")
    assert r.savings == 18


# ── Test 8: hit_count increments on each cache hit ───────────────────────────


def test_08_hit_count_increments(agent):
    _inject(agent, "yes", tokens=8)
    agent.ask("Does Python GIL exist?")

    agent.ask("Does Python GIL exist?")
    agent.ask("Does Python GIL exist?")

    entries = agent.list_cached()
    assert entries[0]["hit_count"] == 2


# ── Test 9: fuzzy match ≥ 80% keyword overlap is a cache hit ─────────────────


def test_09_fuzzy_hit_on_near_duplicate(agent):
    _inject(agent, "Use ruff.", tokens=12)
    agent.ask("Best Python linter to use?")

    # Shares {best, python, linter, use} / adds {2024} → 4/5 = 80%
    r = agent.ask("Best Python linter to use in 2024?")
    assert r.cached is True
    assert r.tokens == 0
    assert "[~cached" in r.answer


# ── Test 10: fuzzy below threshold is a cache miss ───────────────────────────


def test_10_fuzzy_miss_on_unrelated_question(agent):
    _inject(agent, "Recursion: function calls itself.", tokens=10)
    agent.ask("Explain recursion in programming")

    _inject(agent, "JWT tokens", tokens=10)
    r = agent.ask("How does OAuth authentication work?")
    assert r.cached is False


# ── Test 11: force_fresh bypasses exact cache ────────────────────────────────


def test_11_force_fresh_ignores_cache(agent):
    _inject(agent, "First answer", tokens=10)
    agent.ask("Same question")

    _inject(agent, "Second answer", tokens=10)
    r = agent.ask("Same question", force_fresh=True)
    assert r.cached is False
    assert r.answer == "Second answer"


# ── Test 12: forget() removes a specific entry ───────────────────────────────


def test_12_forget_removes_entry(agent):
    _inject(agent, "meow", tokens=5)
    agent.ask("Do cats purr?")
    assert agent.stats()["cached_entries"] == 1

    removed = agent.forget("Do cats purr?")
    assert removed is True
    assert agent.stats()["cached_entries"] == 0


# ── Test 13: forget() returns False for unknown question ─────────────────────


def test_13_forget_nonexistent_returns_false(agent):
    assert agent.forget("A question that was never asked") is False


# ── Test 14: memory persists across agent instances ──────────────────────────


def test_14_persistence_across_instances(tmp_path):
    mem = tmp_path / "shared.json"

    a1 = TokenSaverAgent(memory_file=mem)
    _inject(a1, "3.11", tokens=9)
    a1.ask("Current Python version?")

    # New instance — reads same file
    a2 = TokenSaverAgent(memory_file=mem)
    r = a2.ask("Current Python version?")
    assert r.cached is True
    assert r.tokens == 0


# ── Test 15: savings_pct is calculated correctly ─────────────────────────────


def test_15_savings_percentage(agent):
    _inject(agent, "ok", tokens=100)
    agent.ask("Question A")  # 100 tokens used
    agent.ask("Question A")  # 100 saved (hit 1)
    agent.ask("Question A")  # 100 saved (hit 2)

    s = agent.stats()
    assert s["tokens_used"] == 100
    assert s["tokens_saved"] == 200
    # 200 / (100 + 200) = 66.7 %
    assert s["savings_pct"] == pytest.approx(66.7, abs=0.5)


# ── Bonus: clear() returns correct count ──────────────────────────────────────


def test_16_clear_returns_count(agent):
    _inject(agent, "a", tokens=5)
    agent.ask("Q1?")
    agent.ask("Q2?")
    agent.ask("Q3?")
    assert agent.clear() == 3
    assert agent.stats()["cached_entries"] == 0


# ── Bonus: list_cached truncates long questions ───────────────────────────────


def test_17_list_cached_truncates_long_question(agent):
    long_q = "x" * 200
    _inject(agent, "short answer", tokens=5)
    agent.ask(long_q)

    rows = agent.list_cached()
    assert len(rows) == 1
    assert rows[0]["question"].endswith("…")
    assert len(rows[0]["question"]) == 81  # 80 chars + ellipsis
