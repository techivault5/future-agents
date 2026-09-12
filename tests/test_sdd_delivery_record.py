"""The semantic layer, the work breakdown, the issues, the metrics, the record.

What these tests hold in place: an ask is read in one vocabulary and says when a
word is still ambiguous; every task lands in a tracked item; the issues that come
out are postable without a GitHub client anywhere near this package; every item
carries numbers that name the question they answer; and the project record cannot
claim more than the run actually did.
"""

from __future__ import annotations

import json

import pytest
from future_agents.sdd import (
    DeliveryPipeline,
    DryRunPublisher,
    ExternalRef,
    IntakeSource,
    IssueBuilder,
    JsonlPublisher,
    MetricPlanner,
    Objective,
    ProjectDocs,
    SemanticLayer,
    SpecKitConfig,
    WorkBreakdownBuilder,
    WorkItemKind,
    publish_breakdown,
)
from future_agents.sdd.models import (
    AcceptanceCriterion,
    ConceptKind,
    Priority,
    Requirement,
    Spec,
    TaskKind,
)


def spec_with(*statements: str, title: str = "Refund tooling", summary: str = "") -> Spec:
    requirements = [
        Requirement(
            id=f"REQ-{index:03d}",
            statement=statement,
            priority=Priority.MUST,
            acceptance_criteria=[
                AcceptanceCriterion(
                    id=f"REQ-{index:03d}-AC-001",
                    given="the feature is live",
                    when="it is used",
                    then=statement,
                )
            ],
        )
        for index, statement in enumerate(statements, start=1)
    ]
    return Spec(objective_id="obj-1", title=title, summary=summary, requirements=requirements)


def objective(statement: str, **kwargs) -> Objective:
    return Objective(statement=statement, source=IntakeSource.TICKET, **kwargs)


@pytest.fixture
def pipeline() -> DeliveryPipeline:
    config = SpecKitConfig()
    config.memory_hub.enabled = False
    return DeliveryPipeline(config)


# ── The semantic layer ────────────────────────────────────────────────────────


def test_the_ask_resolves_to_actor_action_entity() -> None:
    model = SemanticLayer().build(spec_with("Support must refund an order"))

    capability = model.capabilities[0]

    assert capability.actor == "support"
    assert capability.action == "refund"
    assert capability.entity == "order"


def test_a_word_with_two_readings_is_recorded_not_guessed() -> None:
    model = SemanticLayer().build(spec_with("Support must refund an order"))

    refund = next(c for c in model.concepts if c.canonical == "refund")

    assert refund.ambiguous
    assert len(refund.readings) == 2
    assert any("refund" in item for item in model.ambiguities)


def test_a_criterion_that_settles_the_meaning_ends_the_ambiguity() -> None:
    spec = spec_with("Support must refund an order")
    spec.requirements[0].acceptance_criteria[
        0
    ].then = "a reversal of the original payment is issued to the customer's card"

    model = SemanticLayer().build(spec)

    refund = next(c for c in model.concepts if c.canonical == "refund")
    assert not refund.ambiguous
    assert "reversal" in refund.definition


def test_the_requirement_decides_its_own_capability() -> None:
    """A term that recurs elsewhere must not hijack a requirement it barely touches."""
    model = SemanticLayer().build(
        spec_with(
            "Support must refund an order",
            "The ledger must reconcile every refund nightly",
        )
    )

    second = model.capability_for("REQ-002")

    assert second is not None
    assert second.action == "reconcile", "the loudest term in the spec is not this requirement's"


def test_grammar_words_never_become_concepts() -> None:
    model = SemanticLayer().build(
        spec_with("Support must be able to refund an order that was recorded yesterday")
    )

    canonical = {c.canonical for c in model.concepts}

    assert "able" not in canonical
    assert "recorded" not in canonical, "a participle describes a thing, it does not name one"
    assert "order" in canonical


def test_the_thought_process_is_recorded() -> None:
    model = SemanticLayer().build(spec_with("Support must refund an order"))

    assert len(model.trace) >= 3
    assert any("capability" in step for step in model.trace)


def test_named_systems_are_recognised_as_systems() -> None:
    model = SemanticLayer().build(spec_with("Export refunds to Snowflake nightly"))

    kinds = {c.canonical: c.kind for c in model.concepts}

    assert kinds.get("snowflake") is ConceptKind.SYSTEM


# ── The work breakdown ────────────────────────────────────────────────────────


def test_every_task_lands_in_a_tracked_item(pipeline: DeliveryPipeline) -> None:
    state = pipeline.start(objective("Support must be able to refund an order without help"))

    tracked = {task_id for item in state.breakdown.items for task_id in item.task_ids}

    assert tracked == {task.id for task in state.tasks.tasks}, "nothing small goes untracked"


