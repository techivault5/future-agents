"""Answering while the metadata is still landing.

Blocking silently is the one option that is never right: a user cannot tell a
slow system from a broken one.
"""

from __future__ import annotations

import time

import pytest
from beta_queries.catalog.readiness import (
    FAILED,
    PARTIAL,
    PHASES,
    READY,
    Readiness,
    ReadinessStore,
    decide,
)
from beta_queries.context.model import ConversationContext
from beta_queries.memory.profile import DictKV
from beta_queries.progress import StepMachine

duckdb = pytest.importorskip("duckdb")
demo = pytest.importorskip("scripts.beta_queries_demo")


@pytest.fixture
def store() -> ReadinessStore:
    return ReadinessStore(DictKV())


def _mid_crawl(store, seen: int, total: int = 900, elapsed: float = 30.0) -> Readiness:
    store.begin("salesdb", tables_total=total)
    state = store.get("salesdb")
    state.started_at = time.time() - elapsed
    state.tables_seen = seen
    return store.put(state)


# ── the state machine ────────────────────────────────────────────────────────


def test_a_datasource_nobody_has_crawled_is_not_assumed_ready(store):
    assert decide(store.get("never-seen")).action == "queue"


def test_structure_alone_makes_a_source_usable(store):
    store.begin("salesdb")
    store.completed_phase("salesdb", "structure")
    state = store.get("salesdb")
    assert state.status == PARTIAL and state.can_route


def test_all_phases_make_it_ready(store):
    store.begin("salesdb")
    for phase in PHASES:
        store.completed_phase("salesdb", phase)
    assert store.get("salesdb").status == READY
    assert decide(store.get("salesdb")).action == "ready"


def test_a_failed_crawl_says_so_rather_than_looking_slow(store):
    store.failed("salesdb", "connection refused")
    decision = decide(store.get("salesdb"))
    assert decision.action == "failed" and store.get("salesdb").status == FAILED
    assert "connection refused" in decision.reason


# ── the estimate ─────────────────────────────────────────────────────────────


def test_an_eta_is_withheld_until_there_is_enough_to_measure(store):
    """A rate measured over a fraction of a second extrapolates to 'done
    already' and would tell a caller to wait for something barely started."""
    _mid_crawl(store, seen=5, elapsed=0.1)
    assert store.get("salesdb").eta_seconds() is None
    assert decide(store.get("salesdb")).action == "queue"


def test_an_eta_is_extrapolated_once_there_is(store):
    _mid_crawl(store, seen=60, total=900, elapsed=30.0)
    eta = store.get("salesdb").eta_seconds()
    assert eta and 350 < eta < 500  # 840 left at 2/s


# ── the three paths ──────────────────────────────────────────────────────────


def test_a_long_way_off_queues_the_question(store):
    _mid_crawl(store, seen=60)
    decision = decide(store.get("salesdb"))
    assert decision.action == "queue"
    assert not decision.can_answer


def test_nearly_done_waits_and_narrates(store):
    _mid_crawl(store, seen=890)
    decision = decide(store.get("salesdb"))
    assert decision.action == "wait" and decision.can_answer


def test_usable_but_incomplete_answers_with_a_caveat(store):
    _mid_crawl(store, seen=800)
    store.completed_phase("salesdb", "structure")
    decision = decide(store.get("salesdb"))
    assert decision.action == "partial"
    assert decision.can_answer
    assert "still reading" in decision.caveat


def test_a_multi_table_question_says_joins_are_not_mapped_yet(store):
    # Far enough from done that waiting is not an option.
    _mid_crawl(store, seen=400)
    store.completed_phase("salesdb", "structure")
    decision = decide(store.get("salesdb"), needs_joins=True)
    assert decision.action == "partial"
    assert "relate" in decision.caveat


def test_a_corrupt_state_reads_as_unknown_not_as_ready(store):
    store.kv.set("bq:readiness:salesdb", "{not json")
    assert decide(store.get("salesdb")).action == "queue"


# ── narration ────────────────────────────────────────────────────────────────


def test_a_running_step_can_report_progress_without_finishing():
    """A four-minute sync must not look frozen."""
    machine = StepMachine(
        config=[
            {
                "id": "sync",
                "running": "Syncing {datasource}…",
                "progress": "{seen} of ~{total} tables",
                "done": "{tables} tables",
            }
        ]
    )
    machine.start("sync", datasource="salesdb")
    machine.progress("sync", seen=412, total=900)
    assert machine.trace()[0]["detail"] == "412 of ~900 tables"
    assert machine.trace()[0]["state"] == "running"
    machine.done("sync", tables=900)
    assert machine.trace()[0]["state"] == "done"


def test_a_missing_placeholder_never_reaches_the_user_as_braces():
    machine = StepMachine(config=[{"id": "x", "running": "Running against {datasource}…"}])
    assert "{" not in machine.start("x").label


# ── end to end ───────────────────────────────────────────────────────────────


@pytest.fixture
def system(tmp_path):
    path = str(tmp_path / "hr.duckdb")
    demo.build_database(path)
    orchestrator, _ = demo.build(path)
    store = ReadinessStore(DictKV())
    orchestrator.readiness = store
    return orchestrator, store


def _ask(orchestrator):
    return orchestrator.ask(
        "how many people are in India?", demo.ME, ConversationContext(session_id=demo.ME)
    )


def test_a_question_asked_before_any_crawl_is_queued_not_answered_wrongly(system):
    orchestrator, _ = system
    answer = _ask(orchestrator)
    assert answer.error and answer.error["kind"] == "not_ready"
    assert "I'll let you know" in answer.text
    assert any(s["id"] == "sync" for s in answer.steps)


def test_a_partial_catalog_answers_and_says_it_is_partial(system):
    orchestrator, store = system
    store.begin("hrdb", tables_total=900)
    store.completed_phase("hrdb", "structure")
    state = store.get("hrdb")
    state.started_at = time.time() - 30
    state.tables_seen = 400  # far from done, so it answers rather than waits
    store.put(state)

    answer = _ask(orchestrator)
    assert answer.ok
    assert answer.text == "There are 2 active employees in India."
    assert any("still reading" in a["text"] for a in answer.assumptions)


def test_a_ready_catalog_narrates_no_sync_at_all(system):
    orchestrator, store = system
    store.begin("hrdb")
    for phase in PHASES:
        store.completed_phase("hrdb", phase)
    answer = _ask(orchestrator)
    assert answer.ok
    assert not any(s["id"].startswith("sync") for s in answer.steps)


def test_no_readiness_store_means_every_source_is_treated_as_ready(system):
    orchestrator, _ = system
    orchestrator.readiness = None
    assert _ask(orchestrator).ok
