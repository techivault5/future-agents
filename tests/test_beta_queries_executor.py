"""Execution against a real database.

DuckDB is the engine everything is tested against, because it is the only one
of the six that can be created in a fixture. The schema is deliberately
hostile: a column with a space, a column whose case matters, and a view.
"""

from __future__ import annotations

import pytest
from beta_queries.sql.executor import (
    DEFAULT_ROW_LIMIT,
    DbapiExecutor,
    ExecutionError,
    ExecutionRequest,
    bind,
    duckdb_connect,
    run,
)

duckdb = pytest.importorskip("duckdb")


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "hr.duckdb")
    con = duckdb.connect(path)
    con.execute('CREATE TABLE employee ("report id" INTEGER, "Status" VARCHAR, country VARCHAR)')
    con.execute("INSERT INTO employee VALUES (1,'ACTIVE','IN'),(2,'ACTIVE','IN'),(3,'LEFT','DE')")
    con.execute("CREATE VIEW vw_active AS SELECT * FROM employee WHERE \"Status\" = 'ACTIVE'")
    con.close()
    return path


@pytest.fixture
def connect(db):
    return duckdb_connect(db, read_only=True)


# ── parameter binding ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "dialect,expected",
    [
        ("duckdb", "SELECT * FROM t WHERE a = ? AND b = ?"),
        ("sqlserver", "SELECT * FROM t WHERE a = ? AND b = ?"),
        ("postgres", "SELECT * FROM t WHERE a = %s AND b = %s"),
        ("mysql", "SELECT * FROM t WHERE a = %s AND b = %s"),
        ("snowflake", "SELECT * FROM t WHERE a = %s AND b = %s"),
    ],
)
def test_placeholders_are_rewritten_into_the_drivers_own_style(dialect, expected):
    sql, params = bind("SELECT * FROM t WHERE a = @p0 AND b = @p1", {"p0": "IN", "p1": 5}, dialect)
    assert sql == expected
    assert params == ("IN", 5)


def test_parameters_are_ordered_by_appearance_not_by_name():
    _, params = bind("SELECT * FROM t WHERE b = @p1 AND a = @p0", {"p0": "x", "p1": "y"}, "duckdb")
    assert params == ("y", "x")


def test_a_percent_in_a_like_pattern_is_escaped_for_pyformat_drivers():
    # Otherwise psycopg and mysql-connector read it as a format spec.
    sql, params = bind("SELECT * FROM t WHERE n LIKE 'A%'", {}, "postgres")
    assert sql.endswith("'A%%'") and params == ()


def test_an_unbound_parameter_fails_rather_than_binding_null():
    """A silently-NULL filter returns the wrong number instead of an error."""
    with pytest.raises(ExecutionError, match="unbound parameter"):
        bind("SELECT * FROM t WHERE a = @nope", {}, "duckdb")


def test_a_literal_is_never_interpolated():
    sql, params = bind("SELECT * FROM t WHERE a = @p0", {"p0": "'; DROP TABLE t; --"}, "duckdb")
    assert "DROP" not in sql
    assert params == ("'; DROP TABLE t; --",)


# ── execution ────────────────────────────────────────────────────────────────


def test_a_bound_query_returns_rows(connect):
    result = run(
        'SELECT COUNT(*) AS n FROM employee WHERE country = @p0 AND "Status" = @p1',
        "duckdb",
        connect,
        {"p0": "IN", "p1": "ACTIVE"},
    )
    assert result.first() == {"n": 2}
    assert result.columns == ["n"]


def test_a_column_with_a_space_survives_the_whole_path(connect):
    result = run('SELECT "report id" FROM employee ORDER BY "report id"', "duckdb", connect)
    assert [row[0] for row in result.rows] == [1, 2, 3]


def test_the_row_cap_is_enforced_and_truncation_is_knowable(connect):
    result = run("SELECT * FROM employee", "duckdb", connect, row_limit=2)
    assert result.row_count == 2
    assert result.truncated is True


def test_a_result_inside_the_cap_is_not_marked_truncated(connect):
    result = run("SELECT * FROM employee", "duckdb", connect, row_limit=10)
    assert result.row_count == 3 and not result.truncated


def test_an_empty_result_is_a_result_not_an_error(connect):
    result = run("SELECT * FROM employee WHERE country = @p0", "duckdb", connect, {"p0": "ZZ"})
    assert result.row_count == 0 and result.first() is None


# ── failure ──────────────────────────────────────────────────────────────────


def test_the_engines_message_is_carried_verbatim(connect):
    """Verbatim matters: diagnose(), the technical error layer and the healing
    signature all read this string, and all three break if it is tidied up."""
    with pytest.raises(ExecutionError) as caught:
        run("SELECT nope FROM employee", "duckdb", connect)
    assert "nope" in caught.value.message
    assert caught.value.dialect == "duckdb"
    assert caught.value.sql.startswith("SELECT nope")


def test_an_execution_error_feeds_the_healing_loop(connect):
    """The loop closing: a real engine error becomes a real repair plan."""
    from beta_queries.sql.healing import diagnose, plan_repair

    with pytest.raises(ExecutionError) as caught:
        run("SELECT nope FROM employee", "duckdb", connect)

    diagnosis = diagnose(caught.value.message, caught.value.dialect)
    assert diagnosis.kind == "unknown_column"
    assert diagnosis.subject == "nope"
    assert plan_repair(diagnosis).action == "rewrite_identifiers"


def test_a_write_is_refused_by_the_connection_not_only_by_the_guard(connect):
    # The guard rejects non-SELECT first; this is the second lock on the door,
    # for the case where something reaches the executor another way.
    with pytest.raises(ExecutionError):
        run("DELETE FROM employee", "duckdb", connect)


def test_a_failure_is_reported_to_the_observer(connect):
    seen: list[ExecutionError] = []
    executor = DbapiExecutor(connect, "duckdb", on_error=seen.append)
    with pytest.raises(ExecutionError):
        executor.run(ExecutionRequest(sql="SELECT nope FROM employee", dialect="duckdb"))
    assert seen and seen[0].sqlstate is not None


def test_connections_are_closed_even_when_the_query_fails(db):
    closed: list[str] = []

    class Tracking:
        def __init__(self, inner):
            self.inner = inner

        def cursor(self):
            return Tracking(self.inner.cursor())

        def execute(self, *a):
            return self.inner.execute(*a)

        def fetchmany(self, n):
            return self.inner.fetchmany(n)

        @property
        def description(self):
            return self.inner.description

        def close(self):
            closed.append("closed")
            self.inner.close()

    def connect():
        return Tracking(duckdb.connect(db, read_only=True))

    with pytest.raises(ExecutionError):
        run("SELECT nope FROM employee", "duckdb", connect)
    assert len(closed) == 2  # cursor and connection


def test_the_default_row_cap_is_applied_without_being_asked_for(connect):
    result = run("SELECT * FROM employee", "duckdb", connect)
    assert result.row_limit == DEFAULT_ROW_LIMIT
