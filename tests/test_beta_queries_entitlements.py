"""Entitlements and the model provider — the two ends of the request.

Entitlements decide what the model is even allowed to know about; the provider
is the one place a key could leak. Both are asserted concretely because both
fail silently when they fail.
"""

from __future__ import annotations

import json

import pytest
from beta_queries.agent.providers import (
    AnthropicProvider,
    Completion,
    EchoProvider,
    LunaProvider,
    parse_plan,
)
from beta_queries.entitlements.resolver import (
    CachedEntitlements,
    InMemoryEntitlements,
    Mask,
    RowFilter,
)
from beta_queries.memory.profile import DictKV

ME = "a@example.com"


def _resolver(**kw) -> InMemoryEntitlements:
    base = {
        "grants": {ME: {"hr.dbo.employee", "hr.dbo.salary", "hr.dbo.department"}},
        "denies": {ME: {"hr.dbo.salary"}},
    }
    base.update(kw)
    return InMemoryEntitlements(**base)


# ── grants ───────────────────────────────────────────────────────────────────


def test_deny_beats_allow():
    """Two groups, one granting and one denying, must deny.

    Any other resolution order turns joining a group into a way of widening
    access.
    """
    grants = _resolver().resolve(ME)
    assert "hr.dbo.salary" not in grants.tables
    assert grants.may_read("hr.dbo.employee")


def test_relnames_are_scoped_to_one_datasource():
    grants = _resolver(grants={ME: {"hr.dbo.employee", "sales.dbo.orders"}}, denies={}).resolve(ME)
    assert grants.entitled_relnames("hr") == {"dbo.employee"}
    assert grants.datasources == {"hr", "sales"}


def test_nobody_gets_anything_by_default():
    assert InMemoryEntitlements().resolve("stranger@example.com").tables == set()


# ── the cache key ────────────────────────────────────────────────────────────


def test_two_people_with_identical_access_share_a_cache_key():
    a = InMemoryEntitlements(grants={"a": {"d.s.t"}}).resolve("a")
    b = InMemoryEntitlements(grants={"b": {"d.s.t"}}).resolve("b")
    assert a.hash() == b.hash()


def test_the_same_tables_behind_different_row_filters_never_share_a_plan():
    """Otherwise one person sees the other's rows out of a cache."""
    plain = InMemoryEntitlements(grants={"a": {"d.s.t"}}).resolve("a")
    filtered = InMemoryEntitlements(
        grants={"b": {"d.s.t"}},
        row_filters={"b": [RowFilter("d.s.t", "{alias}.region = 'EMEA'")]},
    ).resolve("b")
    assert plain.hash() != filtered.hash()


def test_a_mask_changes_the_cache_key_too():
    plain = InMemoryEntitlements(grants={"a": {"d.s.t"}}).resolve("a")
    masked = InMemoryEntitlements(
        grants={"b": {"d.s.t"}},
        masks={"b": [Mask("d.s.t", "salary", "aggregate_only")]},
    ).resolve("b")
    assert plain.hash() != masked.hash()


def test_a_policy_filter_is_never_presented_as_the_users_to_remove():
    grants = _resolver(
        row_filters={ME: [RowFilter("hr.dbo.employee", "{alias}.region = 'EMEA'")]}
    ).resolve(ME)
    assert grants.filters_for("hr.dbo.employee")[0].source == "policy"


def test_an_aggregate_only_mask_says_so():
    assert Mask("t", "salary", "aggregate_only").aggregate_only
    assert not Mask("t", "salary", "redact").aggregate_only


# ── the snapshot ─────────────────────────────────────────────────────────────


def test_the_snapshot_round_trips_every_field():
    inner = _resolver(
        row_filters={ME: [RowFilter("hr.dbo.employee", "x = 1", "your region")]},
        masks={ME: [Mask("hr.dbo.employee", "salary", "aggregate_only")]},
        denied_columns={ME: {"hr.dbo.employee.ssn"}},
    )
    cached = CachedEntitlements(inner, DictKV())
    first = cached.resolve(ME)
    second = cached.resolve(ME)  # served from the snapshot this time
    assert second.hash() == first.hash()
    assert second.denied_columns == {"hr.dbo.employee.ssn"}
    assert second.masks[0].strategy == "aggregate_only"


def test_a_revoked_grant_can_be_dropped_without_waiting_for_the_ttl():
    kv = DictKV()
    inner = _resolver()
    cached = CachedEntitlements(inner, kv)
    assert cached.resolve(ME).may_read("hr.dbo.employee")

    inner.grants[ME] = set()
    assert cached.resolve(ME).may_read("hr.dbo.employee")  # still snapshotted
    cached.invalidate(ME)
    assert not cached.resolve(ME).may_read("hr.dbo.employee")


def test_a_corrupt_snapshot_resolves_properly_rather_than_widening_access():
    kv = DictKV()
    cached = CachedEntitlements(_resolver(), kv)
    cached.resolve(ME)
    # Overwrite the snapshot with junk, as a partial write or a format change
    # would. It must fall back to the real resolver, not to "no restrictions".
    for key in list(kv._data):
        kv.set(key, "{not json")
    grants = cached.resolve(ME)
    assert grants.may_read("hr.dbo.employee")
    assert "hr.dbo.salary" not in grants.tables