def test_the_tree_is_an_epic_with_children(pipeline: DeliveryPipeline) -> None:
    state = pipeline.start(objective("Support must be able to refund an order without help"))
    breakdown = state.breakdown

    root = breakdown.root()

    assert root is not None and root.kind is WorkItemKind.EPIC
    assert breakdown.children(root.id), "an epic with no children is just a ticket"
    assert breakdown.coverage([r.id for r in state.spec.requirements]) == 1.0


def test_a_bug_report_is_tracked_as_a_fix_not_a_feature() -> None:
    spec = spec_with("The nightly export is broken and drops the last row")

    breakdown = WorkBreakdownBuilder().build(objective(spec.requirements[0].statement), spec)

    item = next(i for i in breakdown.items if not i.is_root)
    assert item.kind is WorkItemKind.FIX
    assert any("reproduces the failure" in entry for entry in item.definition_of_done)


def test_a_migration_keeps_its_rollback_in_the_definition_of_done() -> None:
    spec = spec_with("Migrate the ledger table to the new schema")

    breakdown = WorkBreakdownBuilder().build(objective(spec.requirements[0].statement), spec)

    item = next(i for i in breakdown.items if not i.is_root)
    assert item.kind is WorkItemKind.MIGRATION
    assert any("rollback" in entry.lower() for entry in item.definition_of_done)


def test_an_integration_is_told_to_keep_credentials_out_of_the_code() -> None:
    spec = spec_with("Integrate with the Stripe webhook for refund events")

    breakdown = WorkBreakdownBuilder().build(objective(spec.requirements[0].statement), spec)

    item = next(i for i in breakdown.items if not i.is_root)
    assert item.kind is WorkItemKind.INTEGRATION
    assert any("environment" in entry for entry in item.definition_of_done)


def test_who_asked_reaches_every_item(pipeline: DeliveryPipeline) -> None:
    state = pipeline.start(
        objective(
            "Support must be able to refund an order without help",
            submitted_by="dana",
            external=ExternalRef(
                system="github", id="482", url="https://example.test/482", author="dana"
            ),
        )
    )

    assert all(item.requested_by == "dana" for item in state.breakdown.items)
    assert all(item.source == "github:482" for item in state.breakdown.items)


# ── Issues ────────────────────────────────────────────────────────────────────


def test_the_epic_carries_a_sub_issue_task_list(pipeline: DeliveryPipeline) -> None:
    state = pipeline.start(objective("Support must be able to refund an order without help"))
    payloads = IssueBuilder(state.spec).build(state.breakdown)

    epic = payloads[0]

    assert epic.title.startswith("[EPIC]")
    assert "## Sub-issues" in epic.body
    assert "- [ ] `WI-002`" in epic.body


def test_a_sub_issue_names_its_parent_and_its_criteria(pipeline: DeliveryPipeline) -> None:
    state = pipeline.start(objective("Support must be able to refund an order without help"))
    payloads = IssueBuilder(state.spec).build(state.breakdown)

    child = payloads[1]

    assert child.parent_work_item_id == payloads[0].work_item_id
    assert child.body.startswith("Parent: ")
    assert "- [ ] `REQ-001-AC-001`" in child.body


def test_an_issue_says_where_the_code_goes_and_where_it_must_not(tmp_path) -> None:
    repo = tmp_path / "billing"
    (repo / "src").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname = 'billing'\n")
    (repo / "AGENTS.md").write_text(
        "| A new agent type | `src/agents/<name>_agent.py` | subclass BaseAgent |\n"
    )
    config = SpecKitConfig()
    config.memory_hub.enabled = False
    state = DeliveryPipeline(config, repo_root=str(repo)).start(
        objective("Add a purchase-order agent so that finance stops keying orders by hand")
    )

    payloads = IssueBuilder(state.spec).build(state.breakdown)
    feature = next(p for p in payloads if p.kind == "feature")

    assert "Goes in: " in feature.body


def test_every_issue_ends_with_its_traceability(pipeline: DeliveryPipeline) -> None:
    state = pipeline.start(objective("Support must be able to refund an order without help"))

    for payload in IssueBuilder(state.spec).build(state.breakdown):
        assert "Traceability: " in payload.body
        assert payload.body.rstrip().endswith("_Opened by spec-driven delivery._")


