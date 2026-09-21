"""The schema graph, profile memory, healing and catalog sync."""

from __future__ import annotations

import pytest
from beta_queries.catalog.graph import Edge, InMemoryGraph, JoinStep, TableNode, is_staging
from beta_queries.eval import corpus
from beta_queries.memory.profile import DictKV, Profile, ProfileStore, user_key
from beta_queries.sql.healing import HealingMemory, diagnose, plan_repair, signature
from beta_queries.sync.plan import apply_to_graph, diff_catalog


def _graph() -> InMemoryGraph:
    g = InMemoryGraph()
    for fqn, cols, kw in [
        ("hr.dbo.employee", ["employee_id", "dept_id", "location_id"], {"terms": {"people"}}),
        ("hr.dbo.department", ["dept_id", "name"], {}),
        ("hr.dbo.location", ["location_id", "country_code"], {}),
        ("hr.dbo.absence", ["absence_id", "employee_id", "days"], {}),
        ("hr.dbo.vw_headcount", ["n"], {"is_view": True}),
        ("hr.stg.employee_raw", ["employee_id"], {"terms": {"people"}}),
    ]:
        ds, schema, name = fqn.split(".")
        g.upsert_table(
            TableNode(fqn=fqn, datasource=ds, schema=schema, name=name, columns=cols, **kw)
        )
    g.upsert_edge(Edge("hr.dbo.employee", "dept_id", "hr.dbo.department", "dept_id"))
    g.upsert_edge(Edge("hr.dbo.employee", "location_id", "hr.dbo.location", "location_id"))
    g.upsert_edge(
        Edge("hr.dbo.absence", "employee_id", "hr.dbo.employee", "employee_id", source="inferred")
    )
    return g


# ── table selection ──────────────────────────────────────────────────────────


def test_a_view_never_ranks_as_a_candidate():
    assert all(c.fqn != "hr.dbo.vw_headcount" for c in _graph().candidate_tables("headcount"))


def test_a_staging_copy_loses_to_the_curated_table():
    # Both match "people" identically — nothing lexical separates them.
    names = [c.fqn for c in _graph().candidate_tables("how many people")]
    assert names == ["hr.dbo.employee"]


@pytest.mark.parametrize(
    "schema,name",
    [
        ("stg", "employee"),
        ("dbo", "stg_employee"),
        ("dbo", "employee_bak"),
        ("raw", "orders"),
        ("dbo", "orders_20240101"),
        ("bronze", "orders"),
    ],
)
def test_staging_is_recognised_by_schema_prefix_or_suffix(schema, name):
    assert is_staging(schema, name)
    assert not is_staging("dbo", "employee")


def test_entitlements_remove_tables_from_consideration_entirely():
    entitled = {"hr.dbo.department"}
    got = _graph().candidate_tables("people by department", entitled=entitled)
    assert [c.fqn for c in got] == ["hr.dbo.department"]


def test_a_certified_metric_outranks_a_lexical_match():
    g = _graph()
    g.upsert_table(
        TableNode(
            fqn="fin.dbo.gl",
            datasource="fin",
            schema="dbo",
            name="gl",
            columns=["amount"],
            metrics={"revenue"},
        )
    )
    top = g.candidate_tables("what is revenue")[0]
    assert top.fqn == "fin.dbo.gl"


# ── join paths ───────────────────────────────────────────────────────────────


def test_a_join_path_is_found_through_an_intermediate_table():
    plan = _graph().join_plan(["hr.dbo.absence", "hr.dbo.department"])
    assert plan.ok
    assert [s.source for s in plan.steps] == ["inferred", "declared"]
    assert {s.right for s in plan.steps} == {"hr.dbo.employee", "hr.dbo.department"}


def test_an_unconnected_table_is_reported_not_invented():
    plan = _graph().join_plan(["hr.dbo.employee", "hr.stg.employee_raw"])
    assert not plan.ok
    assert plan.unreachable == ["hr.stg.employee_raw"]


def test_a_declared_key_is_preferred_over_an_inferred_one():
    g = _graph()
    g.upsert_edge(
        Edge("hr.dbo.absence", "dept_id", "hr.dbo.department", "dept_id", source="inferred")
    )
    g.upsert_edge(
        Edge("hr.dbo.absence", "dept_id", "hr.dbo.department", "dept_id", source="declared")
    )
    assert [
        e.source for e in g.edges() if e.left == "hr.dbo.absence" and e.right == "hr.dbo.department"
    ] == ["declared"]


