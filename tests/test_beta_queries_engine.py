"""Beta Queries engine — dialects, semantics, guard, routing, contract, steps.

These are the behaviours that decide whether an answer is right rather than
merely well-formed, so they are asserted concretely: a view is refused by name,
`load_date` loses to `hire_date`, and a T-SQL row cap is spelled TOP.
"""

from __future__ import annotations

import pytest

from beta_queries import dialects
from beta_queries.catalog import crawler, models
from beta_queries.agent.contract import QueryPlan
from beta_queries.catalog.models import Column, Table, logical_type
from beta_queries.catalog.semantics import (
    detect_default_filters,
    is_ambiguous,
    rank_columns,
)
from beta_queries.progress import StepMachine
from beta_queries.routing import router
from beta_queries.routing.router import SourceProfile, route
from beta_queries.sql.guard import GuardContext, check

sqlglot = pytest.importorskip("sqlglot")


def _col(name: str, dtype: str, ordinal: int = 1, **kw) -> Column:
    return Column(
        name=name, ordinal=ordinal, data_type=dtype, nullable=kw.pop("nullable", True), **kw
    )


@pytest.fixture
def employee() -> Table:
    return Table(
        datasource_id="hr",
        schema="dbo",
        name="employee",
        columns=[
            _col("employee_id", "int", 1, nullable=False),
            _col("full_name", "nvarchar(100)", 2, is_pii=True),
            _col(
                "employment_status",
                "varchar(16)",
                3,
                sample_values=["ACTIVE", "TERMINATED"],
                distinct_count=2,
            ),
            _col("is_deleted", "bit", 4, nullable=False),
            _col("hire_date", "date", 5),
            _col("load_date", "datetime2", 6),
        ],
    )


CATALOG = {"dbo.employee": False, "dbo.location": False, "dbo.v_headcount": True}


# ── dialects ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "alias,expected",
    [
        ("mssql", "sqlserver"),
        ("postgresql", "postgres"),
        ("mariadb", "mysql"),
        ("spark", "databricks"),
    ],
)
def test_dialect_aliases_resolve(alias: str, expected: str) -> None:
    assert dialects.get(alias).name == expected


def test_only_enforcing_engines_claim_declared_fks() -> None:
    # Snowflake and Databricks do not enforce FKs; a catalog that trusts
    # referential_constraints there silently produces no joins.
    assert dialects.get("snowflake").supports_declared_fks is False
    assert dialects.get("databricks").supports_declared_fks is False
    assert dialects.get("sqlserver").supports_declared_fks is True


def test_identifier_quoting_is_engine_correct() -> None:
    assert dialects.get("sqlserver").quote_ident("my tbl") == "[my tbl]"
    assert dialects.get("databricks").quote_ident("my tbl") == "`my tbl`"
    assert dialects.get("postgres").quote_ident('od"d') == '"od""d"'


def test_sqlserver_introspection_uses_sys_tables_not_table_type() -> None:
    # sys.tables excludes views structurally, so no string comparison can let
    # one through.
    sql = dialects.get("sqlserver").columns_sql
    assert "sys.tables" in sql and "table_type" not in sql.lower()


def test_databricks_excludes_views_by_negation() -> None:
    # Unity Catalog reports MANAGED/EXTERNAL/VIEW — never 'BASE TABLE'.
    sql = dialects.get("databricks").columns_sql
    assert "table_type <> 'VIEW'" in sql
    assert "BASE TABLE" not in sql


@pytest.mark.parametrize(
    "physical,logical",
    [
        ("NUMBER(38,0)", "integer"),
        ("tinyint(1)", "boolean"),
        ("bit", "boolean"),
        ("TIMESTAMP_NTZ", "timestamp"),
        ("NVARCHAR(50)", "string"),
        ("jsonb", "other"),
    ],
)
def test_logical_types_span_all_engines(physical: str, logical: str) -> None:
    assert logical_type(physical) == logical


# ── semantics ────────────────────────────────────────────────────────────────


def test_soft_delete_and_status_flags_are_detected(employee: Table) -> None:
    found = {f.kind: f for f in detect_default_filters(employee, "sqlserver", alias="e")}
    assert found["soft_delete"].expression == "e.is_deleted = 0"
    assert found["status_enum"].expression == "e.employment_status = 'ACTIVE'"