def test_the_github_payload_is_what_the_api_wants(pipeline: DeliveryPipeline) -> None:
    state = pipeline.start(objective("Support must be able to refund an order without help"))
    payload = IssueBuilder(state.spec).build(state.breakdown)[0]

    github = payload.to_github()

    assert set(github) == {"title", "body", "labels", "assignees"}
    assert len(github["body"]) <= 60000


# ── Publishing ────────────────────────────────────────────────────────────────


def test_publishing_is_a_dry_run_unless_a_poster_is_given(pipeline: DeliveryPipeline) -> None:
    state = pipeline.start(objective("Support must be able to refund an order without help"))

    report = publish_breakdown(state.breakdown, IssueBuilder(state.spec))

    assert report.dry_run is True
    assert len(report.created) == len(state.breakdown.items)


def test_children_learn_their_parent_issue_number(pipeline: DeliveryPipeline) -> None:
    state = pipeline.start(objective("Support must be able to refund an order without help"))
    builder = IssueBuilder(state.spec)

    report = publish_breakdown(state.breakdown, builder, DryRunPublisher())

    epic_ref = report.created[state.breakdown.root().id]
    child = next(i for i in state.breakdown.items if i.parent_id == state.breakdown.root().id)
    body = next(p for p in builder.build(state.breakdown) if p.work_item_id == child.id).body
    assert f"Parent: {epic_ref}" in body, "a sub-issue must point at a real issue"


def test_a_posters_failure_is_recorded_not_raised(pipeline: DeliveryPipeline) -> None:
    state = pipeline.start(objective("Support must be able to refund an order without help"))

    class Broken:
        def create(self, payload):  # noqa: ANN001
            raise RuntimeError("rate limited")

    report = publish_breakdown(state.breakdown, IssueBuilder(state.spec), Broken())

    assert report.created == {}
    assert "rate limited" in next(iter(report.failed.values()))


def test_jsonl_publishing_hands_over_postable_payloads(
    pipeline: DeliveryPipeline, tmp_path
) -> None:
    state = pipeline.start(objective("Support must be able to refund an order without help"))
    target = tmp_path / "issues.jsonl"

    publish_breakdown(state.breakdown, IssueBuilder(state.spec), JsonlPublisher(target))

    records = [json.loads(line) for line in target.read_text().splitlines()]
    assert len(records) == len(state.breakdown.items)
    assert records[0]["parent_work_item_id"] == ""
    assert records[1]["parent_work_item_id"] == records[0]["work_item_id"]
    assert {"title", "body", "labels"} <= set(records[0])


# ── Metrics ───────────────────────────────────────────────────────────────────


def test_every_metric_names_the_question_it_answers(pipeline: DeliveryPipeline) -> None:
    state = pipeline.start(objective("Support must be able to refund an order without help"))

    assert state.metrics is not None
    assert all(metric.question for metric in state.metrics.specs)


def test_the_outcome_metric_is_named_even_when_it_cannot_be_measured(
    pipeline: DeliveryPipeline,
) -> None:
    state = pipeline.start(
        objective("Support must refund an order so that customers stop waiting on engineering")
    )

    unbound = [m for m in state.metrics.specs if m.source == "unbound"]

    assert unbound, "the outcome the asker cared about must be visible, not silently dropped"
    assert all("Did this move the outcome" in m.question for m in unbound)


def test_quality_metrics_read_from_qa_not_from_claims(pipeline: DeliveryPipeline) -> None:
    state = pipeline.start(objective("Support must be able to refund an order without help"))

    quality = [m for m in state.metrics.specs if m.source == "qa"]

    assert quality and all(m.target == 1.0 for m in quality)


def test_reliability_metrics_come_from_the_objectives_themselves(
    pipeline: DeliveryPipeline,
) -> None:
    state = pipeline.start(objective("Support must be able to refund an order without help"))

    reliability = [m for m in state.metrics.specs if m.source == "observability"]

    assert reliability
    slo_ids = {slo.id for slo in state.plan.observability.slos}
    assert all(any(sid in m.name for sid in slo_ids) for m in reliability)


def test_a_metric_with_no_target_is_never_reported_as_missed() -> None:
    spec = spec_with("Support must refund an order")
    breakdown = WorkBreakdownBuilder().build(objective(spec.requirements[0].statement), spec)

    metrics = MetricPlanner().build(breakdown)

    assert metrics.unmet() == []
    assert all(m.met is not False for m in metrics.specs)


# ── The project record ────────────────────────────────────────────────────────


