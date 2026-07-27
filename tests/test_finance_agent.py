"""Agentic BYOK layer: tool wiring, the loop, and key handling."""

from __future__ import annotations

import json

import pytest
from finance_advisor.agent import (
    ProviderError,
    ProviderTurn,
    ToolCall,
    build_toolset,
    clear_session,
    get_history,
    get_provider,
    provider_catalog,
    resolve_key,
    run_agent,
)
from finance_advisor.agent.providers import _to_anthropic, _to_openai
from finance_advisor.agent.tools import MAX_RESULT_CHARS
from finance_advisor.memory import FinanceMemorySDK


@pytest.fixture
def sdk():
    return FinanceMemorySDK()


@pytest.fixture
def tools(sdk):
    return build_toolset(sdk)


class ScriptedProvider:
    """Replays canned turns so the loop runs with no network and no key."""

    label = "Scripted"
    key_env = ""
    requires_key = False

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    def complete(self, *, key, model, system, messages, tools, base_url="", **kw):
        self.calls.append({"key": key, "messages": list(messages), "tools": tools})
        return self.turns.pop(0)


def events(**kwargs):
    return list(run_agent(**kwargs))


# ── toolset ──────────────────────────────────────────────────────────────────


def test_every_tool_has_a_json_schema(tools):
    assert set(tools) >= {"recall_memory", "remember_fact", "run_skill", "market_snapshot"}
    for tool in tools.values():
        schema = tool.schema()
        assert schema["description"]
        assert schema["parameters"]["type"] == "object"


def test_remember_then_recall_round_trips(tools):
    tools["remember_fact"].run(content="take_home=180000", tags=["profile"])
    hits = tools["recall_memory"].run(query="what do I earn")["hits"]
    assert any("take_home" in h["content"] for h in hits)


def test_sensitive_memories_are_redacted_before_they_can_reach_a_provider(tools):
    tools["remember_fact"].run(content="hdfc_balance=942310", sensitive=True)
    hits = tools["recall_memory"].run(query="bank balance")["hits"]
    assert hits and all("942310" not in h["content"] for h in hits)


def test_run_skill_does_the_indian_tax_maths(tools):
    out = tools["run_skill"].run(
        skill="capital_gains", args={"buy_value": 400000, "sell_value": 600000, "months_held": 24}
    )
    assert "error" not in out
    assert json.dumps(out)  # serialisable for the wire


def test_unknown_skill_is_reported_not_raised(tools):
    out = tools["run_skill"].run(skill="astrology")
    assert "available" in out


def test_tool_failures_come_back_as_results(tools):
    from finance_advisor.agent import execute

    assert "error" in execute(tools, "nope", {})
    assert "error" in execute(tools, "recall_memory", {"bogus": 1})


# ── the loop ─────────────────────────────────────────────────────────────────


def test_single_turn_with_no_tools(tools):
    prov = ScriptedProvider([ProviderTurn(text="Pay the 22% card first.")])
    out = events(message="which debt first?", tools=tools, provider=prov)
    assert {"type": "text", "text": "Pay the 22% card first."} in out
    assert out[-1]["type"] == "done"


def test_loop_executes_a_tool_then_answers(tools):
    prov = ScriptedProvider(
        [
            ProviderTurn(
                tool_calls=[
                    ToolCall(
                        id="t1",
                        name="run_skill",
                        arguments={
                            "skill": "loans",
                            "args": {"principal": 3500000, "annual_rate_pct": 8.6, "months": 240},
                        },
                    )
                ]
            ),
            ProviderTurn(text="EMI is about ₹30,596."),
        ]
    )
    out = events(message="emi?", tools=tools, provider=prov)
    kinds = [e["type"] for e in out]
    assert kinds == ["tool_call", "tool_result", "text", "done"]
    # the result was fed back as a tool message the provider could see
    second_request = prov.calls[1]["messages"]
    assert second_request[-1]["role"] == "tool"
    assert second_request[-1]["tool_call_id"] == "t1"


def test_loop_stops_at_the_round_limit(tools):
    looping = [
        ProviderTurn(tool_calls=[ToolCall(id=f"t{i}", name="user_profile", arguments={})])
        for i in range(4)
    ]
    out = events(message="hi", tools=tools, provider=ScriptedProvider(looping), max_rounds=3)
    assert out[-1]["type"] == "error"
    assert "3 tool rounds" in out[-1]["message"]


