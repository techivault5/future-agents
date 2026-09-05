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
from future_agents.sdd.memory_hub import MemoryHub
from future_agents.sdd.models import (
    ClarificationOutcome,
    Objective,
    PipelineEvent,
    RunState,
    Stage,
)
from future_agents.sdd.router import EngineRouter
from future_agents.sdd.stages import (
    ArchitectStage,
    DeliveryStage,
    PMStage,
    QAStage,
    TaskPlanner,
    WorkerBackend,
    WorkerStage,
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
    ) -> None:
        self.config = config or SpecKitConfig()
        self.router = router or EngineRouter(self.config)
        self.memory = memory or MemoryHub(self.config.memory_hub)
        self.constitution = self.config.constitution()
        self.on_event = on_event

        self.clarifier = IntentClarifier(self.config)
        self.pm = PMStage(self.config, self.router)
        self.architect = ArchitectStage(self.config, self.router)
        self.planner = TaskPlanner(self.config, self.router)
        self.worker = WorkerStage(backend)
        self.qa = QAStage(self.config)
        self.delivery = DeliveryStage()

    # ── Entry points ──────────────────────────────────────────────────────────

    def start(self, objective: Objective) -> RunState:
        state = RunState(objective=objective)
        self._log(state, Stage.INTAKE, f"objective accepted from {objective.source.value}")
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
        self._log(state, Stage.CLARIFY, f"{len(answers)} answer(s) recorded")
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
        self._log(state, Stage.CLARIFY, "meeting held")
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
        self._log(
            state,
            Stage.SPEC,
            f"{len(spec.requirements)} requirement(s), {len(spec.criteria())} criteria",
            spec_hash=spec.content_hash(),
        )

        state.stage = Stage.PLAN
        memory_report = self.memory.retrieve(f"{spec.title} {spec.summary}")
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
        )

        state.stage = Stage.TASKS
        graph = self.planner.build(plan, spec)
        violations = self.constitution.check_tasks(graph, spec)
        if self._blocking(violations):
            return self._block(state, Stage.TASKS, violations)
        state.tasks = graph
        self._log(state, Stage.TASKS, f"{len(graph.tasks)} task(s) in the DAG")

        state.stage = Stage.WORK
        state.work_results = self.worker.execute(graph, spec)
        done = sum(1 for r in state.work_results if r.status.value == "done")
        self._log(state, Stage.WORK, f"{done}/{len(state.work_results)} task(s) completed")

        state.stage = Stage.QA
        state.qa = self.qa.verify(spec, graph, state.work_results)
        self._log(
            state,
            Stage.QA,
            f"{state.qa.verdict.value} — coverage {state.qa.coverage}",
            summary=state.qa.summary_lines(),
        )

        state.stage = Stage.DELIVER
        state.delivery = self.delivery.package(state)
        self._log(
            state,
            Stage.DELIVER,
            "accepted" if state.delivery.accepted else "not accepted",
            coverage=state.delivery.coverage,
        )

        state.stage = Stage.HARVEST
        case = self.memory.harvest(state)
        state.case_id = case.id
        self._log(state, Stage.HARVEST, f"case {case.id} ({case.outcome})")

        state.stage = Stage.DONE
        return state

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
