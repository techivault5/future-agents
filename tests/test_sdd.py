"""Spec-driven delivery — clarification gate, IR pipeline, QA, memory hub."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from future_agents.sdd import (
    ClarificationOutcome,
    Constitution,
    DeliveryPipeline,
    EngineCall,
    EngineRouter,
    IntakeSource,
    IntentClarifier,
    MemoryHub,
    Objective,
    Plan,
    Question,
    Requirement,
    Spec,
    SpecKitConfig,
    Stage,
    TaskGraph,
    TaskKind,
    TaskStatus,
    TaskUnit,
    WorkResult,
    load_state,
    save_state,
)
from future_agents.sdd.config import ConfigError, MemoryHubConfig
from future_agents.sdd.constitution import Severity
from future_agents.sdd.memory_hub import MemoryCase
from future_agents.sdd.models import (
    AcceptanceCriterion,
    Component,
    CycleError,
    Priority,
    QAVerdict,
)
from future_agents.sdd.router import CallableEngine
from future_agents.sdd.stages import ArchitectStage, PMStage, QAStage, TaskPlanner, WorkerStage

GOOD_STATEMENT = (
    "Sales must get a weekly churn report so that account managers can call at-risk customers"
)


@pytest.fixture
def config(tmp_path: Path) -> SpecKitConfig:
    cfg = SpecKitConfig.load(root=Path.cwd())
    cfg.memory_hub = MemoryHubConfig(case_studies_path=str(tmp_path / "cases"))
    return cfg


@pytest.fixture
def hub(config: SpecKitConfig) -> MemoryHub:
    return MemoryHub(config.memory_hub)


@pytest.fixture
def pipeline(config: SpecKitConfig, hub: MemoryHub) -> DeliveryPipeline:
    return DeliveryPipeline(config, memory=hub)


def meeting_objective() -> Objective:
    return Objective(
        statement=GOOD_STATEMENT,
        context="Ops review 2026-09-01.",
        source=IntakeSource.MEETING,
        submitted_by="dana",
        raw_inputs=[
            "Dana: the report pulls from Snowflake every Monday 09:00\n"
            "Ravi: flag any account whose usage dropped 20% or more\n"
            "Priya: billing integration is out of scope for this phase"
        ],
        constraints=["no new production env vars"],
        deadline="2026-10-01",
    )


# ── Clarification gate ────────────────────────────────────────────────────────


def test_well_formed_objective_is_ready(config: SpecKitConfig) -> None:
    result = IntentClarifier(config).assess(meeting_objective())
    assert result.outcome is ClarificationOutcome.READY
    assert result.confidence >= config.clarification.ready_threshold


def test_vague_objective_escalates_to_a_meeting(config: SpecKitConfig) -> None:
    result = IntentClarifier(config).assess(
        Objective(statement="Make the dashboard faster and more user-friendly", submitted_by="sam")
    )
    assert result.outcome is ClarificationOutcome.MEETING_REQUIRED
    assert result.meeting is not None
    assert "sam" in result.meeting.required_attendees
    assert result.meeting.agenda  # a meeting always arrives with its agenda


def test_answers_raise_confidence_and_close_questions(config: SpecKitConfig) -> None:
    clarifier = IntentClarifier(config)
    objective = Objective(statement="Make the dashboard faster", submitted_by="sam")
    first = clarifier.assess(objective)
    answers = {q.id: "p95 under 800ms, from a 3.2s baseline" for q in first.questions}

    second = clarifier.apply_answers(objective, first, answers)

    assert second.confidence > first.confidence
    assert second.round_number == 2


def test_low_risk_unknowns_become_recorded_assumptions(config: SpecKitConfig) -> None:
    config.clarification.auto_assume_low_risk = True
    result = IntentClarifier(config).assess(
        Objective(
            statement="Publish the quarterly board deck to the shared drive each Friday",
            submitted_by="dana",
        )
    )
    assert result.assumptions
    assert all(a.statement for a in result.assumptions)


def test_escalation_trigger_produces_a_blocking_ownership_question(config: SpecKitConfig) -> None:
    result = IntentClarifier(config).assess(
        Objective(
            statement="Store payment card details for returning customers in the checkout flow",
            context="Checkout revamp.",
            submitted_by="dana",
        )
    )
    ownership = [q for q in result.questions if q.topic.value == "ownership"]
    assert ownership and ownership[0].blocking


def test_meeting_notes_become_objective_context(config: SpecKitConfig) -> None:
    clarifier = IntentClarifier(config)
    objective = Objective(statement="Make it better", submitted_by="sam")
    result = clarifier.assess(objective)

    clarifier.record_meeting(objective, result, "Target: p95 under 800ms.")

    assert "p95" in objective.context
    assert result.meeting is not None and result.meeting.status.value == "held"


# ── Config ────────────────────────────────────────────────────────────────────


def test_repo_config_loads_and_derives_a_constitution() -> None:
    cfg = SpecKitConfig.load(root=Path.cwd())
    assert cfg.project.name
    assert cfg.engine_for("pm_agent")
    assert "Constitution" in cfg.constitution().render_markdown()


def test_env_reference_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPEC_KIT_TEST_GATEWAY", "mcp://gateway:9000")
    cfg = SpecKitConfig.from_yaml("agents:\n  mcp_gateway_uri: ${SPEC_KIT_TEST_GATEWAY}\n")
    assert cfg.agents.mcp_gateway_uri == "mcp://gateway:9000"


def test_inline_secret_is_rejected() -> None:
    with pytest.raises(ConfigError, match="inline secret"):
        SpecKitConfig.from_yaml("agents:\n  api_key: sk-not-a-real-key\n")


def test_thresholds_must_be_ordered() -> None:
    with pytest.raises(ValueError):
        SpecKitConfig.from_yaml(
            "clarification:\n  ready_threshold: 0.5\n  meeting_threshold: 0.9\n"
        )


# ── Constitution gates ────────────────────────────────────────────────────────


def spec_with(**kwargs) -> Spec:
    requirement = Requirement(
        id="REQ-001",
        statement="the report lists at-risk accounts",
        acceptance_criteria=[
            AcceptanceCriterion(
                id="REQ-001-AC-001",
                given="a week of usage",
                when="the report runs",
                then="at-risk accounts are listed",
            )
        ],
    )
    return Spec(objective_id="obj-1", title="churn report", requirements=[requirement], **kwargs)


def test_missing_acceptance_criteria_fails_the_spec_gate() -> None:
    spec = spec_with()
    spec.requirements[0].acceptance_criteria = []
    violations = Constitution().check_spec(spec)
    assert any(v.rule == "acceptance-criteria-required" for v in violations)


def test_unanswered_blocking_question_fails_the_spec_gate() -> None:
    spec = spec_with(open_questions=[Question(text="which source?", blocking=True)])
    violations = Constitution().check_spec(spec)
    assert any(
        v.rule == "no-blocking-unknowns" and v.severity is Severity.ERROR for v in violations
    )


def test_stale_plan_is_detected() -> None:
    spec = spec_with()
    plan = Plan(spec_id=spec.id, spec_hash="deadbeef", test_strategy="bdd")
    assert any(v.rule == "stale-plan" for v in Constitution().check_plan(plan, spec))


def test_banned_practice_in_a_plan_is_caught() -> None:
    constitution = Constitution(
        banned_practices=["No direct database connections from API route handlers."]
    )
    plan = Plan(
        spec_id="s",
        spec_hash="h",
        test_strategy="bdd",
        architecture="the API route handler opens a direct database connection per request",
    )
    assert any(v.rule == "banned-practice" for v in constitution.check_plan(plan))


def test_test_parity_requires_a_test_task_per_must_requirement() -> None:
    spec = spec_with()
    graph = TaskGraph(
        plan_id="p",
        plan_hash="h",
        tasks=[TaskUnit(id="T-001", title="implement", requirement_ids=["REQ-001"])],
    )
    assert any(v.rule == "test-parity" for v in Constitution().check_tasks(graph, spec))


def test_diff_gate_allows_additive_patches_but_blocks_rewrites() -> None:
    golden = "jobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: pytest -q\n"
    additive = golden + "      - run: ruff check .\n"
    rewrite = "jobs:\n  everything:\n    runs-on: self-hosted\n    steps:\n      - run: make\n"
    constitution = Constitution()

    assert constitution.diff_gate(golden, additive).allowed
    blocked = constitution.diff_gate(golden, rewrite)
    assert not blocked.allowed
    assert blocked.removed_topology


# ── IR models ─────────────────────────────────────────────────────────────────


def test_content_hash_ignores_provenance_but_tracks_content() -> None:
    a = spec_with()
    b = spec_with()
    assert a.content_hash() == b.content_hash()  # different ids, same content
    b.requirements[0].statement = "something else"
    assert a.content_hash() != b.content_hash()


def test_task_graph_orders_and_detects_cycles() -> None:
    graph = TaskGraph(
        plan_id="p",
        plan_hash="h",
        tasks=[
            TaskUnit(id="T-002", title="impl", depends_on=["T-001"]),
            TaskUnit(id="T-001", title="test"),
        ],
    )
    assert [t.id for t in graph.topological_order()] == ["T-001", "T-002"]
    assert [t.id for t in graph.ready()] == ["T-001"]

    graph.tasks[1].depends_on = ["T-002"]
    with pytest.raises(CycleError):
        graph.topological_order()


# ── Stages ────────────────────────────────────────────────────────────────────


def test_pm_stage_extracts_traceable_requirements(config: SpecKitConfig) -> None:
    spec = PMStage(config).draft(meeting_objective())
    ids = [r.id for r in spec.requirements]

    assert ids == sorted(ids) and ids[0] == "REQ-001"
    assert all(r.acceptance_criteria for r in spec.requirements)
    assert any("out of scope" in s.lower() for s in spec.out_of_scope)
    assert any("snowflake" in r.statement.lower() for r in spec.requirements)


def test_architect_injects_past_pitfalls_as_warnings(config: SpecKitConfig, hub: MemoryHub) -> None:
    hub.store(
        MemoryCase(
            title="churn report",
            objective="weekly churn report for sales",
            pitfalls=["Snowflake credentials rotate weekly — read them from the vault"],
            outcome="failure",
            tags=["reporting"],
        )
    )
    spec = PMStage(config).draft(meeting_objective())
    plan = ArchitectStage(config).draft(spec, hub.retrieve("weekly churn report for sales"))

    assert plan.historical_warnings
    assert plan.spec_hash == spec.content_hash()
    assert any(r.source == "memory" for r in plan.risks)


def test_planner_puts_the_test_before_the_code(config: SpecKitConfig) -> None:
    spec = PMStage(config).draft(meeting_objective())
    plan = ArchitectStage(config).draft(spec)
    graph = TaskPlanner(config).build(plan, spec)

    for task in graph.tasks:
        if (
            task.kind is TaskKind.CODE
            and task.requirement_ids
            and task.title.startswith("Implement")
        ):
            deps = [graph.by_id(d) for d in task.depends_on]
            assert any(d and d.kind is TaskKind.TEST for d in deps)
    assert not Constitution().check_tasks(graph, spec)


def test_worker_blocks_dependents_of_a_failed_task(config: SpecKitConfig) -> None:
    spec = PMStage(config).draft(meeting_objective())
    plan = ArchitectStage(config).draft(spec)
    graph = TaskPlanner(config).build(plan, spec)
    first = graph.topological_order()[0]

    def failing(task: TaskUnit, _spec: Spec) -> WorkResult:
        if task.id == first.id:
            return WorkResult(task_id=task.id, status=TaskStatus.FAILED, error="boom")
        return WorkResult(task_id=task.id, status=TaskStatus.DONE)

    results = WorkerStage(failing).execute(graph, spec)
    blocked = [r for r in results if r.status is TaskStatus.BLOCKED]
    assert blocked and all(r.summary == "upstream task failed" for r in blocked)


def test_qa_fences_out_of_scope_criteria(config: SpecKitConfig) -> None:
    config.qa.out_of_scope = ["load testing"]
    spec = spec_with()
    spec.requirements.append(
        Requirement(
            id="REQ-002",
            statement="load testing of the report endpoint",
            acceptance_criteria=[
                AcceptanceCriterion(id="REQ-002-AC-001", given="a", when="b", then="c")
            ],
        )
    )
    graph = TaskGraph(plan_id="p", plan_hash="h", tasks=[])

    report = QAStage(config).verify(spec, graph, [])

    assert "REQ-002-AC-001" in report.out_of_scope_ignored
    assert all(c.requirement_id != "REQ-002" for c in report.checks)


def test_qa_summary_stays_short_and_hides_logs(config: SpecKitConfig) -> None:
    spec = PMStage(config).draft(meeting_objective())
    plan = ArchitectStage(config).draft(spec)
    graph = TaskPlanner(config).build(plan, spec)
    results = WorkerStage().execute(graph, spec)

    report = QAStage(config).verify(spec, graph, results)

    assert report.verdict is QAVerdict.PASS
    assert report.coverage == 1.0
    assert len(report.summary_lines()) <= config.qa.communication.max_summary_lines
    assert report.environment_cleaned


def test_qa_fails_when_a_must_criterion_is_unverified(config: SpecKitConfig) -> None:
    spec = spec_with()
    graph = TaskGraph(plan_id="p", plan_hash="h", tasks=[])
    report = QAStage(config).verify(spec, graph, [])

    assert report.verdict is QAVerdict.FAIL
    assert report.findings[0].severity == "blocker"


# ── Memory hub ────────────────────────────────────────────────────────────────


def test_hub_writes_markdown_and_prefers_failures(hub: MemoryHub) -> None:
    hub.store(MemoryCase(title="ok run", objective="weekly churn report", outcome="success"))
    hub.store(
        MemoryCase(
            title="bad run",
            objective="weekly churn report",
            outcome="failure",
            pitfalls=["the warehouse view lags by a day"],
        )
    )
    report = hub.retrieve("weekly churn report")

    assert report.matches[0].case.outcome == "failure"
    assert any("lags by a day" in w for w in report.warnings())
    assert list(Path(hub.path).glob("*.md"))


def test_harvest_records_a_case_from_a_run(pipeline: DeliveryPipeline, hub: MemoryHub) -> None:
    state = pipeline.start(meeting_objective())
    assert state.case_id
    case = next(c for c in hub.all_cases() if c.id == state.case_id)
    assert case.requirement_ids
    assert "# " in case.to_markdown()


# ── Router ────────────────────────────────────────────────────────────────────


def test_router_prefers_intent_route_then_role_default(config: SpecKitConfig) -> None:
    router = EngineRouter(config)
    assert router.decide("pm_agent").engine == config.engine_for("pm_agent")
    config.agents.intent_routes = {"terraform": "engine-x"}
    assert router.decide("pm_agent", "rewrite the terraform module").engine == "engine-x"


def test_router_degrades_when_an_engine_raises(config: SpecKitConfig) -> None:
    def explode(_call: EngineCall) -> str:
        raise RuntimeError("engine down")

    router = EngineRouter(config)
    router.register(config.engine_for("pm_agent"), CallableEngine("boom", explode))

    out = router.run(EngineCall(role="pm_agent", system="s", prompt="p"))

    assert out == ""
    assert router.history[-1].ok is False


def test_engine_output_enriches_the_spec_summary(config: SpecKitConfig) -> None:
    router = EngineRouter(config)
    router.register(
        config.engine_for("pm_agent"), CallableEngine("stub", lambda call: "engine summary")
    )
    spec = PMStage(config, router).draft(meeting_objective())
    assert spec.summary == "engine summary"


# ── Pipeline ──────────────────────────────────────────────────────────────────


def test_happy_path_runs_to_delivery(pipeline: DeliveryPipeline) -> None:
    state = pipeline.start(meeting_objective())

    assert state.stage is Stage.DONE
    assert state.spec and state.plan and state.tasks and state.qa and state.delivery
    assert state.delivery.accepted
    assert [e.stage for e in state.events][0] is Stage.INTAKE


def test_unclear_objective_pauses_for_a_human(pipeline: DeliveryPipeline) -> None:
    state = pipeline.start(Objective(statement="Make it better", submitted_by="sam"))

    assert state.stage is Stage.CLARIFY
    assert state.awaiting_human
    assert state.spec is None
    assert state.clarification and state.clarification.meeting


def test_meeting_unblocks_the_run(pipeline: DeliveryPipeline) -> None:
    state = pipeline.start(Objective(statement="Make the dashboard faster", submitted_by="sam"))
    assert state.awaiting_human

    answers = {
        q.id: "p95 under 800ms from a 3.2s baseline, measured in Grafana"
        for q in state.pending_questions()
    }
    state = pipeline.hold_meeting(state, "Ops owns sign-off. Baseline 3.2s, target 800ms.", answers)

    assert state.stage is Stage.DONE
    assert state.spec is not None


def test_delivery_surfaces_unconfirmed_assumptions(pipeline: DeliveryPipeline) -> None:
    state = pipeline.start(meeting_objective())
    assert state.delivery is not None
    assert all(not a.confirmed for a in state.delivery.unconfirmed_assumptions)


def test_run_state_round_trips_through_json(pipeline: DeliveryPipeline, tmp_path: Path) -> None:
    state = pipeline.start(meeting_objective())
    path = save_state(state, tmp_path)
    restored = load_state(path)

    assert restored.id == state.id
    assert restored.stage is state.stage
    assert [r.id for r in restored.spec.requirements] == [r.id for r in state.spec.requirements]
    assert json.loads(path.read_text())["objective"]["statement"] == state.objective.statement


def test_components_group_requirements_by_domain(config: SpecKitConfig) -> None:
    spec = PMStage(config).draft(meeting_objective())
    plan = ArchitectStage(config).draft(spec)
    names = {c.name for c in plan.components}

    assert names  # every requirement lands in exactly one component
    assert sum(len(c.requirement_ids) for c in plan.components) == len(spec.requirements)
    assert all(isinstance(c, Component) for c in plan.components)


def test_must_priority_is_the_default_for_unmarked_requirements() -> None:
    spec = spec_with()
    assert spec.requirements[0].priority is Priority.MUST
