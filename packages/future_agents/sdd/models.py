"""Spec-Driven Delivery — the intermediate representation (IR) artifacts.

Each artifact bounds the next: objective → spec → plan → tasks → work → QA →
delivery → case. Every artifact is content-hashed so a downstream stage can
detect that its input changed underneath it (staleness) instead of silently
building on a stale premise.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _nid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class Hashable(BaseModel):
    """Artifact base that can fingerprint its own semantic content."""

    def content_hash(self) -> str:
        payload = self.model_dump(mode="json", exclude=self._hash_exclude())
        blob = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def _hash_exclude(self) -> set[str]:
        # Timestamps and back-references are provenance, not content.
        return {"created_at", "updated_at", "id", "confidence"}


# ── Intake ────────────────────────────────────────────────────────────────────


class IntakeSource(str, Enum):
    MEETING = "meeting_transcript"
    TICKET = "ticket"
    CHAT = "chat"
    EMAIL = "email"
    INCIDENT = "incident"
    SCHEDULED = "scheduled"


class Objective(Hashable):
    """Raw human intent entering the pipeline — the only un-derived artifact."""

    id: str = Field(default_factory=lambda: _nid("obj"))
    statement: str
    context: str = ""
    source: IntakeSource = IntakeSource.CHAT
    submitted_by: str = "unknown"
    raw_inputs: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    deadline: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


# ── Clarification ─────────────────────────────────────────────────────────────


class QuestionTopic(str, Enum):
    SCOPE = "scope"
    ACCEPTANCE = "acceptance"
    DATA = "data"
    NON_FUNCTIONAL = "non_functional"
    INTEGRATION = "integration"
    OWNERSHIP = "ownership"
    TIMELINE = "timeline"
    RISK = "risk"


class Question(BaseModel):
    """One resolvable unknown. Blocking questions fail the gate closed."""

    id: str = Field(default_factory=lambda: _nid("q"))
    text: str
    topic: QuestionTopic = QuestionTopic.SCOPE
    blocking: bool = False
    why_it_matters: str = ""
    options: list[str] = Field(default_factory=list)
    evidence: str = ""
    answer: Optional[str] = None
    answered_by: Optional[str] = None
    answered_at: Optional[datetime] = None

    @property
    def answered(self) -> bool:
        return bool(self.answer and self.answer.strip())


class Assumption(BaseModel):
    """An unconfirmed premise the pipeline proceeded on. Always surfaced."""

    id: str = Field(default_factory=lambda: _nid("asm"))
    statement: str
    basis: str = ""
    risk: str = "medium"  # low | medium | high
    confirmed: bool = False
    source_question_id: Optional[str] = None


class MeetingStatus(str, Enum):
    REQUESTED = "requested"
    SCHEDULED = "scheduled"
    HELD = "held"
    CANCELLED = "cancelled"


class MeetingRequest(BaseModel):
    """Escalation to a live human conversation — the last rung of the ladder."""

    id: str = Field(default_factory=lambda: _nid("mtg"))
    objective_id: str
    title: str
    reason: str
    agenda: list[str] = Field(default_factory=list)
    question_ids: list[str] = Field(default_factory=list)
    required_attendees: list[str] = Field(default_factory=list)
    duration_minutes: int = 30
    status: MeetingStatus = MeetingStatus.REQUESTED
    scheduled_for: Optional[str] = None
    notes: str = ""
    created_at: datetime = Field(default_factory=_now)


class ClarificationOutcome(str, Enum):
    READY = "ready"  # confident enough to spec
    ASYNC_QUESTIONS = "async_questions"  # answerable without a meeting
    MEETING_REQUIRED = "meeting_required"  # too tangled for async
    BLOCKED = "blocked"  # human said stop / SLA expired


class ClarificationResult(BaseModel):
    id: str = Field(default_factory=lambda: _nid("clr"))
    objective_id: str
    outcome: ClarificationOutcome
    confidence: float = 0.0
    questions: list[Question] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    meeting: Optional[MeetingRequest] = None
    rationale: str = ""
    round_number: int = 1

    @property
    def open_blocking(self) -> list[Question]:
        return [q for q in self.questions if q.blocking and not q.answered]


# ── Spec ──────────────────────────────────────────────────────────────────────


class Priority(str, Enum):
    MUST = "must"
    SHOULD = "should"
    COULD = "could"


class AcceptanceCriterion(BaseModel):
    """Given/When/Then. The unit QA verifies and coverage is measured against."""

    id: str
    given: str
    when: str
    then: str

    def render(self) -> str:
        return f"Given {self.given}, when {self.when}, then {self.then}."


class Requirement(BaseModel):
    id: str  # REQ-001 — stable, referenced by tasks, tests and QA
    statement: str
    rationale: str = ""
    priority: Priority = Priority.MUST
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    source: str = ""


class Spec(Hashable):
    """Functional intent — what and why. Deliberately free of tech-stack detail."""

    id: str = Field(default_factory=lambda: _nid("spec"))
    objective_id: str
    title: str
    summary: str = ""
    requirements: list[Requirement] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    open_questions: list[Question] = Field(default_factory=list)
    glossary: dict[str, str] = Field(default_factory=dict)
    success_metrics: list[str] = Field(default_factory=list)
    context_notes: list[str] = Field(default_factory=list)  # what the repo already does
    confidence: float = 0.0
    created_at: datetime = Field(default_factory=_now)

    def criteria(self) -> list[AcceptanceCriterion]:
        return [ac for r in self.requirements for ac in r.acceptance_criteria]

    def requirement(self, req_id: str) -> Optional[Requirement]:
        return next((r for r in self.requirements if r.id == req_id), None)


# ── Repository knowledge ──────────────────────────────────────────────────────


class RepoMatch(BaseModel):
    """Something that already exists in the repository, and where."""

    path: str
    symbol: str = ""
    kind: str = ""
    score: float = 0.0
    excerpt: str = ""
    reason: str = ""

    def render(self) -> str:
        target = f"{self.path}::{self.symbol}" if self.symbol else self.path
        return f"{target} ({self.reason})"


class PlacementOption(BaseModel):
    """One way to satisfy a requirement, with the price of taking it."""

    path: str
    approach: str  # extend | new-module | new-package | new-app | config | docs
    rationale: str = ""
    tradeoff: str = ""
    score: float = 0.0


class ForbiddenZone(BaseModel):
    """Somewhere the change must not go, and the rule that says so."""

    path: str
    reason: str
    source: str = ""  # the file the rule came from


class PlacementDecision(BaseModel):
    """Where a requirement's code, tests and docs go — and where they may not."""

    requirement_id: str = ""
    target_path: str = ""
    test_path: str = ""
    docs_path: str = ""
    approach: str = "new-module"
    rationale: str = ""
    confidence: float = 0.0
    alternatives: list[PlacementOption] = Field(default_factory=list)
    forbidden: list[ForbiddenZone] = Field(default_factory=list)
    reuse: list[RepoMatch] = Field(default_factory=list)
    conventions: list[str] = Field(default_factory=list)  # rules that decided it

    def summary(self) -> str:
        where = self.target_path or "unknown"
        alt = (
            f"; alternatives: {', '.join(a.path for a in self.alternatives)}"
            if self.alternatives
            else ""
        )
        return f"{self.requirement_id or 'change'} → {where} ({self.approach}){alt}"