def test_boolean_literal_follows_the_engine() -> None:
    flag = Table(
        datasource_id="d",
        schema="s",
        name="t",
        columns=[_col("is_active", "boolean", 1, nullable=False)],
    )
    pg = detect_default_filters(flag, "postgres", alias="t")[0]
    ms = detect_default_filters(
        Table(
            datasource_id="d",
            schema="s",
            name="t",
            columns=[_col("is_active", "bit", 1, nullable=False)],
        ),
        "sqlserver",
        alias="t",
    )[0]
    assert pg.expression == "t.is_active = TRUE"
    assert ms.expression == "t.is_active = 1"


def test_scd2_sentinel_end_date_is_recognised() -> None:
    scd = Table(
        datasource_id="d",
        schema="s",
        name="dim",
        columns=[_col("valid_to", "date", 1, sample_values=["9999-12-31"])],
    )
    f = detect_default_filters(scd, "snowflake", alias="d")[0]
    assert f.kind == "scd_current"
    assert "9999-12-31" in f.expression


def test_status_column_without_a_live_value_asks_rather_than_guesses() -> None:
    odd = Table(
        datasource_id="d",
        schema="s",
        name="t",
        columns=[
            _col("record_status", "varchar(4)", 1, sample_values=["P", "Q"], distinct_count=2)
        ],
    )
    f = detect_default_filters(odd, "postgres", alias="t")[0]
    assert f.expression == ""  # nothing invented
    assert f.confidence < 0.5


def test_audit_columns_lose_to_business_columns(employee: Table) -> None:
    ranked = {s.name: s.score for s in rank_columns("date", employee, intent="time")}
    assert ranked["hire_date"] > ranked["load_date"]


def test_a_genuine_tie_is_reported_as_ambiguous(employee: Table) -> None:
    employee.columns.append(_col("termination_date", "date", 7))
    assert is_ambiguous(rank_columns("date", employee, intent="time"))


# ── guard ────────────────────────────────────────────────────────────────────


def test_view_is_refused_even_when_entitled() -> None:
    r = check("SELECT * FROM dbo.v_headcount", GuardContext(dialect="postgres", tables=CATALOG))
    assert not r.ok and r.first_rule() == "G06"
    assert "base tables" in r.rejections[0].message


def test_unknown_table_is_refused() -> None:
    r = check("SELECT * FROM dbo.salaries_secret", GuardContext(dialect="postgres", tables=CATALOG))
    assert not r.ok and r.first_rule() == "G06"


@pytest.mark.parametrize("dialect", ["sqlserver", "postgres", "snowflake", "mysql", "databricks"])
def test_second_statement_is_refused_in_every_dialect(dialect: str) -> None:
    r = check(
        "SELECT 1 FROM dbo.employee; DROP TABLE dbo.employee",
        GuardContext(dialect=dialect, tables=CATALOG),
    )
    assert not r.ok


def test_cartesian_product_is_refused() -> None:
    r = check(
        "SELECT * FROM dbo.employee e, dbo.location l",
        GuardContext(dialect="mysql", tables=CATALOG),
    )
    assert not r.ok and r.first_rule() == "G11"


def test_tsql_escape_hatches_are_refused() -> None:
    r = check(
        "SELECT * FROM dbo.employee WHERE 1 = (SELECT 1 FROM OPENROWSET('x','y','z'))",
        GuardContext(dialect="sqlserver", tables=CATALOG),
    )
    assert not r.ok


def test_row_cap_is_spelled_the_way_the_engine_spells_it() -> None:
    ms = check(
        "SELECT employee_id FROM dbo.employee",
        GuardContext(dialect="sqlserver", tables=CATALOG, row_limit=100),
    )
    sf = check(
        "SELECT employee_id FROM dbo.employee",
        GuardContext(dialect="snowflake", tables=CATALOG, row_limit=100),
    )
    assert ms.ok and "TOP 100" in ms.sql and "LIMIT" not in ms.sql
    assert sf.ok and "LIMIT 100" in sf.sql and "TOP" not in sf.sql


def test_existing_limit_is_left_alone() -> None:
    r = check(
        "SELECT employee_id FROM dbo.employee LIMIT 5",
        GuardContext(dialect="postgres", tables=CATALOG, row_limit=1000),
    )
    assert r.ok and "LIMIT 5" in r.sql and "1000" not in r.sql


