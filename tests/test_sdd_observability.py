"""Observability — the scope every feature carries.

The properties under test are the ones that decide whether monitoring is real or
ceremonial: does every feature get objectives derived from what it actually
promised, does the instrumentation become scheduled work, does the gate notice
when it is missing, and does QA tell the truth about whether it ran.
"""

from __future__ import annotations

import pytest
from future_agents.sdd import (
    DeliveryPipeline,
    IntakeSource,
    Objective,
    SpecKitConfig,
    render_runbook,
    telemetry_for,
)
from future_agents.sdd.constitution import Severity
from future_agents.sdd.models import (
    AcceptanceCriterion,
    Component,
    Plan,
    Priority,
    Requirement,
    Spec,
    TaskKind,
    TaskStatus,
    WorkResult,
)
from future_agents.sdd.observability import ObservabilityPlanner
from future_agents.sdd.repos.languages import toolchain_for


def spec_with(*statements: str, criteria: dict[str, str] | None = None) -> Spec:
    """A spec whose criteria can be steered per requirement."""
    requirements = []
    for index, statement in enumerate(statements, start=1):
        rid = f"REQ-{index:03d}"
        then = (criteria or {}).get(rid, statement)
        requirements.append(
            Requirement(
                id=rid,
                statement=statement,
                priority=Priority.MUST,
                acceptance_criteria=[
                    AcceptanceCriterion(
                        id=f"{rid}-AC-001",
                        given="the feature is live",
                        when="it is used",
                        then=then,
                    )
                ],
            )
        )
    return Spec(objective_id="obj-1", title="Refund tooling", requirements=requirements)


def components(*names: str) -> list[Component]:
    return [
        Component(
            name=name,
            responsibility=f"{name} work",
            requirement_ids=[f"REQ-{i:03d}" for i in range(1, 2)],
            target_path=f"src/{name}.py",
        )
        for name in names
    ]


# ── Signals ───────────────────────────────────────────────────────────────────


def test_every_component_gets_the_three_questions_answered() -> None:
    plan = ObservabilityPlanner().build(spec_with("Refunds must succeed"), components("core"))

    instruments = {s.instrument for s in plan.signals_for("core")}

    assert {"counter", "histogram", "span"} <= instruments, (
        "is it running, is it slow, is it failing — nothing cheaper answers those"
    )


def test_a_signal_says_where_it_must_be_emitted_from() -> None:
    plan = ObservabilityPlanner().build(spec_with("Refunds must succeed"), components("core"))

    assert all(s.emitted_from == "src/core.py" for s in plan.signals_for("core"))


def test_unbounded_labels_never_reach_a_metric() -> None:
    config = SpecKitConfig().observability
    config.forbidden_labels = ["outcome", "user_id"]  # ban one the planner wants

    plan = ObservabilityPlanner(config).build(spec_with("Refunds must succeed"), components("core"))

    assert all("outcome" not in s.labels for s in plan.signals), (
        "cardinality is a design decision, not a discovery on the bill"
    )
    assert plan.gaps == []


def test_a_component_with_no_signals_is_reported_not_hidden() -> None:
    plan = ObservabilityPlanner().build(spec_with("Refunds must succeed"), [])

    assert any("no components" in gap for gap in plan.gaps)


# ── Objectives ────────────────────────────────────────────────────────────────


def test_a_deadline_in_the_requirement_becomes_a_latency_objective() -> None:
    plan = ObservabilityPlanner().build(
        spec_with("A refund must be recorded within 2 seconds"), components("core")
    )

    slo = plan.slos[0]

    assert slo.kind == "latency"
    assert slo.threshold_ms == 2000


def test_a_prohibition_becomes_a_correctness_objective() -> None:
    plan = ObservabilityPlanner().build(
        spec_with("The ledger must never double-count a refund"), components("core")
    )

    assert plan.slos[0].kind == "correctness"


def test_freshness_is_read_out_of_a_schedule() -> None:
    plan = ObservabilityPlanner().build(
        spec_with("Refund totals are refreshed nightly for finance"), components("core")
    )

    assert plan.slos[0].kind == "freshness"


