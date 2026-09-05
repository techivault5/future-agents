"""Pipeline stages — PM, Architect, Planner, Worker, QA, Delivery.

Every stage is deterministic on its own: it derives its artifact from the
upstream one with explicit rules, and an engine (when configured) only enriches
free-text fields. That is what makes runs reproducible and testable — the model
is an accelerator, never the source of truth.
"""

from __future__ import annotations

import re
import time
from typing import Callable, Optional

from future_agents.sdd.config import SpecKitConfig
from future_agents.sdd.languages import Toolchain
from future_agents.sdd.memory_hub import RetrievalReport
from future_agents.sdd.models import (
    AcceptanceCriterion,
    BehaviourCheck,
    ClarificationResult,
    Component,
    Delivery,
    Objective,
    Plan,
    Priority,
    QAFinding,
    QAReport,
    QAVerdict,
    Requirement,
    Risk,
    RunState,
    Spec,
    TaskGraph,
    TaskKind,
    TaskStatus,
    TaskUnit,
    WorkResult,
)
from future_agents.sdd.personas import DEFAULT_PERSONA, Persona
from future_agents.sdd.router import EngineCall, EngineRouter
from future_agents.sdd.scaffold import RepoScaffolder

_ACTION = re.compile(
    r"\b(must|shall|should|needs? (?:to|a|the)?|we (?:need|want)|require[sd]?|"
    r"action item|todo|will)\b",
    re.IGNORECASE,
)
# A transcript line that opens with an imperative verb is an action item even
# without a modal ("flag accounts with usage down 20%").
_IMPERATIVE = re.compile(
    r"^(add|build|create|send|expose|ensure|support|generate|remove|update|migrate|"
    r"integrate|alert|flag|show|display|store|track|schedule|deliver|replace|enable|"
    r"restrict|log|export|import|sync|notify|document)\b",
    re.IGNORECASE,
)
_MUST = re.compile(r"\b(must|shall|required|blocker|critical)\b", re.IGNORECASE)
_COULD = re.compile(r"\b(could|nice to have|maybe|optional|stretch)\b", re.IGNORECASE)
_OUT_OF_SCOPE = re.compile(
    r"\b(out of scope|not in scope|won'?t (?:do|cover)|exclude[sd]?|later phase)\b", re.IGNORECASE
)
_SO_THAT = re.compile(r"\bso that\b(.+)$", re.IGNORECASE)
_METRIC = re.compile(
    r"[^.\n]*?\d+\s*(?:%|percent|ms|sec|min|hours?|days?|rps|qps|users?|records?)[^.\n]*",
    re.IGNORECASE,
)
_SPEAKER = re.compile(r"^\s*(?:[-*]\s*)?(?:\[[\d:]+\]\s*)?([A-Z][\w .'-]{1,30}):\s*(.+)$")

# requirement keyword → component name
_DOMAINS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("auth", ("login", "auth", "sso", "permission", "role", "token", "session")),
    ("api", ("api", "endpoint", "rest", "graphql", "webhook", "request")),
    ("data", ("data", "database", "schema", "etl", "pipeline", "warehouse", "record")),
    ("ui", ("ui", "screen", "page", "dashboard", "button", "form", "view")),
    ("notification", ("notify", "notification", "email", "alert", "slack", "message")),
    ("reporting", ("report", "export", "metric", "analytics", "chart")),
    ("infra", ("deploy", "pipeline", "ci", "cd", "infrastructure", "terraform", "container")),
)


