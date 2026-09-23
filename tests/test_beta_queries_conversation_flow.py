"""Multi-turn conversation, driven through the orchestrator — the seam.

`test_beta_queries_conversation.py` tests the dialogue layer with a context it
populates by hand, and `test_beta_queries_orchestrator.py` tests single turns.
Between them sat the bug this file exists to prevent: the orchestrator never
wrote back the metric or the user's filters, so every follow-up rebuilt a
question with no subject in it and routed to `out_of_scope`. Both suites were
green throughout.

A conversation is only testable as a conversation.
"""

from __future__ import annotations

import pytest
from beta_queries.context.model import ConversationContext

duckdb = pytest.importorskip("duckdb")
demo = pytest.importorskip("scripts.beta_queries_demo", reason="demo script")


@pytest.fixture
def orchestrator(tmp_path):
    path = str(tmp_path / "hr.duckdb")
    demo.build_database(path)
    orch, _ = demo.build(path)
    return orch


@pytest.fixture
def chat(orchestrator):
    ctx = ConversationContext(session_id="flow")

    def _ask(question: str):
        return orchestrator.ask(question, demo.ME, ctx), ctx

    return _ask


def _chip(ctx, column):
    return next((c for c in ctx.filters if c.column == column), None)


def test_first_turn_records_what_was_asked(chat):
    answer, ctx = chat("how many people are in india")

    assert answer.scenario == "new_topic"
    assert "2" in (answer.text or "")
    # Without these three the next turn has nothing to build on.
    assert ctx.metric, "no metric recorded — a follow-up cannot name the subject"
    assert ctx.last_plan_id
    country = _chip(ctx, "country_name")
    assert country is not None and country.value == "India"
    assert country.source == "question"


def test_row_level_security_never_becomes_a_chip(chat):
    """The asker's own RLS predicate must not be shown, or be removable.

    `employee.region = 'EMEA'` is injected by policy compilation. Surfaced as
    a chip it would disclose a filter nobody was told about, and `rewrite()`
    has a remove_filter op that would invite dropping it.
    """
    _, ctx = chat("how many people are in india")

    # Assert the harvest ran at all, or "no region chip" is trivially true.
    assert _chip(ctx, "country_name") is not None
    assert _chip(ctx, "region") is None
    labels = " ".join(c.label for c in ctx.filters)
    assert "EMEA" not in labels


def test_pivot_swaps_the_value_and_keeps_the_subject(chat):
    chat("how many people are in india")
    answer, ctx = chat("and in Germany?")

    assert answer.scenario == "pivot"
    # Replace, never AND: two filters on one column silently return nothing.
    country = _chip(ctx, "country_name")
    assert country is not None
    assert len([c for c in ctx.filters if c.column == "country_name"]) == 1


def test_a_narrowing_follow_up_keeps_the_standing_filters(chat):
    """'add a filter for X' — the case the whole feature exists for."""
    chat("how many people are in india")
    answer, ctx = chat("add a filter for active only")

    assert answer.scenario == "refine"
    assert _chip(ctx, "country_name") is not None, "narrowing dropped the subject"


def test_a_period_follow_up_is_not_a_value_swap(chat):
    """'what about last year' asked for country_name = 'last year' once."""
    chat("how many people are in india")
    _, ctx = chat("what about last year")

    country = _chip(ctx, "country_name")
    assert country is not None, "the period follow-up dropped the subject"
    assert country.value != "last year", "a date was swapped into a country column"


def test_reset_clears_the_standing_question(chat):
    _, ctx = chat("how many people are in india")
    assert [c for c in ctx.filters if c.source == "question"], "nothing was standing to reset"

    chat("forget that")
    assert not [c for c in ctx.filters if c.source == "question" and not c.pinned]