def test_two_promises_in_one_requirement_earn_two_objectives() -> None:
    plan = ObservabilityPlanner().build(
        spec_with("A refund is recorded within 2 seconds and is never double-counted"),
        components("core"),
    )

    kinds = {slo.kind for slo in plan.slos}

    assert kinds == {"latency", "correctness"}, (
        "fast and wrong would otherwise read as green on a latency objective"
    )


def test_a_deadline_phrased_as_a_prohibition_is_still_one_promise() -> None:
    plan = ObservabilityPlanner().build(
        spec_with("The report must not take more than 30 seconds"), components("core")
    )

    assert [slo.kind for slo in plan.slos] == ["latency"]


def test_a_requirement_with_no_criteria_is_a_recorded_gap() -> None:
    spec = Spec(
        objective_id="obj-1",
        title="Refunds",
        requirements=[Requirement(id="REQ-001", statement="Refunds work", priority=Priority.MUST)],
    )

    plan = ObservabilityPlanner().build(spec, components("core"))

    assert plan.slos == []
    assert any("REQ-001" in gap for gap in plan.gaps)


# ── Alerts and the runbook ────────────────────────────────────────────────────


def test_each_objective_gets_a_fast_page_and_a_slow_ticket() -> None:
    plan = ObservabilityPlanner().build(spec_with("Refunds must succeed"), components("core"))
    alerts = plan.alerts_for(plan.slos[0].id)

    assert [a.severity for a in alerts] == ["page", "ticket"]
    assert alerts[0].burn_rate > alerts[1].burn_rate
    assert alerts[0].channel != alerts[1].channel


def test_no_alert_exists_without_a_runbook_to_answer_it() -> None:
    plan = ObservabilityPlanner().build(spec_with("Refunds must succeed"), components("core"))

    assert all(alert.runbook for alert in plan.alerts)
    assert all(alert.runbook.startswith(plan.runbook_path) for alert in plan.alerts)


def test_the_runbook_answers_the_three_am_question() -> None:
    spec = spec_with("A refund must be recorded within 2 seconds")
    plan = ObservabilityPlanner().build(spec, components("core"))

    text = render_runbook(plan, spec)

    assert "First five minutes" in text
    assert plan.slos[0].id.lower() in text, "every alert anchors into a section that exists"
    assert "dependency" in text, "latency burns get their own first check"


def test_sensitive_fields_are_named_as_never_loggable() -> None:
    spec = spec_with("Refunds must not expose payment details")
    spec.summary = "handles card payments"

    plan = ObservabilityPlanner().build(spec, components("core"))

    assert "card_number" in plan.redactions
    assert "Never log" in render_runbook(plan, spec)


# ── Language coverage ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("language", ["python", "typescript", "go", "java", "rust"])
def test_each_toolchain_knows_how_it_emits(language: str) -> None:
    stack = telemetry_for(language)

    assert stack.package and stack.api


def test_an_unknown_language_says_so_rather_than_inventing_a_package() -> None:
    plan = ObservabilityPlanner(toolchain=None).build(
        spec_with("Refunds must succeed"), components("core")
    )

    assert "language not detected" in plan.telemetry_stack


def test_the_repo_language_names_its_own_instrumentation() -> None:
    plan = ObservabilityPlanner(toolchain=toolchain_for("python")).build(
        spec_with("Refunds must succeed"), components("core")
    )

    assert "opentelemetry" in plan.telemetry_stack.lower()


# ── The gates ─────────────────────────────────────────────────────────────────


def test_a_plan_that_says_nothing_about_monitoring_is_flagged() -> None:
    config = SpecKitConfig()
    spec = spec_with("Refunds must succeed")
    plan = Plan(spec_id=spec.id, spec_hash=spec.content_hash(), test_strategy="unit")

    violations = config.constitution().check_plan(plan, spec)

    assert any(v.rule == "observability-required" for v in violations)


def test_the_gate_can_be_made_blocking() -> None:
    config = SpecKitConfig()
    config.observability.block_on_gap = True
    spec = spec_with("Refunds must succeed")
    plan = Plan(spec_id=spec.id, spec_hash=spec.content_hash(), test_strategy="unit")

    violations = config.constitution().check_plan(plan, spec)
    blocking = [v for v in violations if v.severity is Severity.ERROR]

    assert any(v.rule == "observability-required" for v in blocking)