def test_history_persists_across_turns_within_a_session(tools):
    session = "sess-test-1"
    clear_session(session)
    events(
        message="I earn 1.8L",
        tools=tools,
        provider=ScriptedProvider([ProviderTurn(text="noted")]),
        session=session,
    )
    prov = ScriptedProvider([ProviderTurn(text="still noted")])
    events(message="and?", tools=tools, provider=prov, session=session)
    assert prov.calls[0]["messages"][0]["content"] == "I earn 1.8L"
    assert clear_session(session) is True
    assert get_history(session) == []


def test_a_provider_error_ends_the_turn_cleanly(tools):
    class Broken(ScriptedProvider):
        def complete(self, **kw):
            raise ProviderError("Anthropic rejected the API key.")

    out = events(message="hi", tools=tools, provider=Broken([]))
    assert out == [{"type": "error", "message": "Anthropic rejected the API key."}]


def test_missing_key_is_refused_before_any_request_is_made(tools, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = events(message="hi", tools=tools, provider_name="anthropic")
    assert out[0]["type"] == "error"
    assert "API key" in out[0]["message"]


# ── providers ────────────────────────────────────────────────────────────────


def test_catalog_exposes_whether_a_key_exists_never_the_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-never-leak")
    catalog = provider_catalog()
    blob = json.dumps(catalog)
    assert "sk-ant-should-never-leak" not in blob
    anthropic = next(p for p in catalog if p["name"] == "anthropic")
    assert anthropic["server_key_available"] is True
    assert anthropic["default_model"] == "claude-opus-5"


def test_user_key_beats_the_server_env_var(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-key")
    prov = get_provider("anthropic")
    assert resolve_key(prov, "user-key") == "user-key"
    assert resolve_key(prov, "") == "server-key"


def test_ollama_needs_no_key():
    assert get_provider("ollama").requires_key is False


def test_unknown_provider_is_rejected():
    with pytest.raises(ProviderError):
        get_provider("skynet")


def test_anthropic_batches_consecutive_tool_results_into_one_user_message():
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "", "raw": [{"type": "tool_use", "id": "a"}]},
        {"role": "tool", "tool_call_id": "a", "name": "x", "content": "{}"},
        {"role": "tool", "tool_call_id": "b", "name": "y", "content": "{}"},
        {"role": "assistant", "content": "done"},
    ]
    out = _to_anthropic(msgs)
    assert [m["role"] for m in out] == ["user", "assistant", "user", "assistant"]
    assert len(out[2]["content"]) == 2
    # raw blocks (which carry thinking) are replayed verbatim
    assert out[1]["content"] == [{"type": "tool_use", "id": "a"}]


def test_openai_shape_serialises_tool_calls_as_json_strings():
    msgs = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [ToolCall(id="a", name="run_skill", arguments={"skill": "loans"})],
        },
        {"role": "tool", "tool_call_id": "a", "name": "run_skill", "content": "{}"},
    ]
    out = _to_openai("sys", msgs)
    assert out[0]["role"] == "system"
    assert json.loads(out[2]["tool_calls"][0]["function"]["arguments"]) == {"skill": "loans"}
    assert out[3]["role"] == "tool"


# ── prompt-token economy ─────────────────────────────────────────────────────


def test_market_snapshot_drops_chart_only_fields(tools):
    from finance_advisor.agent.tools import _compact_quote

    raw = {
        "key": "gold",
        "name": "Gold",
        "price": 118.6234,
        "sparkline": [1.0] * 30,
        "outlook": "",
        "signal": "dip-watch",
    }
    out = _compact_quote(raw)
    assert "sparkline" not in out and "key" not in out
    assert out["price"] == 118.62
    assert "outlook" not in out  # empty values are dropped too
    assert out["signal"] == "dip-watch"


def test_a_snapshot_fits_inside_the_tool_result_budget(tools):
    """It did not before: 30 floats per asset pushed it past the cap, and the
    model received truncated JSON it could not parse."""
    payload = json.dumps(tools["market_snapshot"].run(), default=str)
    assert len(payload) < MAX_RESULT_CHARS