class PMStage:
    """Meeting transcript / ticket / chat → a functional spec with traceable IDs."""

    role = "pm_agent"

    def __init__(
        self, config: Optional[SpecKitConfig] = None, router: Optional[EngineRouter] = None
    ) -> None:
        self.config = config or SpecKitConfig()
        self.router = router or EngineRouter(self.config)

    def draft(
        self, objective: Objective, clarification: Optional[ClarificationResult] = None
    ) -> Spec:
        candidates = _candidate_lines(objective)
        lines = [text for text, _ in candidates]
        # In a transcript every attributed line is a candidate action item; in a
        # ticket or chat only modal/imperative phrasing is.
        statements = [
            text
            for index, (text, attributed) in enumerate(candidates)
            if index == 0
            or _ACTION.search(text)
            or _IMPERATIVE.match(text)
            or (attributed and not text.rstrip().endswith("?"))
        ]
        if not statements:
            statements = [objective.statement]

        requirements: list[Requirement] = []
        out_of_scope: list[str] = list(self.config.qa.out_of_scope)
        for line in lines:
            if _OUT_OF_SCOPE.search(line):
                out_of_scope.append(_clean(line))

        for idx, statement in enumerate(_dedupe_lines(statements), start=1):
            if _OUT_OF_SCOPE.search(statement):
                continue
            req_id = f"REQ-{idx:03d}"
            requirements.append(
                Requirement(
                    id=req_id,
                    statement=_clean(statement),
                    rationale=_rationale(statement),
                    priority=_priority(statement),
                    acceptance_criteria=[_criterion(req_id, statement, objective)],
                    source=objective.source.value,
                )
            )

        answers = _answer_context(clarification)
        summary = self._summary(objective, requirements, answers)
        return Spec(
            objective_id=objective.id,
            title=_title(objective.statement),
            summary=summary,
            requirements=requirements,
            out_of_scope=_dedupe_lines(out_of_scope),
            assumptions=list(clarification.assumptions) if clarification else [],
            open_questions=[
                q for q in (clarification.questions if clarification else []) if not q.answered
            ],
            success_metrics=_metrics(objective, answers),
            confidence=clarification.confidence if clarification else 0.5,
        )

    def _summary(self, objective: Objective, reqs: list[Requirement], answers: str) -> str:
        generated = (
            f"{len(reqs)} requirement(s) derived from a {objective.source.value} "
            f"submitted by {objective.submitted_by}."
        )
        enriched = self.router.run(
            EngineCall(
                role=self.role,
                system="Summarise business intent. No technology choices.",
                prompt=f"{objective.statement}\n{objective.context}\n{answers}",
            ),
            intent=objective.statement,
        )
        return enriched.strip() or generated


