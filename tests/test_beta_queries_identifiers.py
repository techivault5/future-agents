"""Identifier resolution — the failure mode that produces working-looking SQL.

Every case here was a real report: SQL that parsed, passed the guard, and then
threw at the database because the identifier the model wrote is not the
identifier the catalog holds.
"""

from __future__ import annotations

import pytest
from beta_queries.sql.identifiers import (
    Catalog,
    case_rules,
    loose,
    repair_unparseable,
    rewrite_identifiers,
)

sqlglot = pytest.importorskip("sqlglot")

COLUMNS = {
    "dbo.reports": ["report id", "Status", "user", "created_at"],
    "dbo.report_owner": ["report id", "owner name"],
}


def _cat(dialect: str = "sqlserver") -> Catalog:
    return Catalog(COLUMNS, dialect=dialect)


# ── folding rules ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "dialect,fold",
    [
        ("snowflake", "upper"),
        ("postgres", "lower"),
        ("databricks", "lower"),
        ("sqlserver", "preserve"),
        ("mysql", "preserve"),
        ("duckdb", "preserve"),
    ],
)
def test_each_engine_folds_unquoted_identifiers_its_own_way(dialect, fold):
    assert case_rules(dialect).unquoted_fold == fold


def test_a_case_sensitive_collation_overrides_the_engine_default():
    # Seen on SQL Server estates migrated from Sybase.
    assert case_rules("sqlserver").quoted_case_sensitive is False
    assert case_rules("sqlserver", "SQL_Latin1_General_CP1_CS_AS").quoted_case_sensitive


def test_mysql_table_names_are_case_sensitive_on_linux():
    assert case_rules("mysql").table_names_case_sensitive
    assert not case_rules("postgres").table_names_case_sensitive


def test_loose_folding_ignores_spacing_case_and_punctuation():
    assert loose("Report ID") == loose("report_id") == loose("REPORTID") == "reportid"


# ── quoting ──────────────────────────────────────────────────────────────────


def test_an_identifier_with_a_space_is_always_quoted_in_this_engines_style():
    assert _cat("sqlserver").render("report id") == "[report id]"
    assert _cat("postgres").render("report id") == '"report id"'
    assert _cat("mysql").render("report id") == "`report id`"
    assert _cat("databricks").render("report id") == "`report id`"


def test_a_reserved_word_is_quoted_even_though_it_looks_bare():
    assert _cat("postgres").render("user") == '"user"'
    assert _cat("sqlserver").render("order") == "[order]"


def test_a_plain_business_word_is_left_bare():
    # Quoting `status` or `region`, which no engine reserves, buys nothing and
    # makes generated SQL look machine-written.
    for dialect in ("sqlserver", "mysql", "duckdb"):
        assert Catalog({"t": ["status", "region"]}, dialect=dialect).render("status") == "status"


def test_case_that_would_not_survive_folding_is_quoted():
    # Snowflake folds unquoted to upper, so a lower-case column needs quotes;
    # an upper-case one does not.
    snow = Catalog({"T": ["status", "STATUS_CODE"]}, dialect="snowflake")
    assert snow.render("status") == '"status"'
    assert snow.render("STATUS_CODE") == "STATUS_CODE"

    # Postgres is the mirror image.
    pg = Catalog({"t": ["Status", "status_code"]}, dialect="postgres")
    assert pg.render("Status") == '"Status"'
    assert pg.render("status_code") == "status_code"


# ── resolution ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "written", ["report id", "report_id", "REPORT_ID", "ReportId", "reportid", "Report ID"]
)
def test_every_spelling_of_a_column_resolves_to_the_catalog_spelling(written):
    resolution = _cat().resolve_column(written, "dbo.reports")
    assert resolution.resolved == "report id"


def test_an_unknown_column_names_the_closest_candidates():
    resolution = _cat().resolve_column("reprot_idd", "dbo.reports")
    assert not resolution.ok
    assert "no column" in resolution.message


def test_a_column_in_two_tables_is_ambiguous_not_guessed():
    resolution = _cat().resolve_column("report_id")
    assert resolution.how == "ambiguous"
    assert set(resolution.candidates) == {"dbo.reports.report id", "dbo.report_owner.report id"}
    assert "say which one" in resolution.message


def test_qualifying_the_column_resolves_the_ambiguity():
    assert _cat().resolve_column("report_id", "dbo.reports").ok


