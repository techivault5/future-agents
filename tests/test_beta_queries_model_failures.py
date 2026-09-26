"""The model call: retried when it should be, and honest when it fails.

"The LLM stops responding" was never the model stopping. The call timed out at
8 seconds, or truncated at 1500 tokens, was not retried, and every kind of
failure reached the user as "I couldn't turn that into a query I'd trust" —
which sends them off rephrasing a question that was fine.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from beta_queries.agent import planner
from beta_queries.agent.prompts import SchemaCard
from beta_queries.agent.providers import Completion

GOOD = (
    '{"datasource_id": "hrdb", "dialect": "duckdb", "intent": "aggregate_count",'
    ' "confidence": 0.9, "sql": "SELECT COUNT(*) AS n FROM main.t_emp_m",'
    ' "referenced_tables": ["main.t_emp_m"], "answer_template": "{{n}}"}'
)
CARDS = [SchemaCard(fqn="hrdb.main.t_emp_m", columns=[("emp_id", "INTEGER")])]


class Scripted:
    """Raises or answers in order, and counts how often it was asked."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def complete(self, system, user, **kw):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(planner, "TRANSPORT_BACKOFF_SECONDS", 0, raising=False)


def _plan(provider):
    return planner.plan_query(
        "how many", "hrdb", "duckdb", CARDS, provider, entitled={"hrdb.main.t_emp_m"}
    )


def test_a_transport_failure_is_retried_once_and_then_succeeds():
    provider = Scripted(TimeoutError("timed out"), Completion(text=GOOD))
    result = _plan(provider)
    assert result.ok and provider.calls == 2


def test_a_transport_failure_is_retried_once_and_only_once():
    provider = Scripted(TimeoutError("timed out"), TimeoutError("timed out"), Completion(GOOD))
    result = _plan(provider)
    assert not result.ok
    assert provider.calls == 2, "a second retry costs double for the same odds"
    assert result.failure == "timeout"


def test_a_rejected_key_is_not_retried():
    provider = Scripted(RuntimeError("LUNA_API_KEY is not set"), Completion(text=GOOD))
    result = _plan(provider)
    assert result.failure == "auth" and provider.calls == 1


def test_a_truncated_reply_is_named_as_such():
    result = _plan(Scripted(Completion(text=GOOD[:40], stop_reason="length")))
    assert result.failure == "truncated"


def _limits(env: dict[str, str]) -> tuple[float, int]:
    """Read the limits in a fresh interpreter.

    Reloading the module in-process would swap its classes out from under
    every other test that already imported them — a failure that shows up
    later, somewhere else, looking random.
    """
    root = Path(__file__).resolve().parents[1]
    code = (
        "import sys; sys.path[:0] = ['apps', 'packages']\n"
        "from beta_queries.agent import providers as p\n"
        "print(p.DEFAULT_TIMEOUT, p.DEFAULT_MAX_TOKENS)"
    )
    clean = {k: v for k, v in os.environ.items() if not k.startswith("BQ_LLM_")}
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        env={**clean, **env},
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return float(out[0]), int(out[1])


def test_the_limits_are_generous_by_default():
    timeout, max_tokens = _limits({})
    assert timeout >= 30, "8 s was a latency policy enforced as a correctness rule"
    assert max_tokens >= 4000, "1500 truncated a long statement plus its template"


def test_the_limits_are_overridable_from_the_environment():
    assert _limits({"BQ_LLM_TIMEOUT_SECONDS": "90", "BQ_LLM_MAX_TOKENS": "8000"}) == (90.0, 8000)


def test_a_malformed_override_falls_back_rather_than_crashing():
    timeout, _ = _limits({"BQ_LLM_TIMEOUT_SECONDS": "ninety"})
    assert timeout >= 30


def test_a_failed_model_call_tells_the_user_why(tmp_path, monkeypatch):
    """Not "rephrase your question" — the question was never the problem."""
    duckdb = pytest.importorskip("duckdb")
    demo = pytest.importorskip("scripts.beta_queries_demo")
    path = str(tmp_path / "hr.duckdb")
    demo.build_database(path)
    orchestrator, _ = demo.build(path)
    orchestrator.provider = Scripted(TimeoutError("timed out"), TimeoutError("timed out"))

    answer = orchestrator.ask("how many people are in india", demo.ME)
    assert answer.scenario == "model_unavailable"
    assert "BQ_LLM_TIMEOUT_SECONDS" in answer.text
    assert answer.error and answer.error["kind"] == "timeout"
    assert duckdb