def test_cte_name_is_not_mistaken_for_a_missing_table() -> None:
    r = check(
        "WITH recent AS (SELECT * FROM dbo.employee) SELECT * FROM recent",
        GuardContext(dialect="postgres", tables=CATALOG),
    )
    assert r.ok, r.findings


def test_unparseable_sql_fails_closed() -> None:
    r = check("SELECT FROM WHERE )(", GuardContext(dialect="postgres", tables=CATALOG))
    assert not r.ok


# ── routing ──────────────────────────────────────────────────────────────────


def _hr() -> SourceProfile:
    return SourceProfile(
        datasource_id="hr_warehouse",
        dialect="sqlserver",
        description="people, headcount, payroll",
        subject_areas=["hr"],
        table_terms={"employee", "location"},
        column_terms={"country_code", "hire_date"},
        value_index={"india": "dbo.location.country_code"},
        metric_names={"headcount"},
        synonyms={"people": "employee", "staff": "employee"},
    )


def _finance() -> SourceProfile:
    return SourceProfile(
        datasource_id="finance_dw",
        dialect="snowflake",
        description="revenue, invoices, general ledger",
        subject_areas=["finance"],
        table_terms={"invoice", "ledger"},
        column_terms={"amount", "currency"},
        metric_names={"revenue"},
    )


def test_synonyms_route_people_to_the_employee_source() -> None:
    d = route("how many people are in India?", [_hr(), _finance()])
    assert d.chosen == "hr_warehouse"


def test_metric_name_routes_without_asking() -> None:
    d = route("what was revenue last quarter?", [_hr(), _finance()])
    assert d.confident and d.chosen == "finance_dw"


def test_two_weak_candidates_are_not_an_ambiguity() -> None:
    d = route("show me pipeline velocity", [_hr(), _finance()])
    assert d.chosen is None and d.needs_clarification is False


def test_entitlement_filters_the_candidate_set() -> None:
    d = route("what was revenue last quarter?", [_hr(), _finance()], entitled={"hr_warehouse"})
    assert d.chosen != "finance_dw"


# ── contract ─────────────────────────────────────────────────────────────────


def _plan(**over) -> dict:
    base = dict(
        datasource_id="hr",
        dialect="sqlserver",
        intent="aggregate_count",
        confidence=0.9,
        sql="SELECT COUNT(*) AS headcount FROM dbo.employee",
        referenced_tables=["hr.dbo.employee"],
        answer_template="There are {{headcount}} active employees in {{p0_label}}.",
        params=[
            {
                "name": "p0",
                "type": "char(2)",
                "value": "IN",
                "source": "value_index",
                "label": "India",
            }
        ],
    )
    base.update(over)
    return base


def test_code_fence_from_the_model_is_tolerated() -> None:
    plan = QueryPlan(**_plan(sql="```sql\nSELECT COUNT(*) AS headcount FROM dbo.employee;\n```"))
    assert plan.sql == "SELECT COUNT(*) AS headcount FROM dbo.employee"


def test_narrative_renders_deterministically_with_no_model() -> None:
    assert QueryPlan(**_plan()).render_answer({"headcount": 4812}) == (
        "There are 4,812 active employees in India."
    )


