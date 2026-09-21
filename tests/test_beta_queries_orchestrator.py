"""The whole pipeline, against a real database.

These are the tests that would have caught every bug the first end-to-end run
found — which is the argument for having built the demo before the unit tests
for this layer.
"""

from __future__ import annotations

import pytest
from beta_queries.context.model import ConversationContext

duckdb = pytest.importorskip("duckdb")

demo = pytest.importorskip("scripts.beta_queries_demo", reason="demo script")


@pytest.fixture
def system(tmp_path):
    path = str(tmp_path / "hr.duckdb")
    demo.build_database(path)
    orchestrator, graph = demo.build(path)
    return orchestrator, graph


@pytest.fixture
def ask(system):
    orchestrator, _ = system

    def _ask(question: str, ctx: ConversationContext | None = None):
        return orchestrator.ask(question, demo.ME, ctx or ConversationContext(session_id=demo.ME))

    return _ask


# ── the happy path ───────────────────────────────────────────────────────────


def test_a_question_is_answered_end_to_end(ask):
    answer = ask("how many people are in India?")
    assert answer.ok
    assert answer.rows == [(2,)]
    assert answer.text == "There are 2 active employees in India."


def test_the_catalog_default_is_enforced_not_merely_suggested(ask):
    """India has three employees and two of them are active.

    The model's SQL carried no status filter. Answering 3 while calling them
    "active" is the confident wrong number this whole system exists to stop,
    so the default is injected by the compiler rather than hoped for.
    """
    answer = ask("how many people are in India?")
    assert "\"Status\" = 'ACTIVE'" in answer.sql
    assert answer.rows == [(2,)]
    assert any("catalog default" in a["text"] for a in answer.assumptions)


def test_row_level_security_is_injected_every_time(ask):
    answer = ask("how many people are in India?")
    assert "region = 'EMEA'" in answer.sql


def test_the_answer_is_rendered_from_a_template_not_a_second_model_call(ask):
    answer = ask("how many people are in India?")
    assert answer.llm_calls == 1


# ── the reported bug ─────────────────────────────────────────────────────────


def test_a_column_with_a_space_is_resolved_and_quoted(ask):
    """The model writes `report_id`; the column is `report id`."""
    answer = ask("show me every report id")
    assert answer.ok
    assert '"report id"' in answer.sql
    assert answer.rows == [(1,), (2,), (4,)]


def test_the_answer_template_survives_the_column_being_renamed(ask):
    # The template says {{report_id}}; the result column is `report id`.
    answer = ask("show me every report id")
    assert "{{" not in answer.text


# ── refusals ─────────────────────────────────────────────────────────────────


def test_a_view_earns_the_view_answer_not_a_generic_one(ask):
    answer = ask("headcount from the view")
    assert answer.scenario == "view_not_queryable"
    assert "is a view" in answer.text
    assert "employee" in answer.text  # and it names what to use instead


def test_an_aggregate_only_column_can_be_averaged(ask):
    answer = ask("what is the average salary")
    assert answer.ok and answer.rows


def test_the_same_column_row_by_row_is_refused(ask):
    answer = ask("list every salary")
    assert not answer.ok or answer.scenario == "policy_blocked"
    assert "aggregate" in answer.text.lower()


def test_a_write_never_reaches_the_model(ask):
    answer = ask("delete all employees")
    assert answer.scenario == "unsupported_write"
    assert answer.llm_calls == 0


def test_a_greeting_never_reaches_the_model(ask):
    answer = ask("hi")
    assert answer.scenario == "greeting"
    assert answer.llm_calls == 0 and answer.sql is None


def test_off_topic_is_deflected_before_anything_else_runs(ask):
    answer = ask("what is the weather in Paris")
    assert answer.scenario == "chitchat"
    assert answer.llm_calls == 0


def test_a_data_question_nothing_covers_says_so_rather_than_guessing(ask):
    answer = ask("how many spacecraft did we launch")
    assert answer.scenario == "out_of_scope"
    assert answer.llm_calls == 0
    assert answer.suggestions  # never a dead end


# ── narration ────────────────────────────────────────────────────────────────


def test_every_stage_is_narrated_with_no_unfilled_placeholders(ask):
    answer = ask("how many people are in India?")
    labels = [s["label"] for s in answer.steps]
    details = [s.get("detail", "") for s in answer.steps]
    assert len(labels) >= 7
    for text in labels + details:
        assert "{" not in text, f"unfilled placeholder in narration: {text!r}"


def test_a_failed_stage_is_narrated_as_failed(ask):
    answer = ask("headcount from the view")
    assert any(s["state"] == "failed" for s in answer.steps)


def test_the_panel_shows_what_was_applied(ask):
    ctx = ConversationContext(session_id=demo.ME)
    ask("how many people are in India?", ctx)
    panel = ctx.to_panel()
    assert panel["source"] == "hrdb"
    assert any("ACTIVE" in f["label"] for f in panel["filters"])


# ── two-layer errors ─────────────────────────────────────────────────────────


def test_a_failure_carries_both_a_business_and_a_technical_explanation(system):
    """A person who gets `Invalid column name 'x'` learns nothing actionable.
    A person who gets "something went wrong" learns less."""
    from beta_queries.agent.providers import EchoProvider

    orchestrator, _ = system
    orchestrator.provider = EchoProvider(
        plans={
            "broken": {
                "datasource_id": "hrdb",
                "dialect": "duckdb",
                "intent": "lookup",
                "confidence": 0.9,
                "sql": "SELECT no_such_column FROM main.employee",
                "referenced_tables": ["main.employee"],
                "answer_template": "{{n}}",
            }
        }
    )
    answer = orchestrator.ask(
        "broken question about employee status", demo.ME, ConversationContext(session_id=demo.ME)
    )
    assert answer.error is not None
    assert answer.error["business"] and answer.error["technical"]
    # Business language: no error codes, no raw identifiers.
    assert "no_such_column" not in answer.error["business"]
    # Technical: the engine's own words, verbatim.
    assert "no_such_column" in answer.error["technical"]
    assert answer.error["what_the_system_is_doing"]


def test_a_rejection_before_execution_also_carries_both_layers(ask):
    """Nothing threw, so the technical layer is our own reason — which is the
    honest thing to say: this was our decision, not the database's."""
    answer = ask("list every salary")
    assert answer.error is not None
    assert answer.error["stage"] == "guard"
    assert "row by row" in answer.error["technical"]
    assert answer.error["what_the_system_is_doing"] == "No query was executed."