class RepoContext(BaseModel):
    """What the repository already knows that bears on this piece of work."""

    query: str
    matches: list[RepoMatch] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def render(self, limit: int = 5) -> list[str]:
        return [m.render() for m in self.matches[:limit]]


# ── Plan ──────────────────────────────────────────────────────────────────────


class Component(BaseModel):
    name: str
    responsibility: str
    requirement_ids: list[str] = Field(default_factory=list)
    interfaces: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    target_path: str = ""  # where this component's code goes, from repo knowledge


class Risk(BaseModel):
    id: str = Field(default_factory=lambda: _nid("risk"))
    description: str
    severity: str = "medium"  # low | medium | high
    mitigation: str = ""
    source: str = ""  # "constitution" | "memory:<case-id>" | "heuristic"


class Plan(Hashable):
    """Technical blueprint — how. Bound by the spec hash it was drawn from."""

    id: str = Field(default_factory=lambda: _nid("plan"))
    spec_id: str
    spec_hash: str
    architecture: str = ""
    runtime_stack: str = ""
    components: list[Component] = Field(default_factory=list)
    data_contracts: list[str] = Field(default_factory=list)
    test_strategy: str = ""
    risks: list[Risk] = Field(default_factory=list)
    historical_warnings: list[str] = Field(default_factory=list)
    memory_case_ids: list[str] = Field(default_factory=list)
    placements: list[PlacementDecision] = Field(default_factory=list)
    reuse_candidates: list[RepoMatch] = Field(default_factory=list)
    confidence: float = 0.0
    created_at: datetime = Field(default_factory=_now)

    def placement_for(self, requirement_id: str) -> Optional[PlacementDecision]:
        return next((p for p in self.placements if p.requirement_id == requirement_id), None)


