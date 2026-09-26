"""Two-layer errors, and the redaction that keeps the technical one safe."""

from __future__ import annotations

import pytest
from beta_queries.errors.report import REDACTED, ErrorMessages
from beta_queries.sql.healing import diagnose


@pytest.fixture
def messages() -> ErrorMessages:
    return ErrorMessages.from_file("data/config/beta_queries_errors.yaml")


def _report(messages, message, dialect, entitled=(), audience="user"):
    return messages.build(
        diagnose(message, dialect),
        sql="SELECT 1",
        dialect=dialect,
        entitled_objects=entitled,
        audience=audience,
    )


# ── both layers ──────────────────────────────────────────────────────────────


def test_a_failure_says_it_twice(messages):
    report = _report(messages, 'column "employe_id" does not exist', "postgres", ["main.employee"])
    assert "employe_id" not in report.business  # business language, no identifiers
    assert "employe_id" in report.technical  # the engine's own words
    assert report.what_now  # and an acknowledgement


def test_the_technical_layer_carries_the_sql_too(messages):
    assert "SELECT 1" in _report(messages, "syntax error at or near SELCT", "postgres").technical


def test_an_unrecognised_error_still_gets_both_layers(messages):
    report = _report(messages, "something nobody has ever seen", "duckdb")
    assert report.kind == "unknown"
    assert report.business and "something nobody has ever seen" in report.technical


@pytest.mark.parametrize(
    "message,dialect",
    [
        ('column "x" does not exist', "postgres"),
        ("Statement reached its statement timeout", "snowflake"),
        ("division by zero", "postgres"),
        ('column "e.name" must appear in the GROUP BY clause', "postgres"),
    ],
)
def test_every_kind_has_words_of_its_own(messages, message, dialect):
    report = _report(messages, message, dialect)
    generic = messages.messages["unknown"]["business"]
    assert report.business != generic


# ── redaction ────────────────────────────────────────────────────────────────


def test_a_permission_failure_never_shows_the_engines_words(messages):
    report = _report(
        messages, "The SELECT permission was denied on the object 'exec_comp'", "sqlserver"
    )
    assert report.redacted
    assert report.technical == REDACTED
    assert "exec_comp" not in report.technical


def test_a_snowflake_not_found_on_an_unentitled_object_is_redacted(messages):
    """Snowflake merges denied into not-found on purpose, so nobody can probe
    for existence. Relaying it verbatim undoes that in the presentation layer."""
    report = _report(
        messages, "Object 'PAYROLL.EXEC_COMP' does not exist or not authorized.", "snowflake"
    )
    assert report.redacted
    assert "EXEC_COMP" not in report.technical


def test_the_same_error_about_an_entitled_object_is_shown_in_full(messages):
    # They already know this table exists — withholding it helps nobody.
    report = _report(
        messages,
        "Object 'MAIN.EMPLOYEE' does not exist or not authorized.",
        "snowflake",
        entitled=["main.employee"],
    )
    assert not report.redacted
    assert "MAIN.EMPLOYEE" in report.technical


def test_an_operator_sees_everything(messages):
    report = _report(
        messages,
        "The SELECT permission was denied on the object 'exec_comp'",
        "sqlserver",
        audience="operator",
    )
    assert not report.redacted
    assert "exec_comp" in report.technical


def test_an_ordinary_failure_is_never_redacted(messages):
    assert not _report(messages, "division by zero", "postgres").redacted


# ── what happens next ────────────────────────────────────────────────────────


def test_a_terminal_failure_is_not_offered_as_retryable(messages):
    for message in ("permission denied for table salary", "statement timeout"):
        assert not _report(messages, message, "postgres").retryable


def test_a_deterministic_failure_is_retryable(messages):
    assert _report(messages, 'column "x" does not exist', "postgres").retryable


def test_wording_comes_from_config_so_a_product_owner_owns_it():
    custom = ErrorMessages({"timeout": {"business": "Too big. Narrow it down."}})
    report = custom.build(diagnose("statement timeout", "postgres"))
    assert report.business == "Too big. Narrow it down."


def test_a_missing_kind_falls_back_rather_than_going_blank():
    report = ErrorMessages({}).build(diagnose("utterly unknown failure", "duckdb"))
    assert report.business.strip()