def test_sql_and_clarification_are_mutually_exclusive() -> None:
    with pytest.raises(ValueError):
        QueryPlan(
            **_plan(
                clarification={
                    "question": "which?",
                    "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                }
            )
        )


def test_sql_without_an_answer_template_is_refused() -> None:
    with pytest.raises(ValueError):
        QueryPlan(**_plan(answer_template=None))


# ── progress ─────────────────────────────────────────────────────────────────


def test_steps_emit_running_then_done_and_record_skips() -> None:
    events: list[dict] = []
    m = StepMachine(sink=events.append)
    m.start("route")
    m.done("route", datasource="hr_warehouse")
    m.skip("generate", "template hit")
    assert [e["state"] for e in events] == ["running", "done", "skipped"]
    assert events[2]["detail"] == "template hit"


def test_a_missing_placeholder_never_breaks_the_response() -> None:
    m = StepMachine()
    step = m.done("execute")  # template wants {rows} and {ms}
    assert step.state == "done"


# ── crawler ──────────────────────────────────────────────────────────────────


def _fake_runner(dialect_name: str, columns_rows, view_rows=(), fk_rows=(), values=None):
    """Answer the three catalog queries by shape, and value queries by table.column."""
    d = dialects.get(dialect_name)
    values = values or {}

    def run(sql: str):
        if sql == d.columns_sql:
            return list(columns_rows)
        if d.views_sql and sql == d.views_sql:
            return list(view_rows)
        if d.fk_sql and sql == d.fk_sql:
            return list(fk_rows)
        for key, rows in values.items():
            col = key.split(".")[-1]
            if col in sql:
                return list(rows)
        return []

    return run


_EMP_COLUMNS = [
    ("hr", "employee", "id", 1, "int", 0, "People", None),
    ("hr", "employee", "department_id", 2, "int", 1, "People", None),
    ("hr", "employee", "country_code", 3, "varchar", 1, "People", "ISO-2"),
    ("hr", "employee", "email", 4, "varchar", 1, "People", None),
    ("hr", "employee", "is_deleted", 5, "bit", 0, "People", None),
    ("hr", "department", "id", 1, "int", 0, None, None),
    ("hr", "department", "name", 2, "varchar", 0, None, None),
]


def test_crawl_structure_groups_columns_and_keeps_comments():
    run = _fake_runner("sqlserver", _EMP_COLUMNS)
    ds = crawler.crawl_structure("hrdb", "sqlserver", run)
    emp = ds.table("hr.employee")
    assert [c.name for c in emp.columns] == [
        "id",
        "department_id",
        "country_code",
        "email",
        "is_deleted",
    ]
    assert emp.comment == "People"
    assert emp.column("country_code").comment == "ISO-2"
    assert len(ds.tables) == 2


def test_crawl_records_views_without_columns():
    run = _fake_runner("sqlserver", _EMP_COLUMNS, view_rows=[("hr", "vw_headcount")])
    ds = crawler.crawl_structure("hrdb", "sqlserver", run)
    view = ds.table("hr.vw_headcount")
    assert view.is_view and view.columns == []
    assert [t.relname for t in ds.base_tables] == ["hr.employee", "hr.department"]


def test_pii_columns_are_flagged_by_name():
    run = _fake_runner("sqlserver", _EMP_COLUMNS)
    ds = crawler.crawl_structure("hrdb", "sqlserver", run)
    emp = ds.table("hr.employee")
    assert emp.column("email").is_pii
    assert not emp.column("country_code").is_pii


def test_declared_joins_read_from_the_engine():
    fk = [("hr", "employee", "department_id", "hr", "department", "id")]
    run = _fake_runner("sqlserver", _EMP_COLUMNS, fk_rows=fk)
    ds = crawler.crawl_structure("hrdb", "sqlserver", run)
    edges = crawler.declared_joins(ds, run)
    assert len(edges) == 1
    assert edges[0].source == "declared" and edges[0].right_column == "id"


def test_declared_joins_are_skipped_where_fks_are_not_enforced():
    run = _fake_runner("snowflake", _EMP_COLUMNS)
    ds = crawler.crawl_structure("hrdb", "snowflake", run)
    assert crawler.declared_joins(ds, run) == []


def test_inferred_joins_cover_the_engines_without_fks():
    run = _fake_runner("snowflake", _EMP_COLUMNS)
    ds = crawler.crawl_structure("hrdb", "snowflake", run)
    edges = crawler.infer_joins(ds)
    assert [(e.left_column, e.right_table.split(".")[-1], e.source) for e in edges] == [
        ("department_id", "department", "inferred")
    ]


def test_inference_drops_ambiguous_targets():
    rows = list(_EMP_COLUMNS) + [
        ("finance", "department", "id", 1, "int", 0, None, None),
    ]
    run = _fake_runner("snowflake", rows)
    ds = crawler.crawl_structure("hrdb", "snowflake", run)
    assert crawler.infer_joins(ds) == []


def test_merge_joins_prefers_declared_over_inferred():
    declared = models.JoinEdge("a.b.emp", "dept_id", "a.b.dept", "id", source="declared")
    inferred = models.JoinEdge(
        "a.b.emp", "dept_id", "a.b.dept", "id", source="inferred", confidence=0.75
    )
    merged = crawler.merge_joins([inferred], [declared])
    assert len(merged) == 1 and merged[0].source == "declared"


def test_value_count_sql_is_dialect_correct():
    table = models.Table(datasource_id="d", schema="hr", name="employee")
    col = models.Column(name="country code", ordinal=1, data_type="varchar", nullable=True)
    tsql = crawler.value_count_sql(table, col, "sqlserver", 50)
    assert "TOP (50)" in tsql and "[country code]" in tsql and "LIMIT" not in tsql
    snow = crawler.value_count_sql(table, col, "snowflake", 50)
    assert snow.rstrip().endswith("LIMIT 50") and '"country code"' in snow


def test_profiling_indexes_low_cardinality_values_only():
    values = {
        "country_code": [("IN", 4812), ("US", 3100), ("GB", 900)],
        "email": [("a@x.com", 1), ("b@x.com", 1)],
    }
    run = _fake_runner("sqlserver", _EMP_COLUMNS, values=values)
    ds = crawler.crawl_structure("hrdb", "sqlserver", run)
    crawler.profile_values(ds, run)
    emp = ds.table("hr.employee")
    assert emp.column("country_code").sample_values == ["IN", "US", "GB"]
    # PII keeps its cardinality but never its values.
    assert emp.column("email").sample_values == []
    assert emp.column("email").distinct_count == 2


def test_profiling_discards_high_cardinality_columns():
    values = {"country_code": [(f"v{i}", 1) for i in range(60)]}
    run = _fake_runner("sqlserver", _EMP_COLUMNS, values=values)
    ds = crawler.crawl_structure("hrdb", "sqlserver", run)
    crawler.profile_values(ds, run, crawler.ProfileOptions(max_distinct=50))
    col = ds.table("hr.employee").column("country_code")
    assert col.sample_values == [] and col.distinct_count is None


def test_profiling_survives_a_denied_column():
    def run(sql: str):
        if "country_code" in sql and "GROUP BY" in sql:
            raise PermissionError("SELECT denied on hr.employee")
        return _fake_runner("sqlserver", _EMP_COLUMNS)(sql)

    ds = crawler.crawl_structure("hrdb", "sqlserver", run)
    errors: list[str] = []
    crawler.profile_values(ds, run, on_error=lambda t, c, e: errors.append(c.name))
    assert errors == ["country_code"]


def test_crawl_end_to_end_builds_a_routable_profile():
    fk = [("hr", "employee", "department_id", "hr", "department", "id")]
    values = {"country_code": [("IN", 4812), ("US", 3100)]}
    run = _fake_runner(
        "sqlserver", _EMP_COLUMNS, view_rows=[("hr", "vw_headcount")], fk_rows=fk, values=values
    )
    result = crawler.crawl(
        "hrdb", "sqlserver", run, description="HR warehouse", synonyms={"people": "employee"}
    )
    ds = result.datasource
    assert len(ds.base_tables) == 2
    assert any(e.source == "declared" for e in ds.joins)
    # The soft-delete flag becomes a default filter without anyone asking.
    assert any(f.kind == "soft_delete" for f in ds.table("hr.employee").default_filters)
    assert result.profile.value_index["in"] == "hr.employee.country_code"
    assert "employee" in result.profile.table_terms
    assert result.errors == []
    assert "2 base tables, 1 views skipped" in result.summary


def test_crawled_profile_routes_a_question_to_its_source():
    values = {"name": [("Engineering", 300), ("Finance", 80)]}
    run = _fake_runner("sqlserver", _EMP_COLUMNS, values=values)
    hr = crawler.crawl("hrdb", "sqlserver", run, synonyms={"people": "employee"}).profile
    assert hr.value_index["engineering"] == "hr.department.name"
    other = router.SourceProfile(
        datasource_id="salesdb", dialect="postgres", table_terms={"order", "invoice"}
    )
    decision = router.route("how many people work in Engineering", [hr, other])
    assert decision.chosen == "hrdb" and decision.confident


def test_dbapi_runner_closes_its_cursor():
    class Cursor:
        def __init__(self):
            self.closed = False

        def execute(self, sql):
            self.sql = sql

        def fetchall(self):
            return [(1,)]

        def close(self):
            self.closed = True

    class Conn:
        def __init__(self):
            self.cursors = []

        def cursor(self):
            c = Cursor()
            self.cursors.append(c)
            return c

    conn = Conn()
    assert crawler.dbapi_runner(conn)("SELECT 1") == [(1,)]
    assert conn.cursors[0].closed