# ── Tasks ─────────────────────────────────────────────────────────────────────


class TaskKind(str, Enum):
    TEST = "test"
    CODE = "code"
    INFRA = "infra"
    DOC = "doc"
    REVIEW = "review"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class TaskUnit(BaseModel):
    """Atomic work unit. Test units precede the code units that satisfy them."""

    id: str  # T-001
    title: str
    description: str = ""
    kind: TaskKind = TaskKind.CODE
    requirement_ids: list[str] = Field(default_factory=list)
    criterion_ids: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    component: str = ""
    engine: str = ""
    status: TaskStatus = TaskStatus.PENDING
    artifacts: list[str] = Field(default_factory=list)


class CycleError(ValueError):
    """The task graph is not a DAG."""


class TaskGraph(Hashable):
    id: str = Field(default_factory=lambda: _nid("tasks"))
    plan_id: str
    plan_hash: str
    tasks: list[TaskUnit] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)

    def by_id(self, task_id: str) -> Optional[TaskUnit]:
        return next((t for t in self.tasks if t.id == task_id), None)

    def topological_order(self) -> list[TaskUnit]:
        """Kahn's algorithm. Raises CycleError rather than dropping tasks."""
        indegree = {t.id: 0 for t in self.tasks}
        dependents: dict[str, list[str]] = {t.id: [] for t in self.tasks}
        for task in self.tasks:
            for dep in task.depends_on:
                if dep not in indegree:
                    raise CycleError(f"{task.id} depends on unknown task {dep}")
                indegree[task.id] += 1
                dependents[dep].append(task.id)

        # Ordered queue keeps the output stable across runs.
        queue = sorted([tid for tid, deg in indegree.items() if deg == 0])
        ordered: list[TaskUnit] = []
        while queue:
            tid = queue.pop(0)
            task = self.by_id(tid)
            if task is not None:
                ordered.append(task)
            for child in dependents[tid]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)
            queue.sort()

        if len(ordered) != len(self.tasks):
            unresolved = sorted(set(indegree) - {t.id for t in ordered})
            raise CycleError(f"cycle in task graph: {', '.join(unresolved)}")
        return ordered

    def ready(self) -> list[TaskUnit]:
        done = {t.id for t in self.tasks if t.status is TaskStatus.DONE}
        return [
            t
            for t in self.tasks
            if t.status is TaskStatus.PENDING and set(t.depends_on).issubset(done)
        ]


# ── Work ──────────────────────────────────────────────────────────────────────


class WorkResult(BaseModel):
    task_id: str
    status: TaskStatus
    summary: str = ""
    engine: str = ""
    changed_files: list[str] = Field(default_factory=list)
    tests_added: list[str] = Field(default_factory=list)
    criterion_ids: list[str] = Field(default_factory=list)
    log_excerpt: str = ""
    error: str = ""
    duration_ms: float = 0.0


# ── QA ────────────────────────────────────────────────────────────────────────


class QAVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocked"


class QAFinding(BaseModel):
    id: str = Field(default_factory=lambda: _nid("find"))
    criterion_id: str = ""
    requirement_id: str = ""
    severity: str = "major"  # blocker | major | minor
    summary: str = ""
    evidence: str = ""
    in_scope: bool = True


class BehaviourCheck(BaseModel):
    """One acceptance criterion rendered as BDD + an AAA test skeleton."""

    criterion_id: str
    requirement_id: str
    given: str
    when: str
    then: str
    arrange: str = ""
    act: str = ""
    assert_: str = Field(default="", alias="assert")
    covered_by: list[str] = Field(default_factory=list)
    verified: bool = False

    model_config = {"populate_by_name": True}


