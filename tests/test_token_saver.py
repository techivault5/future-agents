"""Tests for TokenSaverAgent — all run without an ANTHROPIC_API_KEY."""

from __future__ import annotations

import types

import pytest

from future_agents.agents.token_saver_agent import TokenSaverAgent


@pytest.fixture(autouse=True)
def _reset_sdk_flag():
    """Restore _SDK_AVAILABLE=False after each test that patches it to True."""
    yield
    import future_agents.agents.token_saver_agent as mod

    mod._SDK_AVAILABLE = False


@pytest.fixture
def agent(tmp_path):
    return TokenSaverAgent(memory_file=tmp_path / "memory.json")


def test_stats_empty(agent):
    s = agent.stats()
    assert s["cached_entries"] == 0
    assert s["tokens_used"] == 0
    assert s["tokens_saved"] == 0


def test_list_cached_empty(agent):
    assert agent.list_cached() == []


def test_clear_empty(agent):
    assert agent.clear() == 0


def _make_mock_response(answer: str, tokens: int = 42):
    """Build a mock Anthropic response object."""
    block = types.SimpleNamespace(type="text", text=answer)
    usage = types.SimpleNamespace(input_tokens=tokens // 2, output_tokens=tokens // 2)
    return types.SimpleNamespace(content=[block], usage=usage)


def _patch_client(agent, answer: str, tokens: int = 42):
    """Inject a mock Anthropic client into agent."""
    mock_client = types.SimpleNamespace(
        messages=types.SimpleNamespace(create=lambda **kw: _make_mock_response(answer, tokens))
    )
    import future_agents.agents.token_saver_agent as mod

    mod._SDK_AVAILABLE = True
    agent._client = mock_client


def test_fresh_call_stores_to_cache(agent, tmp_path):
    _patch_client(agent, "Paris", tokens=10)
    result = agent.ask("What is the capital of France?")
    assert result.answer == "Paris"
    assert result.cached is False
    assert result.tokens == 10
    assert agent.stats()["cached_entries"] == 1


def test_exact_cache_hit(agent):
    _patch_client(agent, "42", tokens=20)
    agent.ask("Answer to life?")

    # Second call — must be cached
    result = agent.ask("Answer to life?")
    assert result.cached is True
    assert result.tokens == 0
    assert result.savings == 20


def test_fuzzy_cache_hit(agent):
    _patch_client(agent, "Use ruff.", tokens=15)
    agent.ask("Best Python linter to use?")

    # Near-duplicate: shares {best, python, linter, use} / union adds {2024} → 80%
    result = agent.ask("Best Python linter to use in 2024?")
    assert result.cached is True
    assert result.tokens == 0


def test_fuzzy_no_hit_on_unrelated(agent):
    _patch_client(agent, "42", tokens=10)
    agent.ask("Explain recursion")

    _patch_client(agent, "JWT", tokens=10)
    result = agent.ask("How does authentication work?")
    assert result.cached is False


def test_force_fresh_bypasses_cache(agent):
    _patch_client(agent, "First", tokens=10)
    agent.ask("Same question")

    _patch_client(agent, "Second", tokens=10)
    result = agent.ask("Same question", force_fresh=True)
    assert result.cached is False
    assert result.answer == "Second"


def test_forget(agent):
    _patch_client(agent, "yes", tokens=5)
    agent.ask("Do cats purr?")
    assert agent.stats()["cached_entries"] == 1

    removed = agent.forget("Do cats purr?")
    assert removed is True
    assert agent.stats()["cached_entries"] == 0


def test_forget_unknown(agent):
    assert agent.forget("nonexistent question") is False


def test_persistence(tmp_path):
    mem = tmp_path / "memory.json"
    a1 = TokenSaverAgent(memory_file=mem)
    _patch_client(a1, "Python 3.11", tokens=8)
    a1.ask("What Python version?")

    # New agent instance loads same memory file
    a2 = TokenSaverAgent(memory_file=mem)
    result = a2.ask("What Python version?")
    assert result.cached is True


def test_stats_savings_pct(agent):
    _patch_client(agent, "ok", tokens=100)
    agent.ask("First question")
    agent.ask("First question")  # hit
    agent.ask("First question")  # hit

    s = agent.stats()
    assert s["tokens_saved"] == 200
    assert s["tokens_used"] == 100
    assert s["savings_pct"] == pytest.approx(66.7, abs=0.5)


def test_list_cached_shows_entries(agent):
    _patch_client(agent, "answer", tokens=5)
    agent.ask("What is 2+2?")
    entries = agent.list_cached()
    assert len(entries) == 1
    assert "What is 2+2?" in entries[0]["question"]