def test_a_must_requirement_without_an_objective_is_named() -> None:
    config = SpecKitConfig()
    spec = spec_with("Refunds must succeed", "Chargebacks must reconcile")
    obs = ObservabilityPlanner().build(spec_with("Refunds must succeed"), components("core"))
    plan = Plan(
        spec_id=spec.id,
        spec_hash=spec.content_hash(),
        test_strategy="unit",
        components=components("core"),
        observability=obs,
    )

    violations = config.constitution().check_plan(plan, spec)

    assert any(
        v.rule == "observability-slo-for-must" and v.subject == "REQ-002" for v in violations
    )


# ── End to end ────────────────────────────────────────────────────────────────


def objective(statement: str, context: str = "") -> Objective:
    return Objective(statement=statement, context=context, source=IntakeSource.TICKET)


@pytest.fixture
def pipeline(tmp_path) -> DeliveryPipeline:
    """A pipeline whose memory is off, so each test starts from nothing."""
    config = SpecKitConfig()
    config.memory_hub.enabled = False
    return DeliveryPipeline(config)


def test_every_feature_that_gets_built_carries_its_monitoring(pipeline: DeliveryPipeline) -> None:
    state = pipeline.start(
        objective(
            "Support must be able to refund an order without engineering help",
            "Acceptance: the refund is recorded within 2 seconds.",
        )
    )

    obs = state.plan.observability
    assert obs is not None
    assert obs.signals and obs.slos and obs.alerts and obs.dashboards
    assert obs.runbook_path.endswith(".md")


def test_instrumentation_is_scheduled_work_not_an_intention(pipeline: DeliveryPipeline) -> None:
    state = pipeline.start(objective("Support must be able to refund an order without help"))

    obs_tasks = [t for t in state.tasks.tasks if t.kind is TaskKind.OBSERVABILITY]

    assert [t.title for t in obs_tasks][:1] == ["Instrument core"]
    assert any("runbook" in t.title.lower() for t in obs_tasks)
    # It depends on the code it instruments: you cannot measure what is not built.
    code_ids = {t.id for t in state.tasks.tasks if t.kind is TaskKind.CODE}
    assert set(obs_tasks[0].depends_on) & code_ids


def test_the_delivery_record_carries_the_runbook_and_the_objectives(
    pipeline: DeliveryPipeline,
) -> None:
    state = pipeline.start(objective("Support must be able to refund an order without help"))

    assert state.delivery.runbook_path
    assert state.delivery.slo_summary
    assert any("SLO-" in line for line in state.delivery.slo_summary)


def test_qa_reports_instrumentation_that_never_ran(pipeline: DeliveryPipeline) -> None:
    state = pipeline.start(objective("Support must be able to refund an order without help"))
    graph = state.tasks
    obs_tasks = [t for t in graph.tasks if t.kind is TaskKind.OBSERVABILITY]

    # Everything ran except the telemetry — the classic "we'll add metrics later".
    results = [
        WorkResult(task_id=t.id, status=TaskStatus.DONE, summary="done")
        for t in graph.tasks
        if t.kind is not TaskKind.OBSERVABILITY
    ]
    report = pipeline.qa.verify(state.spec, graph, results)

    assert report.observability_coverage == 0.0
    assert len(obs_tasks) > 0
    assert any(f.summary.startswith(obs_tasks[0].id) for f in report.findings)


def test_a_run_in_a_repo_writes_the_runbook_the_alerts_point_at(tmp_path) -> None:
    repo = tmp_path / "billing"
    (repo / "src").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname = 'billing'\n")
    config = SpecKitConfig()
    config.memory_hub.enabled = False

    pipeline = DeliveryPipeline(config, repo_root=str(repo))
    state = pipeline.start(objective("Support must be able to refund an order without help"))

    written = repo / state.delivery.runbook_path
    assert written.is_file(), "an alert may not reference a file nobody generated"
    assert "First five minutes" in written.read_text()


def test_monitoring_can_be_switched_off_wholesale(tmp_path) -> None:
    config = SpecKitConfig()
    config.observability.enabled = False
    config.memory_hub.enabled = False

    state = DeliveryPipeline(config).start(
        objective("Support must be able to refund an order without engineering help")
    )

    assert state.plan.observability is None
    assert not [t for t in state.tasks.tasks if t.kind is TaskKind.OBSERVABILITY]