class QAReport(BaseModel):
    id: str = Field(default_factory=lambda: _nid("qa"))
    spec_id: str
    verdict: QAVerdict = QAVerdict.BLOCKED
    checks: list[BehaviourCheck] = Field(default_factory=list)
    findings: list[QAFinding] = Field(default_factory=list)
    out_of_scope_ignored: list[str] = Field(default_factory=list)
    coverage: float = 0.0
    environment: str = "ephemeral"
    environment_cleaned: bool = False
    created_at: datetime = Field(default_factory=_now)

    def summary_lines(self) -> list[str]:
        """The summary_only wire format — verbose logs stay out of the channel."""
        verified = [c for c in self.checks if c.verified]
        headline = f"{len(verified)}/{len(self.checks)} behaviours verified"
        lines = [f"QA {self.verdict.value.upper()} — {headline}"]
        blockers = [f for f in self.findings if f.severity == "blocker"]
        if blockers:
            lines.append(f"Blocker: {blockers[0].summary}")
            return lines
        lines.extend(f"✓ {c.then}" for c in verified[:5])
        lines.extend(f"✗ {f.summary}" for f in self.findings[:3])
        return lines


# ── Delivery & memory ─────────────────────────────────────────────────────────


class Delivery(BaseModel):
    id: str = Field(default_factory=lambda: _nid("del"))
    spec_id: str
    accepted: bool = False
    coverage: float = 0.0
    artifacts: list[str] = Field(default_factory=list)
    unconfirmed_assumptions: list[Assumption] = Field(default_factory=list)
    residual_questions: list[Question] = Field(default_factory=list)
    notes: str = ""
    created_at: datetime = Field(default_factory=_now)


class MemoryCase(BaseModel):
    """A compressed lesson from one run. Negative cases carry the most weight."""

    id: str = Field(default_factory=lambda: _nid("case"))
    title: str
    objective: str
    problem: str = ""
    solution: str = ""
    pitfalls: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    outcome: str = "success"  # success | partial | failure
    requirement_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)

    def to_markdown(self) -> str:
        parts = [
            f"# {self.title}",
            "",
            f"- **Outcome:** {self.outcome}",
            f"- **Tags:** {', '.join(self.tags) if self.tags else '—'}",
            f"- **Recorded:** {self.created_at.date().isoformat()}",
            "",
            "## Objective",
            self.objective,
            "",
            "## Problem",
            self.problem or "—",
            "",
            "## Solution",
            self.solution or "—",
            "",
            "## Pitfalls & hard lessons",
        ]
        parts.extend(f"- {p}" for p in self.pitfalls or ["None recorded"])
        return "\n".join(parts) + "\n"


# ── Pipeline state ────────────────────────────────────────────────────────────


class Stage(str, Enum):
    INTAKE = "intake"
    CLARIFY = "clarify"
    SPEC = "spec"
    PLAN = "plan"
    TASKS = "tasks"
    WORK = "work"
    QA = "qa"
    DELIVER = "deliver"
    HARVEST = "harvest"
    DONE = "done"
    BLOCKED = "blocked"


class PipelineEvent(BaseModel):
    stage: Stage
    message: str
    at: datetime = Field(default_factory=_now)
    data: dict[str, Any] = Field(default_factory=dict)


class RunState(BaseModel):
    """The whole run, resumable from JSON — the pipeline holds no other state."""

    id: str = Field(default_factory=lambda: _nid("run"))
    objective: Objective
    stage: Stage = Stage.INTAKE
    clarification: Optional[ClarificationResult] = None
    spec: Optional[Spec] = None
    plan: Optional[Plan] = None
    tasks: Optional[TaskGraph] = None
    work_results: list[WorkResult] = Field(default_factory=list)
    qa: Optional[QAReport] = None
    delivery: Optional[Delivery] = None
    case_id: Optional[str] = None
    events: list[PipelineEvent] = Field(default_factory=list)
    clarification_rounds: int = 0
    updated_at: datetime = Field(default_factory=_now)

    def log(self, stage: Stage, message: str, **data: Any) -> None:
        self.events.append(PipelineEvent(stage=stage, message=message, data=data))
        self.updated_at = _now()

    @property
    def awaiting_human(self) -> bool:
        return self.stage is Stage.CLARIFY and self.clarification is not None

    def pending_questions(self) -> list[Question]:
        if not self.clarification:
            return []
        return [q for q in self.clarification.questions if not q.answered]