class ArchitectStage:
    """Spec → plan, with the memory hub's past pitfalls injected as constraints."""

    role = "architect_agent"

    def __init__(
        self,
        config: Optional[SpecKitConfig] = None,
        router: Optional[EngineRouter] = None,
        persona: Optional[Persona] = None,
        toolchain: Optional[Toolchain] = None,
    ) -> None:
        self.config = config or SpecKitConfig()
        self.router = router or EngineRouter(self.config)
        self.persona = persona or DEFAULT_PERSONA
        self.toolchain = toolchain

    def draft(self, spec: Spec, memory: Optional[RetrievalReport] = None) -> Plan:
        components = _components(spec)
        constitution = self.config.constitution()
        risks: list[Risk] = []

        spec_blob = " ".join(r.statement for r in spec.requirements).lower()
        for banned in constitution.banned_practices:
            if constitution._mentions(spec_blob, banned):
                risks.append(
                    Risk(
                        description=f"spec brushes a banned practice: {banned}",
                        severity="high",
                        mitigation="design around it or get an explicit exception",
                        source="constitution",
                    )
                )
        for trigger in constitution.requires_escalation(spec_blob):
            risks.append(
                Risk(
                    description=f"touches {trigger} — human sign-off required before ship",
                    severity="high",
                    mitigation="named approver on the delivery record",
                    source="constitution",
                )
            )
        warnings = memory.warnings() if memory else []
        for warning in warnings:
            risks.append(
                Risk(
                    description=warning,
                    severity="medium",
                    mitigation="address explicitly in the task graph",
                    source="memory",
                )
            )

        # Experience enters the plan as risks, not as advice in a prompt.
        risks.extend(self.persona.risks_for(spec))

        high = sum(1 for r in risks if r.severity == "high")
        architecture = self._architecture(spec, components)
        return Plan(
            spec_id=spec.id,
            spec_hash=spec.content_hash(),
            architecture=architecture,
            runtime_stack=self.toolchain.display_name
            if self.toolchain
            else self.config.governance.runtime_stack,
            components=components,
            data_contracts=[
                f"{c.name}: inputs/outputs defined by {', '.join(c.requirement_ids)}"
                for c in components
            ],
            test_strategy=self._test_strategy(spec),
            risks=risks,
            historical_warnings=warnings,
            memory_case_ids=[m.case.id for m in memory.matches] if memory else [],
            confidence=round(max(0.0, spec.confidence - 0.05 * high), 3),
        )

    def _architecture(self, spec: Spec, components: list[Component]) -> str:
        generated = (
            f"{len(components)} component(s): "
            + ", ".join(f"{c.name} ({len(c.requirement_ids)} req)" for c in components)
            + (
                f". Runtime: {self.config.governance.runtime_stack}"
                if self.config.governance.runtime_stack
                else ""
            )
        )
        enriched = self.router.run(
            EngineCall(
                role=self.role,
                system="Draft a technical approach bounded by the given requirements.",
                prompt="\n".join(f"{r.id}: {r.statement}" for r in spec.requirements),
            ),
            intent=spec.title,
        )
        return enriched.strip() or generated

    def _test_strategy(self, spec: Spec) -> str:
        qa = self.config.qa
        bits = [f"{len(spec.criteria())} acceptance criteria verified as Given/When/Then"]
        if self.toolchain and self.toolchain.test:
            bits.append(f"run with `{self.toolchain.test}`")
        if qa.enforce_aaa:
            bits.append("tests structured Arrange-Act-Assert")
        if qa.ephemeral_environment:
            bits.append("run in an ephemeral environment torn down after the report")
        bits.append(f"required coverage {int(qa.required_coverage * 100)}% of MUST criteria")
        return "; ".join(bits)