# ── rewriting whole statements ───────────────────────────────────────────────


def test_a_wrongly_cased_quoted_column_is_corrected():
    # This is the report: it parses, the old guard passed it, the database threw.
    result = rewrite_identifiers('SELECT "REPORT_ID" FROM dbo.reports', _cat("snowflake"))
    assert result.ok
    assert '"report id"' in result.sql


def test_a_bare_two_word_column_is_quoted_so_the_statement_parses():
    sql = "SELECT report id, COUNT(*) FROM dbo.reports GROUP BY report id"
    result = rewrite_identifiers(sql, _cat())
    assert result.ok
    assert result.sql.count("[report id]") == 2
    assert "quoted an identifier containing a space" in result.fixes


def test_keywords_are_never_quoted_by_the_repair():
    sql = "SELECT owner name FROM dbo.report_owner ORDER BY owner name"
    repaired = repair_unparseable(sql, _cat())
    assert repaired is not None
    for keyword in ("SELECT", "FROM", "ORDER BY"):
        assert keyword in repaired


def test_aliases_are_followed_when_resolving_columns():
    sql = "SELECT r.reportid FROM dbo.reports AS r WHERE r.STATUS = 'open'"
    result = rewrite_identifiers(sql, _cat())
    assert result.ok
    assert "[report id]" in result.sql and "Status" in result.sql


def test_a_missing_column_is_an_error_with_a_reason_not_a_silent_pass():
    result = rewrite_identifiers("SELECT nonexistent_col FROM dbo.reports", _cat())
    assert not result.ok
    assert "no column 'nonexistent_col'" in result.errors[0]


def test_an_ambiguous_column_is_reported_for_clarification_not_guessed():
    sql = "SELECT report_id FROM dbo.reports, dbo.report_owner"
    result = rewrite_identifiers(sql, _cat())
    assert result.ambiguities and not result.ok


def test_a_table_missing_its_schema_still_resolves():
    result = rewrite_identifiers("SELECT status FROM reports", _cat())
    assert result.ok
    assert "dbo" in result.sql


def test_an_unknown_table_is_an_error():
    result = rewrite_identifiers("SELECT x FROM dbo.not_a_table", _cat())
    assert not result.ok


def test_rewriting_is_idempotent():
    once = rewrite_identifiers("SELECT report_id FROM dbo.reports", _cat("postgres"))
    twice = rewrite_identifiers(once.sql, _cat("postgres"))
    assert twice.sql == once.sql and twice.ok


@pytest.mark.parametrize("dialect", ["snowflake", "postgres", "sqlserver", "mysql", "databricks"])
def test_the_same_question_produces_valid_sql_on_every_engine(dialect):
    result = rewrite_identifiers(
        "SELECT report_id, status FROM dbo.reports", Catalog(COLUMNS, dialect)
    )
    assert result.ok
    # Whatever the engine, the emitted identifier round-trips through its parser.
    reparsed = sqlglot.parse_one(result.sql, read=dialect if dialect != "sqlserver" else "tsql")
    assert reparsed is not None


# ── names the statement defines for itself ───────────────────────────────────


def test_a_select_alias_is_not_looked_up_in_the_catalog():
    # `ORDER BY headcount` after `COUNT(*) AS headcount` is correct SQL.
    # Rejecting it because no table has a `headcount` column fails good queries.
    sql = "SELECT COUNT(*) AS headcount FROM dbo.reports GROUP BY Status ORDER BY headcount DESC"
    assert rewrite_identifiers(sql, _cat()).ok


def test_a_cte_name_is_not_a_missing_table():
    sql = "WITH recent AS (SELECT report_id AS rid FROM dbo.reports) SELECT rid FROM recent"
    assert rewrite_identifiers(sql, _cat()).ok


def test_a_column_qualified_by_a_derived_table_is_left_alone():
    sql = "SELECT t.n FROM (SELECT COUNT(*) AS n FROM dbo.reports) AS t"
    assert rewrite_identifiers(sql, _cat()).ok


def test_a_genuinely_missing_column_is_still_caught_alongside_aliases():
    sql = "SELECT COUNT(*) AS headcount, nope FROM dbo.reports"
    result = rewrite_identifiers(sql, _cat())
    assert not result.ok and "nope" in result.errors[0]