def test_the_record_has_the_same_shape_every_time(pipeline: DeliveryPipeline) -> None:
    state = pipeline.start(objective("Support must be able to refund an order without help"))

    docs = ProjectDocs().build(
        state, semantics=state.semantics, breakdown=state.breakdown, metrics=state.metrics
    )

    assert set(docs.files) == {
        "README.md",
        "01-objective.md",
        "02-semantics.md",
        "03-architecture.md",
        "04-work-breakdown.md",
        "05-implementation.md",
        "06-qa.md",
        "07-observability.md",
        "08-metrics.md",
        "09-decisions.md",
        "10-changelog.md",
    }


def test_the_record_says_who_asked_and_from_where(pipeline: DeliveryPipeline) -> None:
    state = pipeline.start(
        objective(
            "Support must be able to refund an order without help",
            submitted_by="dana",
            external=ExternalRef(system="github", id="482", url="https://example.test/482"),
        )
    )

    body = ProjectDocs().build(state).files["01-objective.md"]

    assert "dana" in body
    assert "https://example.test/482" in body


def test_the_architecture_document_draws_itself(pipeline: DeliveryPipeline) -> None:
    state = pipeline.start(objective("Support must be able to refund an order without help"))

    body = ProjectDocs().build(state, semantics=state.semantics).files["03-architecture.md"]

    assert body.count("```mermaid") == 2, "structure and traceability, both from the plan"
    assert "REQ-001" in body


def test_a_stage_that_never_ran_says_so_rather_than_going_missing() -> None:
    config = SpecKitConfig()
    config.memory_hub.enabled = False
    state = DeliveryPipeline(config).start(objective("Improve things somehow, quickly"))

    docs = ProjectDocs().build(state)

    assert "Nothing recorded" in docs.files["06-qa.md"]
    assert "01-objective.md" in docs.files, "the ask is recorded even when nothing else is"


def test_the_record_is_written_into_the_repository(tmp_path) -> None:
    repo = tmp_path / "billing"
    (repo / "src").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname = 'billing'\n")
    config = SpecKitConfig()
    config.memory_hub.enabled = False

    state = DeliveryPipeline(config, repo_root=str(repo)).start(
        objective("Support must be able to refund an order without help")
    )

    assert len(state.documents) == 11
    index = repo / "docs/projects/index.md"
    assert index.is_file()
    assert state.id in index.read_text(), "the index lists every delivery"


def test_writing_the_record_twice_does_not_duplicate_the_index_row(tmp_path) -> None:
    repo = tmp_path / "billing"
    (repo / "src").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname = 'billing'\n")
    config = SpecKitConfig()
    config.memory_hub.enabled = False
    pipeline = DeliveryPipeline(config, repo_root=str(repo))

    state = pipeline.start(objective("Support must be able to refund an order without help"))
    ProjectDocs().write(
        state, repo, semantics=state.semantics, breakdown=state.breakdown, metrics=state.metrics
    )

    index = (repo / "docs/projects/index.md").read_text()
    assert index.count(state.id) == 1


def test_documents_can_be_switched_off(tmp_path) -> None:
    repo = tmp_path / "billing"
    (repo / "src").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname = 'billing'\n")
    config = SpecKitConfig()
    config.memory_hub.enabled = False
    config.project_docs.enabled = False

    state = DeliveryPipeline(config, repo_root=str(repo)).start(
        objective("Support must be able to refund an order without help")
    )

    assert state.documents == []
    assert not (repo / "docs/projects").exists()


# ── End to end ────────────────────────────────────────────────────────────────


def test_one_run_produces_the_whole_chain(pipeline: DeliveryPipeline) -> None:
    """Ask → meaning → items → issues → metrics → record, all traceable."""
    state = pipeline.start(
        objective(
            "Support must be able to refund an order so that customers stop waiting",
            submitted_by="dana",
        )
    )

    assert state.semantics is not None and state.semantics.capabilities
    assert state.breakdown is not None and state.breakdown.root() is not None
    assert state.metrics is not None and state.metrics.specs

    payloads = IssueBuilder(state.spec, state.plan.observability, state.metrics, state.qa).build(
        state.breakdown
    )
    assert len(payloads) == len(state.breakdown.items)

    # Every requirement is reachable from the epic, through an item, to a task.
    epic = state.breakdown.root()
    reachable = {
        rid for item in state.breakdown.items if item.id != epic.id for rid in item.requirement_ids
    }
    assert reachable == {r.id for r in state.spec.requirements}

    observability_items = [i for i in state.breakdown.items if i.kind is WorkItemKind.OBSERVABILITY]
    assert observability_items, "monitoring is tracked work, not an afterthought"
    assert all(
        task.kind is TaskKind.OBSERVABILITY
        for item in observability_items
        for task in state.tasks.tasks
        if task.id in item.task_ids
    )