class TaskPlanner:
    """Plan → an execution DAG of atomic, test-first units."""

    role = "planner_agent"

    def __init__(
        self,
        config: Optional[SpecKitConfig] = None,
        router: Optional[EngineRouter] = None,
        persona: Optional[Persona] = None,
        toolchain: Optional[Toolchain] = None,
        repo_root: Optional[str] = None,
    ) -> None:
        self.config = config or SpecKitConfig()
        self.router = router or EngineRouter(self.config)
        self.persona = persona or DEFAULT_PERSONA
        self.toolchain = toolchain
        self.repo_root = repo_root

    def build(self, plan: Plan, spec: Spec) -> TaskGraph:
        tasks: list[TaskUnit] = []
        counter = 0

        def next_id() -> str:
            nonlocal counter
            counter += 1
            return f"T-{counter:03d}"

        code_ids: list[str] = []
        for component in plan.components:
            scaffold_id = next_id()
            tasks.append(
                TaskUnit(
                    id=scaffold_id,
                    title=f"Scaffold {component.name}",
                    description=component.responsibility,
                    kind=TaskKind.CODE,
                    requirement_ids=list(component.requirement_ids),
                    component=component.name,
                    engine=self.router.decide("worker_agent", component.name).engine,
                )
            )
            code_ids.append(scaffold_id)

            for req_id in component.requirement_ids:
                requirement = spec.requirement(req_id)
                if requirement is None:
                    continue
                criterion_ids = [ac.id for ac in requirement.acceptance_criteria]
                test_id = next_id()
                tasks.append(
                    TaskUnit(
                        id=test_id,
                        title=f"Test {req_id}: {_short(requirement.statement)}",
                        description="\n".join(
                            [ac.render() for ac in requirement.acceptance_criteria]
                            + ([f"Run: {self.toolchain.test}"] if self.toolchain else [])
                        ),
                        kind=TaskKind.TEST,
                        requirement_ids=[req_id],
                        criterion_ids=criterion_ids,
                        depends_on=[scaffold_id],
                        component=component.name,
                        engine=self.router.decide("qa_agent", requirement.statement).engine,
                    )
                )
                impl_id = next_id()
                tasks.append(
                    TaskUnit(
                        id=impl_id,
                        title=f"Implement {req_id}: {_short(requirement.statement)}",
                        description=requirement.statement,
                        kind=TaskKind.CODE,
                        requirement_ids=[req_id],
                        criterion_ids=criterion_ids,
                        depends_on=[test_id],  # test first — the unit is red before it is green
                        component=component.name,
                        engine=self.router.decide("worker_agent", requirement.statement).engine,
                    )
                )
                code_ids.append(impl_id)

        missing = RepoScaffolder(self.persona).validate(self.repo_root) if self.repo_root else []
        if missing:
            structure_id = next_id()
            tasks.append(
                TaskUnit(
                    id=structure_id,
                    title="Create the missing repository structure",
                    description="Missing required entries: " + ", ".join(missing),
                    kind=TaskKind.INFRA,
                    requirement_ids=[r.id for r in spec.requirements],
                    engine=self.router.decide("worker_agent", "repository structure").engine,
                )
            )
            code_ids.append(structure_id)

        review_id = next_id()
        tasks.append(
            TaskUnit(
                id=review_id,
                title="Guardrails and constitution review",
                description="Run the guardrails engine and re-check the constitution gates.",
                kind=TaskKind.REVIEW,
                requirement_ids=[r.id for r in spec.requirements],
                depends_on=sorted(code_ids),
                engine=self.router.decide("reviewer_agent", "review").engine,
            )
        )
        gate_tasks = self.persona.gate_tasks(spec, depends_on=[review_id], start_index=counter)
        for gate in gate_tasks:
            gate.engine = self.router.decide("reviewer_agent", gate.title).engine
            counter += 1
        tasks.extend(gate_tasks)

        tasks.append(
            TaskUnit(
                id=next_id(),
                title="Document the delivered behaviour",
                description="Update docs, the runbook and the delivery record.",
                kind=TaskKind.DOC,
                requirement_ids=[r.id for r in spec.requirements],
                depends_on=[review_id] + [g.id for g in gate_tasks],
                engine=self.router.decide("doc_agent", "documentation").engine,
            )
        )

        graph = TaskGraph(plan_id=plan.id, plan_hash=plan.content_hash(), tasks=tasks)
        graph.topological_order()  # raises CycleError if the graph is malformed
        return graph


WorkerBackend = Callable[[TaskUnit, Spec], WorkResult]


def dry_run_backend(task: TaskUnit, spec: Spec) -> WorkResult:
    """Default backend: records what *would* happen. Real backends shell out."""
    return WorkResult(
        task_id=task.id,
        status=TaskStatus.DONE,
        summary=f"[dry-run] {task.title}",
        engine=task.engine,
        criterion_ids=list(task.criterion_ids) if task.kind is TaskKind.TEST else [],
        tests_added=[f"test_{task.id.lower().replace('-', '_')}"]
        if task.kind is TaskKind.TEST
        else [],
    )


class WorkerStage:
    """Executes the DAG in dependency order; a failure blocks only its dependents."""

    role = "worker_agent"

    def __init__(self, backend: Optional[WorkerBackend] = None) -> None:
        self.backend = backend or dry_run_backend

    def execute(self, graph: TaskGraph, spec: Spec) -> list[WorkResult]:
        results: list[WorkResult] = []
        failed: set[str] = set()
        for task in graph.topological_order():
            if failed.intersection(task.depends_on):
                task.status = TaskStatus.BLOCKED
                results.append(
                    WorkResult(
                        task_id=task.id,
                        status=TaskStatus.BLOCKED,
                        summary="upstream task failed",
                    )
                )
                failed.add(task.id)
                continue

            task.status = TaskStatus.RUNNING
            started = time.perf_counter()
            try:
                result = self.backend(task, spec)
            except Exception as exc:  # a backend crash is a task failure, not a run crash
                result = WorkResult(task_id=task.id, status=TaskStatus.FAILED, error=str(exc)[:500])
            result.duration_ms = round((time.perf_counter() - started) * 1000, 3)
            task.status = result.status
            if result.status in (TaskStatus.FAILED, TaskStatus.BLOCKED):
                failed.add(task.id)
            results.append(result)
        return results