def test_a_fully_inferred_plan_says_so():
    g = InMemoryGraph()
    for fqn in ("s.d.a", "s.d.b"):
        ds, sc, nm = fqn.split(".")
        g.upsert_table(TableNode(fqn=fqn, datasource=ds, schema=sc, name=nm))
    g.upsert_edge(Edge("s.d.a", "b_id", "s.d.b", "id", source="inferred"))
    assert g.join_plan(["s.d.a", "s.d.b"]).only_inferred


def test_success_makes_a_path_cheaper_and_a_table_likelier():
    g = _graph()
    before = g.candidate_tables("people")[0].score
    g.record_success(
        ["hr.dbo.employee"],
        [JoinStep("hr.dbo.employee", "dept_id", "hr.dbo.department", "dept_id", "declared", "n:1")],
    )
    assert g.candidate_tables("people")[0].score > before


def test_a_single_table_needs_no_joins():
    plan = _graph().join_plan(["hr.dbo.employee"])
    assert plan.ok and plan.steps == []


# ── profile memory ───────────────────────────────────────────────────────────


def test_the_raw_identity_is_never_the_key():
    key = user_key("techivault5@gmail.com")
    assert "gmail" not in key and "@" not in key
    assert key == user_key("  TECHIVAULT5@GMAIL.COM ")


def test_a_clarification_answered_once_is_not_asked_again():
    store = ProfileStore(DictKV())
    profile = store.load("a@b.com")
    profile.record_resolution("accounts", "sales.dbo.customer")
    store.save("a@b.com", profile)
    assert store.load("a@b.com").resolved("Accounts") == "sales.dbo.customer"


def test_a_repeatedly_dismissed_default_stops_being_applied():
    profile = Profile()
    profile.record_dismissal("status.active")
    assert not profile.should_skip_filter("status.active")
    profile.record_dismissal("status.active")
    assert profile.should_skip_filter("status.active")


def test_the_preferred_source_is_only_a_tie_break_among_offered_sources():
    profile = Profile()
    profile.record_answer("salesdb")
    profile.record_answer("salesdb")
    profile.record_answer("hrdb")
    assert profile.preferred_source() == "salesdb"
    assert profile.preferred_source(among=["hrdb"]) == "hrdb"
    assert profile.preferred_source(among=["lakehouse"]) is None


def test_prompt_hints_are_bounded():
    profile = Profile()
    for i in range(50):
        profile.record_glossary(f"word{i}", f"col{i}")
    assert len(profile.prompt_hints(limit=6)["glossary"]) == 6


def test_forget_leaves_nothing_behind():
    kv = DictKV()
    store = ProfileStore(kv)
    profile = store.load("a@b.com")
    profile.record_answer("hrdb")
    store.save("a@b.com", profile)
    store.forget("a@b.com")
    assert store.load("a@b.com").questions == 0


def test_a_corrupt_profile_is_discarded_not_fatal():
    kv = DictKV()
    kv.set(user_key("a@b.com"), "{not json")
    assert ProfileStore(kv).load("a@b.com").questions == 0


# ── healing ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "dialect,message",
    [
        ("sqlserver", "Invalid column name 'report_id'."),
        ("postgres", 'column "report_id" does not exist'),
        ("mysql", "Unknown column 'report_id' in 'field list'"),
        ("snowflake", "SQL compilation error: invalid identifier 'REPORT_ID'"),
        ("databricks", "cannot resolve 'report_id' given input columns: [report id]"),
        ("duckdb", 'Binder Error: Referenced column "report_id" not found'),
    ],
)
def test_the_same_failure_is_one_kind_across_six_engines(dialect, message):
    diagnosis = diagnose(message, dialect)
    assert diagnosis.kind == "unknown_column"
    assert plan_repair(diagnosis).action == "rewrite_identifiers"


@pytest.mark.parametrize(
    "message,kind",
    [
        ("The SELECT permission was denied on the object 'salary'", "permission_denied"),
        ("Statement reached its statement timeout of 300 seconds", "timeout"),
        ('column reference "id" is ambiguous', "ambiguous_column"),
        ("division by zero", "division_by_zero"),
        ("Incorrect datetime value: '2026-13-01'", "date_format"),
        ('column "e.name" must appear in the GROUP BY clause', "missing_group_by"),
    ],
)
def test_error_kinds_are_recognised(message, kind):
    assert diagnose(message).kind == kind


def test_a_terminal_failure_is_not_retried():
    for message in ("permission denied for table salary", "statement timeout"):
        assert plan_repair(diagnose(message)).action == "stop"


def test_only_one_model_repair_is_attempted():
    diagnosis = diagnose("syntax error at or near SELCT")
    assert plan_repair(diagnosis, attempt=0).action == "ask_model"
    assert plan_repair(diagnosis, attempt=1).action == "stop"