def test_the_raw_identity_is_never_the_snapshot_key():
    kv = DictKV()
    CachedEntitlements(_resolver(), kv).resolve(ME)
    assert all("example.com" not in key for key in kv._data)


def test_the_graph_resolver_builds_a_grant_set_from_a_traversal():
    from beta_queries.entitlements.resolver import GraphEntitlements

    rows = [
        {
            "fqn": "hr.dbo.employee",
            "row_filter": "{alias}.region = 'EMEA'",
            "filter_reason": "your region only",
            "denied_columns": ["ssn"],
            "masks": [{"column": "salary", "strategy": "aggregate_only"}],
        }
    ]
    grants = GraphEntitlements(lambda cypher, params: rows).resolve(ME)
    assert grants.tables == {"hr.dbo.employee"}
    assert grants.denied_columns == {"hr.dbo.employee.ssn"}
    assert grants.masks[0].aggregate_only
    assert grants.row_filters[0].rationale == "your region only"


# ── the provider ─────────────────────────────────────────────────────────────


def test_the_offline_provider_plans_from_the_prompts_own_context():
    prompt = "datasource: hrdb\ndialect: duckdb\ntables:\n  - table: hrdb.dbo.employee\n"
    plan = parse_plan(EchoProvider().complete("sys", prompt).text)
    assert plan.datasource_id == "hrdb"
    assert plan.sql and "dbo.employee" in plan.sql
    assert plan.render_answer({"n": 4812}) == "There are 4,812 rows."


def test_the_offline_provider_clarifies_when_it_has_nothing_to_go_on():
    plan = parse_plan(EchoProvider().complete("sys", "no context at all").text)
    assert plan.sql is None and plan.clarification is not None


def test_a_canned_plan_can_be_pinned_for_a_test():
    canned = {
        "datasource_id": "d",
        "dialect": "duckdb",
        "intent": "lookup",
        "confidence": 0.9,
        "sql": "SELECT 1 AS n",
        "referenced_tables": ["t"],
        "answer_template": "{{n}}",
    }
    provider = EchoProvider(plans={"headcount": canned})
    # Matched against the `question:` line only: the prompt also carries the
    # conversation history, and matching the whole thing lets a previous
    # turn's question silently select this turn's plan.
    prompt = "datasource: d\ndialect: duckdb\n\nquestion: what is headcount"
    assert parse_plan(provider.complete("s", prompt).text).sql == "SELECT 1 AS n"


def test_a_previous_turns_question_does_not_select_this_turns_plan():
    canned = {
        "datasource_id": "d", "dialect": "duckdb", "intent": "lookup",
        "confidence": 0.9, "sql": "SELECT 1 AS n", "referenced_tables": ["t"],
        "answer_template": "{{n}}",
    }
    provider = EchoProvider(plans={"headcount": canned})
    prompt = (
        "datasource: d\ndialect: duckdb\n"
        "conversation so far:\n what is headcount\n\n"
        "question: something else entirely"
    )
    assert parse_plan(provider.complete("s", prompt).text).sql != "SELECT 1 AS n"


def test_code_fences_do_not_break_the_parse():
    payload = {
        "datasource_id": "d",
        "dialect": "duckdb",
        "intent": "lookup",
        "confidence": 0.5,
        "sql": "SELECT 1 AS n",
        "referenced_tables": ["t"],
        "answer_template": "{{n}}",
    }
    assert parse_plan("```json\n" + json.dumps(payload) + "\n```").sql == "SELECT 1 AS n"


def test_a_model_that_narrates_before_the_json_still_parses():
    payload = {
        "datasource_id": "d",
        "dialect": "duckdb",
        "intent": "lookup",
        "confidence": 0.5,
        "sql": "SELECT 1 AS n",
        "referenced_tables": ["t"],
        "answer_template": "{{n}}",
    }
    text = "Here is the plan you asked for:\n" + json.dumps(payload)
    assert parse_plan(text).sql == "SELECT 1 AS n"


def test_unparseable_output_says_what_it_actually_got():
    with pytest.raises(ValueError, match="no JSON object"):
        parse_plan("I'm afraid I can't do that.")


def test_a_truncated_completion_is_not_a_plan():
    # Half a SQL statement that happens to parse is the worst possible outcome.
    assert Completion(text="{", stop_reason="max_tokens").truncated
    assert not Completion(text="{}", stop_reason="stop").truncated


@pytest.mark.parametrize("provider", [LunaProvider(), AnthropicProvider()])
def test_a_provider_never_holds_a_key(provider):
    """A provider that stores a key is a provider that leaks one in a traceback."""
    state = json.dumps(provider.__dict__, default=str).lower()
    assert "key" not in state or "key_env" in state
    assert "sk-" not in state and "bearer" not in state


def test_a_missing_key_is_a_clear_error_not_a_silent_failure(monkeypatch):
    monkeypatch.delenv("LUNA_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="LUNA_API_KEY"):
        LunaProvider(base_url="https://example.invalid").complete("s", "u")