class QAStage:
    """Active QA: BDD/AAA scaffolding, scope fences, summary-only reporting."""

    role = "qa_agent"

    def __init__(self, config: Optional[SpecKitConfig] = None) -> None:
        self.config = config or SpecKitConfig()

    def verify(self, spec: Spec, graph: TaskGraph, results: list[WorkResult]) -> QAReport:
        qa_cfg = self.config.qa
        by_task = {r.task_id: r for r in results}
        report = QAReport(
            spec_id=spec.id, environment="ephemeral" if qa_cfg.ephemeral_environment else "shared"
        )

        fenced: list[str] = []
        for requirement in spec.requirements:
            for criterion in requirement.acceptance_criteria:
                if self._out_of_scope(requirement.statement, criterion):
                    fenced.append(criterion.id)
                    continue
                covered_by = [
                    t.id
                    for t in graph.tasks
                    if criterion.id in t.criterion_ids
                    and t.kind is TaskKind.TEST
                    and by_task.get(t.id)
                    and by_task[t.id].status is TaskStatus.DONE
                ]
                impl_ok = all(
                    by_task[t.id].status is TaskStatus.DONE
                    for t in graph.tasks
                    if criterion.id in t.criterion_ids
                    and t.kind is TaskKind.CODE
                    and t.id in by_task
                )
                check = BehaviourCheck(
                    criterion_id=criterion.id,
                    requirement_id=requirement.id,
                    given=criterion.given,
                    when=criterion.when,
                    then=criterion.then,
                    arrange=f"Arrange: {criterion.given}",
                    act=f"Act: {criterion.when}",
                    covered_by=covered_by,
                    verified=bool(covered_by) and impl_ok,
                )
                check.assert_ = f"Assert: {criterion.then}"
                report.checks.append(check)

                if not check.verified:
                    report.findings.append(
                        QAFinding(
                            criterion_id=criterion.id,
                            requirement_id=requirement.id,
                            severity="blocker"
                            if requirement.priority is Priority.MUST
                            else "major",
                            summary=(
                                f"{criterion.id} not verified"
                                + ("" if covered_by else " — no passing test task")
                            ),
                            evidence=", ".join(covered_by) or "none",
                        )
                    )

        report.out_of_scope_ignored = fenced
        must_checks = [
            c
            for c in report.checks
            if (spec.requirement(c.requirement_id) or Requirement(id="x", statement="")).priority
            is Priority.MUST
        ]
        verified_must = [c for c in must_checks if c.verified]
        report.coverage = round(len(verified_must) / len(must_checks), 3) if must_checks else 0.0
        report.environment_cleaned = qa_cfg.ephemeral_environment

        blockers = [f for f in report.findings if f.severity == "blocker"]
        if not report.checks:
            report.verdict = QAVerdict.BLOCKED
        elif blockers or report.coverage < qa_cfg.required_coverage:
            report.verdict = QAVerdict.FAIL
        else:
            report.verdict = QAVerdict.PASS
        return report

    def _out_of_scope(self, statement: str, criterion: AcceptanceCriterion) -> bool:
        blob = f"{statement} {criterion.render()}".lower()
        return any(fence.lower() in blob for fence in self.config.qa.out_of_scope)


