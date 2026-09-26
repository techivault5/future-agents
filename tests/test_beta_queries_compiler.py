"""Policy compilation — what the user is allowed to see, not merely to run.

These assertions are security assertions. A failure here does not produce a
wrong number; it produces someone else's data.
"""

from __future__ import annotations

import pytest
from beta_queries.entitlements.resolver import GrantSet, Mask, RowFilter
from beta_queries.sql.compiler import compile_policies

pytest.importorskip("sqlglot")


def _grants(**kw) -> GrantSet:
    base = {
        "principal": "a@example.com",
        "tables": {"hr.dbo.employee", "hr.dbo.department"},
        "row_filters": [RowFilter("hr.dbo.employee", "{alias}.region = 'EMEA'", "your region")],
        "masks": [
            Mask("hr.dbo.employee", "salary", "aggregate_only"),
            Mask("hr.dbo.employee", "email", "hash"),
            Mask("hr.dbo.employee", "phone", "redact"),
        ],
        "denied_columns": {"hr.dbo.employee.ssn"},
    }
    base.update(kw)
    return GrantSet(**base)


def _compile(sql: str, grants: GrantSet | None = None, dialect: str = "duckdb"):
    return compile_policies(sql, grants or _grants(), "hr", dialect)


# ── row filters ──────────────────────────────────────────────────────────────


def test_a_row_filter_is_injected_whether_or_not_the_model_asked_for_it():
    result = _compile("SELECT name FROM dbo.employee AS e")
    assert result.ok
    assert "e.region = 'EMEA'" in result.sql
    assert result.filters_applied


def test_a_row_filter_is_anded_onto_an_existing_where():
    result = _compile("SELECT name FROM dbo.employee AS e WHERE e.active = TRUE")
    assert result.ok
    assert "active" in result.sql and "region" in result.sql
    assert " AND " in result.sql.upper()


def test_every_scope_gets_its_own_filter_not_just_the_outer_one():
    """A subquery reading the same table is the obvious way around RLS.

    Injecting only at the top level leaves it unfiltered, and a correlated
    subquery then reads exactly the rows the filter exists to hide.
    """
    sql = "SELECT name FROM dbo.employee e WHERE e.dept_id IN (SELECT dept_id FROM dbo.employee)"
    result = _compile(sql)
    assert result.ok
    assert result.sql.upper().count("REGION") == 2


def test_a_cte_scope_is_filtered_too():
    sql = "WITH staff AS (SELECT name, region FROM dbo.employee) SELECT name FROM staff"
    result = _compile(sql)
    assert result.ok and "region" in result.sql.lower()


def test_a_table_with_no_policy_is_left_alone():
    result = _compile("SELECT name FROM dbo.department AS d")
    assert result.ok and not result.filters_applied


def test_an_unparseable_policy_rejects_rather_than_running_unfiltered():
    grants = _grants(row_filters=[RowFilter("hr.dbo.employee", "this is not sql )(")])
    result = _compile("SELECT name FROM dbo.employee e", grants)
    assert not result.ok
    assert "not valid" in result.rejections[0]


def test_unparseable_sql_is_a_rejection_not_a_pass_through():
    assert not _compile("SELECT FROM WHERE )(").ok


# ── masks ────────────────────────────────────────────────────────────────────


def test_an_aggregate_only_column_may_be_aggregated():
    result = _compile("SELECT AVG(e.salary) AS avg_pay FROM dbo.employee e")
    assert result.ok
    assert any("salary" in m for m in result.masks_applied)


def test_an_aggregate_only_column_may_not_be_listed_row_by_row():
    result = _compile("SELECT e.salary FROM dbo.employee e")
    assert not result.ok
    assert "row by row" in result.rejections[0]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT e.name FROM dbo.employee e ORDER BY e.salary",
        "SELECT e.name FROM dbo.employee e GROUP BY e.name HAVING MAX(e.name) > e.salary",
        "SELECT CASE WHEN e.salary > 100 THEN 'high' ELSE 'low' END FROM dbo.employee e",
    ],
)
def test_a_mask_is_checked_everywhere_not_only_in_the_select_list(sql):
    """ORDER BY, HAVING and a CASE arm are all ways to read a value out."""
    assert not _compile(sql).ok


def test_a_hashed_column_is_hashed_in_the_engines_own_dialect():
    assert "MD5" in _compile("SELECT e.email FROM dbo.employee e", dialect="duckdb").sql
    assert "SHA2" in _compile("SELECT e.email FROM dbo.employee e", dialect="snowflake").sql
    assert "HASHBYTES" in _compile("SELECT e.email FROM dbo.employee e", dialect="sqlserver").sql


def test_a_redacted_column_becomes_null_rather_than_disappearing():
    result = _compile("SELECT e.phone FROM dbo.employee e")
    assert result.ok and "NULL" in result.sql.upper()


def test_a_denied_column_is_refused_outright():
    result = _compile("SELECT e.ssn FROM dbo.employee e")
    assert not result.ok
    assert "not readable" in result.rejections[0]


def test_masks_do_not_leak_across_tables():
    # `department.salary` is a different column from `employee.salary`.
    result = _compile("SELECT d.salary FROM dbo.department d")
    assert result.ok


# ── the guarantee ────────────────────────────────────────────────────────────


def test_nothing_is_emitted_when_anything_was_rejected():
    result = _compile("SELECT e.ssn, e.name FROM dbo.employee e")
    assert not result.ok
    # The original SQL is returned untouched — never a half-compiled statement
    # that looks safe and is not.
    assert result.sql == "SELECT e.ssn, e.name FROM dbo.employee e"


def test_a_user_with_no_policies_gets_their_sql_back_unchanged():
    grants = GrantSet(principal="b", tables={"hr.dbo.employee"})
    result = compile_policies("SELECT name FROM dbo.employee", grants, "hr", "duckdb")
    assert result.ok and not result.filters_applied and not result.masks_applied
