"""The delivery pipeline — one objective, driven to a delivery record.

intake → clarify → spec → plan → tasks → work → qa → deliver → harvest

The pipeline holds no state of its own: everything lives in `RunState`, which
serialises to JSON, so a run can pause for a human answer (or a meeting) for
days and resume in a different process.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

from future_agents.sdd.clarify import IntentClarifier
from future_agents.sdd.config import SpecKitConfig
from future_agents.sdd.constitution import Severity, Violation
from future_agents.sdd.execution.resilience import BudgetExceeded, BudgetGuard
from future_agents.sdd.knowledge import RepoKnowledge
from future_agents.sdd.memory import MemoryHub
from future_agents.sdd.models import (
    Budget,
    ClarificationOutcome,
    Objective,
    PipelineEvent,
    RunState,
    Stage,
)
from future_agents.sdd.personas import DEFAULT_PERSONA, Persona
from future_agents.sdd.project_docs import ProjectDocs
from future_agents.sdd.repos.languages import RepoProfile, Toolchain, detect_repo
from future_agents.sdd.router import EngineRouter
from future_agents.sdd.semantics import SemanticLayer
from future_agents.sdd.stages import (
    ArchitectStage,
    DeliveryStage,
    PMStage,
    QAStage,
    TaskPlanner,
    WorkerBackend,
    WorkerStage,
)
from future_agents.sdd.tracking import (
    MetricPlanner,
    WorkBreakdownBuilder,
)

EventSink = Callable[[PipelineEvent], None]


class DeliveryPipeline:
    """Wires the stages together and enforces the constitution between them."""

    def __init__(
        self,
        config: Optional[SpecKitConfig] = None,
        memory: Optional[MemoryHub] = None,
        router: Optional[EngineRouter] = None,
        backend: Optional[WorkerBackend] = None,
        on_event: Optional[EventSink] = None,
        persona: Optional[Persona] = None,
        repo_root: Optional[str] = None,
        profile: Optional[RepoProfile] = None,
        knowledge: Optional[RepoKnowledge] = None,
        budget: Optional[Budget] = None,
    ) -> None:
        base = config or SpecKitConfig()
        self.persona = persona or DEFAULT_PERSONA
        # The persona tunes the rulebook it works under: how hard it interrogates
        # intent, which gates are mandatory, what coverage it accepts.
        self.config = self.persona.apply_to_config(base)
        self.router = router or EngineRouter(self.config)
        # Memory is scoped to the repository under work: a lesson learned in the
        # billing service is evidence about the billing service, and only a hint
        # anywhere else.
        self.scope = _scope_of(repo_root)
        self.memory = memory or MemoryHub(self.config.memory_hub, scope=self.scope)
        self.constitution = self.config.constitution()
        self.on_event = on_event
        self.repo_root = repo_root
        self.profile = profile or (detect_repo(repo_root) if repo_root else None)
        self.toolchain: Optional[Toolchain] = self.profile.toolchain() if self.profile else None
        # Indexed once per pipeline: the spec, the plan and every task read from it.
        self.knowledge = knowledge or (
            RepoKnowledge.build(repo_root, profile=self.profile) if repo_root else None
        )

        # A run that cannot exceed its ceilings cannot become a cost incident.
        self.budget = budget or Budget()

        self.clarifier = IntentClarifier(self.config, recall=self._recall)
        self.pm = PMStage(self.config, self.router, self.knowledge)
        self.architect = ArchitectStage(
            self.config, self.router, self.persona, self.toolchain, self.knowledge
        )
        self.planner = TaskPlanner(
            self.config, self.router, self.persona, self.toolchain, self.repo_root
        )
        self.worker = WorkerStage(backend)
        self.qa = QAStage(self.config)
        # The ask is read once, in one vocabulary, and every artifact after this
        # point — plan, issues, docs, metrics — uses the same words for it.
        self.semantics = SemanticLayer(self.knowledge)
        self.breakdown = WorkBreakdownBuilder(repo=self.scope)
        self.metrics = MetricPlanner()
        self.docs = ProjectDocs(self.config.project_docs.directory)
        self.delivery = DeliveryStage(repo_root=self.repo_root)

    def _recall(self, question: str, topic: str, blocking: bool) -> Optional[tuple[str, str]]:
        """Adapt the memory hub to the clarifier's plain-callable recall hook."""
        remembered = self.memory.recall_answer(
            question, topic=topic, blocking=blocking, scope=self.scope
        )
        return (remembered.answer, remembered.basis) if remembered else None

    # ── Entry points ──────────────────────────────────────────────────────────

    def start(self, objective: Objective) -> RunState:
        state = RunState(objective=objective, budget=self.budget.model_copy(deep=True))
        self._log(
            state,
            Stage.INTAKE,
            f"objective accepted from {objective.source.value}",
            persona=self.persona.id,
            toolchain=self.toolchain.language if self.toolchain else None,
        )
        return self._clarify(state)

    def answer(
        self, state: RunState, answers: dict[str, str], answered_by: str = "human"
    ) -> RunState:
        """Fold async answers back in and continue (or ask the next round)."""
        if not state.clarification:
            return state
        state.clarification = self.clarifier.apply_answers(
            state.objective, state.clarification, answers, answered_by
        )
        learned = self.memory.remember_answers(
            state.clarification, scope=self.scope, answered_by=answered_by
        )
        self._log(
            state,
            Stage.CLARIFY,
            f"{len(answers)} answer(s) recorded",
            remembered=learned,
        )
        return self._after_clarification(state)

    def hold_meeting(
        self, state: RunState, notes: str, answers: Optional[dict[str, str]] = None
    ) -> RunState:
        """Close the meeting: notes become context, answers close the questions."""
        if not state.clarification:
            return state
        state.clarification = self.clarifier.record_meeting(
            state.objective, state.clarification, notes, answers
        )
        # A meeting is the most expensive answer the system can buy. Remembering
        # what was said there is what stops it buying the same one twice.
        learned = self.memory.remember_answers(
            state.clarification, scope=self.scope, answered_by="meeting"
        )
        self._log(state, Stage.CLARIFY, "meeting held", remembered=learned)
        return self._after_clarification(state)

    def run(self, objective: Objective, answers: Optional[dict[str, str]] = None) -> RunState:
        """Convenience: start, and apply a pre-supplied answer sheet if given."""
        state = self.start(objective)
        if answers and state.awaiting_human:
            state = self.answer(state, answers)
        return state

    # ── Stage machine ─────────────────────────────────────────────────────────

    def _clarify(self, state: RunState) -> RunState:
        state.stage = Stage.CLARIFY
        state.clarification_rounds += 1
        state.clarification = self.clarifier.assess(
            state.objective, prior=state.clarification, round_number=state.clarification_rounds
        )
        self._log(
            state,
            Stage.CLARIFY,
            f"{state.clarification.outcome.value} (confidence {state.clarification.confidence})",
            questions=len(state.clarification.questions),
            recalled=[a.statement for a in state.clarification.assumptions if a.source == "memory"],
        )
        return self._after_clarification(state)

    def _after_clarification(self, state: RunState) -> RunState:
        result = state.clarification
        if result is None:
            return state
        if result.outcome is ClarificationOutcome.READY:
            return self._build(state)
        if result.outcome is ClarificationOutcome.MEETING_REQUIRED and result.meeting:
            self._log(
                state,
                Stage.CLARIFY,
                f"meeting requested: {result.meeting.title}",
                meeting_id=result.meeting.id,
            )
        return state  # awaiting a human — the caller decides when to resume

    def _build(self, state: RunState) -> RunState:
        state.stage = Stage.SPEC
        spec = self.pm.draft(state.objective, state.clarification)
        violations = self.constitution.check_spec(spec)
        if self._blocking(violations):
            return self._block(state, Stage.SPEC, violations)
        state.spec = spec
        state.semantics = self.semantics.build(spec)
        self._log(
            state,
            Stage.SPEC,
            f"{len(spec.requirements)} requirement(s), {len(spec.criteria())} criteria",
            spec_hash=spec.content_hash(),
            capabilities=[c.render() for c in state.semantics.capabilities],
            ambiguities=state.semantics.ambiguities,
        )

        state.stage = Stage.PLAN
        memory_report = self.memory.retrieve(
            " ".join([spec.title, spec.summary, *(r.statement for r in spec.requirements)]),
            scope=self.scope,
        )
        plan = self.architect.draft(spec, memory_report)
        violations = self.constitution.check_plan(plan, spec)
        if self._blocking(violations):
            return self._block(state, Stage.PLAN, violations)
        state.plan = plan
        self._log(
            state,
            Stage.PLAN,
            f"{len(plan.components)} component(s), {len(plan.historical_warnings)} warning(s)",
            cases=plan.memory_case_ids,
            lessons=[lesson.id for lesson in memory_report.lessons],
            observability=plan.observability.summary() if plan.observability else "none",
            placements=[p.summary() for p in plan.placements[:5]],
        )

        state.stage = Stage.TASKS
        graph = self.planner.build(plan, spec)
        violations = self.constitution.check_tasks(graph, spec)
        if self._blocking(violations):
            return self._block(state, Stage.TASKS, violations)
        state.tasks = graph
        # Every task lands in a tracked item, so nothing small goes unrecorded
        # and nothing large arrives without the reason it exists.
        state.breakdown = self.breakdown.build(
            state.objective, spec, plan, graph, state.semantics, plan.observability
        )
        self._log(
            state,
            Stage.TASKS,
            f"{len(graph.tasks)} task(s) in the DAG",
            work_items=len(state.breakdown.items),
            tracking_coverage=state.breakdown.coverage([r.id for r in spec.requirements]),
        )

        state.stage = Stage.WORK
        guard = BudgetGuard(state.budget)
        try:
            state.work_results = self.worker.execute(graph, spec, guard=guard)
        except BudgetExceeded as exc:
            state.stage = Stage.BLOCKED
            self._log(state, Stage.WORK, f"stopped: {exc}", budget=state.budget.model_dump())
            return state
        done = sum(1 for r in state.work_results if r.status.value == "done")
        state.assignments = list(getattr(self.worker.backend, "assignments", []))
        self._log(
            state,
            Stage.WORK,
            f"{done}/{len(state.work_results)} task(s) completed",
            agents=sorted({r.agent_id for r in state.work_results if r.agent_id}),
        )

        state.stage = Stage.QA
        state.qa = self.qa.verify(spec, graph, state.work_results)
        self._log(
            state,
            Stage.QA,
            f"{state.qa.verdict.value} — coverage {state.qa.coverage}",
            summary=state.qa.summary_lines(),
            observability_coverage=state.qa.observability_coverage,
        )

        state.stage = Stage.DELIVER
        state.delivery = self.delivery.package(state)
        self._log(
            state,
            Stage.DELIVER,
            "accepted" if state.delivery.accepted else "not accepted",
            coverage=state.delivery.coverage,
            runbook=state.delivery.runbook_path,
            slos=state.delivery.slo_summary,
        )

        state.metrics = (
            self.metrics.build(
                state.breakdown,
                qa=state.qa,
                observability=plan.observability,
                state=state,
            )
            if state.breakdown
            else None
        )
        if state.metrics is not None:
            self._log(
                state,
                Stage.DELIVER,
                f"{len(state.metrics.specs)} metric(s) defined",
                unbound=[m.id for m in state.metrics.specs if m.source == "unbound"],
            )
        self._write_documents(state)

        state.stage = Stage.HARVEST
        case = self.memory.harvest(state, scope=self.scope)
        state.case_id = case.id
        # Harvest writes; consolidation is what turns writes into knowledge —
        # duplicates merge, recurring pitfalls become lessons, stale ones fade.
        report = self.memory.consolidate()
        self._log(
            state,
            Stage.HARVEST,
            f"case {case.id} ({case.outcome})",
            consolidation=report.summary() if report.changed else "no change",
        )

        state.stage = Stage.DONE
        return state

    def _write_documents(self, state: RunState) -> None:
        """Write the project record, when there is a repository to write it into.

        A run with no repo root still builds the document set on demand (the CLI
        and the API render it); it just has nowhere to put files.
        """
        if not (self.config.project_docs.enabled and self.repo_root and state.spec):
            return
        try:
            written = self.docs.write(
                state,
                self.repo_root,
                semantics=state.semantics,
                breakdown=state.breakdown,
                metrics=state.metrics,
            )
        except OSError as exc:
            self._log(state, Stage.DELIVER, f"project docs not written: {exc}")
            return
        state.documents = [str(path) for path in written]
        self._log(
            state,
            Stage.DELIVER,
            f"{len(written)} project document(s) written",
            docs=state.documents[:3],
        )

    # ── Gates & logging ───────────────────────────────────────────────────────

    @staticmethod
    def _blocking(violations: list[Violation]) -> list[Violation]:
        return [v for v in violations if v.severity is Severity.ERROR]

    def _block(self, state: RunState, stage: Stage, violations: list[Violation]) -> RunState:
        errors = self._blocking(violations)
        state.stage = Stage.BLOCKED
        self._log(
            state,
            stage,
            f"blocked by {len(errors)} constitution violation(s)",
            violations=[v.model_dump(mode="json") for v in errors],
        )
        return state

    def _log(self, state: RunState, stage: Stage, message: str, **data: object) -> None:
        state.log(stage, message, **data)
        if self.on_event:
            self.on_event(state.events[-1])


# ── Persistence ───────────────────────────────────────────────────────────────


def save_state(state: RunState, directory: str | Path) -> Path:
    path = Path(directory) / f"{state.id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.model_dump(mode="json"), indent=2) + "\n")
    return path


def load_state(path: str | Path) -> RunState:
    return RunState.model_validate(json.loads(Path(path).read_text()))


def _scope_of(repo_root: Optional[str]) -> str:
    """A repo's directory name is its memory scope; no repo means global."""
    from future_agents.sdd.memory import GLOBAL_SCOPE

    if not repo_root:
        return GLOBAL_SCOPE
    return Path(repo_root).resolve().name or GLOBAL_SCOPE