def test_two_typos_of_the_same_column_share_one_lesson():
    a = diagnose("Invalid column name 'report_id'.", "sqlserver")
    b = diagnose("Invalid column name 'custome_id'.", "sqlserver")
    assert a.signature == b.signature
    assert signature("x", "postgres") != signature("x", "mysql")


def test_a_lesson_becomes_guidance_only_once_it_has_worked_twice():
    memory = HealingMemory()
    diagnosis = diagnose("Invalid column name 'report_id'.", "sqlserver")
    memory.observe(diagnosis, "sqlserver")
    memory.record_repair(diagnosis, "quote from the catalog spelling", "sqlserver")
    assert memory.guidance("sqlserver") == []
    memory.observe(diagnosis, "sqlserver")
    memory.record_repair(diagnosis, "quote from the catalog spelling", "sqlserver")
    assert memory.guidance("sqlserver")
    assert memory.guidance("postgres") == []


# ── catalog sync ─────────────────────────────────────────────────────────────


def test_a_partial_crawl_is_quarantined_rather_than_applied():
    previous = {f"dbo.t{i}": ["id"] for i in range(100)}
    current = {f"dbo.t{i}": ["id"] for i in range(40)}
    diff = diff_catalog("hrdb", previous, current)
    assert not diff.safe_to_apply
    assert "partial crawl" in diff.quarantined


def test_an_empty_crawl_never_empties_the_catalog():
    assert not diff_catalog("hrdb", {"dbo.t": ["id"]}, {}).safe_to_apply


def test_a_real_decommission_is_applied():
    previous = {f"dbo.t{i}": ["id"] for i in range(10)}
    current = {f"dbo.t{i}": ["id"] for i in range(9)}
    diff = diff_catalog("hrdb", previous, current)
    assert diff.safe_to_apply and diff.removed_tables == ["dbo.t9"]


def test_column_changes_are_reported_per_table():
    diff = diff_catalog("hrdb", {"dbo.t": ["a", "b"]}, {"dbo.t": ["a", "c"]})
    assert diff.changed_tables["dbo.t"] == {"added": ["c"], "removed": ["b"]}


def test_a_quarantined_diff_writes_nothing_at_all():
    graph = InMemoryGraph()
    diff = diff_catalog("hrdb", {f"t{i}": [] for i in range(100)}, {"t0": []})
    node = TableNode(fqn="hrdb.dbo.t0", datasource="hrdb", schema="dbo", name="t0")
    result = apply_to_graph(graph, [node], [], diff)
    assert not result.ok and result.tables_written == 0 and graph.tables() == []


def test_only_changed_tables_are_rewritten():
    graph = InMemoryGraph()
    diff = diff_catalog(
        "hrdb", {"dbo.a": ["id"], "dbo.b": ["id"]}, {"dbo.a": ["id", "extra"], "dbo.b": ["id"]}
    )
    nodes = [
        TableNode(fqn="hrdb.dbo.a", datasource="hrdb", schema="dbo", name="a"),
        TableNode(fqn="hrdb.dbo.b", datasource="hrdb", schema="dbo", name="b"),
    ]
    result = apply_to_graph(graph, nodes, [], diff)
    assert result.ok and result.tables_written == 1


# ── the corpus ───────────────────────────────────────────────────────────────


def test_the_corpus_is_large_and_counted_not_estimated():
    assert corpus.total_cases() == sum(1 for _ in corpus.generate())


def test_generation_is_deterministic():
    a = [c.id for c in corpus.generate(limit=200)]
    b = [c.id for c in corpus.generate(limit=200)]
    assert a == b


def test_questions_read_like_people_wrote_them():
    questions = [c.question for c in corpus.generate(limit=500)]
    assert any("?" in q for q in questions)
    # Not a template with the entity name substituted into a stock frame.
    assert not all(q.lower().startswith("how many") for q in questions)


def test_every_hazard_is_exercised_by_the_release_gate():
    covered = {h for case in corpus.hazard_suite() for h in case.hazards}
    assert covered == set(corpus.HAZARDS_BY_ID)


def test_every_hazard_declares_a_behaviour_the_system_must_produce():
    assert {h.expected for h in corpus.HAZARDS} <= {"answer", "clarify", "refuse", "assume"}


def test_the_stricter_expectation_wins_when_hazards_combine():
    cases = [c for c in corpus.generate(limit=6000) if len(c.hazards) > 1]
    assert cases
    order = {"refuse": 3, "clarify": 2, "assume": 1, "answer": 0}
    for case in cases[:50]:
        strictest = max(order[corpus.HAZARDS_BY_ID[h].expected] for h in case.hazards)
        assert order[case.expected] == strictest