class DeliveryStage:
    """Packages the run: what shipped, what is still assumed, what stayed open."""

    role = "delivery_agent"

    def package(self, state: RunState) -> Delivery:
        spec = state.spec
        qa = state.qa
        accepted = bool(
            qa
            and qa.verdict is QAVerdict.PASS
            and not (state.clarification and state.clarification.open_blocking)
        )
        artifacts = sorted(
            {f for result in state.work_results for f in result.changed_files}
            | {t for result in state.work_results for t in result.tests_added}
        )
        return Delivery(
            spec_id=spec.id if spec else "",
            accepted=accepted,
            coverage=qa.coverage if qa else 0.0,
            artifacts=artifacts,
            unconfirmed_assumptions=[
                a for a in (spec.assumptions if spec else []) if not a.confirmed
            ],
            residual_questions=[q for q in (spec.open_questions if spec else []) if not q.answered],
            notes="; ".join(qa.summary_lines()) if qa else "no QA report",
        )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _candidate_lines(objective: Objective) -> list[tuple[str, bool]]:
    """Lines worth reading, each flagged as speaker-attributed or not."""
    lines: list[tuple[str, bool]] = [(objective.statement, False)]
    for block in [objective.context, *objective.raw_inputs]:
        for raw in block.splitlines():
            line = raw.strip()
            if len(line) < 8:
                continue
            speaker = _SPEAKER.match(line)
            lines.append((speaker.group(2).strip(), True) if speaker else (line, False))
    return [(text, attributed) for text, attributed in lines if text]


def _dedupe_lines(lines: list[str], similarity: float = 0.7) -> list[str]:
    """Drop exact repeats and near-repeats — a transcript restates the ask often."""
    seen: set[str] = set()
    kept_tokens: list[set[str]] = []
    out: list[str] = []
    for line in lines:
        key = re.sub(r"\W+", "", line.lower())
        if not key or key in seen:
            continue
        tokens = {w for w in re.findall(r"[a-z]{3,}", line.lower())}
        if tokens and any(
            len(tokens & prior) / len(tokens | prior) >= similarity for prior in kept_tokens
        ):
            continue
        seen.add(key)
        kept_tokens.append(tokens)
        out.append(line)
    return out


def _clean(line: str) -> str:
    return re.sub(r"^[-*\d.)\s]+", "", line).strip()


def _priority(statement: str) -> Priority:
    if _COULD.search(statement):
        return Priority.COULD
    if _MUST.search(statement):
        return Priority.MUST
    return Priority.SHOULD if re.search(r"\bshould\b", statement, re.I) else Priority.MUST


def _rationale(statement: str) -> str:
    match = _SO_THAT.search(statement)
    return match.group(1).strip().rstrip(".") if match else ""


def _criterion(req_id: str, statement: str, objective: Objective) -> AcceptanceCriterion:
    outcome = _rationale(statement) or _clean(statement)
    given = (
        objective.context.strip().splitlines()[0]
        if objective.context.strip()
        else "the system is in its normal state"
    )
    return AcceptanceCriterion(
        id=f"{req_id}-AC-001",
        given=_short(given, 120),
        when=_short(_clean(statement), 120),
        then=_short(outcome, 120),
    )


def _metrics(objective: Objective, answers: str) -> list[str]:
    blob = "\n".join([text for text, _ in _candidate_lines(objective)] + [answers])
    return _dedupe_lines([m.group(0).strip() for m in _METRIC.finditer(blob)])[:5]


def _answer_context(clarification: Optional[ClarificationResult]) -> str:
    if not clarification:
        return ""
    return "\n".join(f"{q.text} → {q.answer}" for q in clarification.questions if q.answered)


def _components(spec: Spec) -> list[Component]:
    buckets: dict[str, list[str]] = {}
    for requirement in spec.requirements:
        name = _domain(requirement.statement)
        buckets.setdefault(name, []).append(requirement.id)
    return [
        Component(
            name=name,
            responsibility=f"satisfies {', '.join(req_ids)}",
            requirement_ids=req_ids,
        )
        for name, req_ids in sorted(buckets.items())
    ]


def _domain(statement: str) -> str:
    low = statement.lower()
    for name, keywords in _DOMAINS:
        if any(re.search(rf"\b{re.escape(k)}\b", low) for k in keywords):
            return name
    return "core"


def _title(statement: str) -> str:
    return _short(_clean(statement), 72)


def _short(text: str, limit: int = 48) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
