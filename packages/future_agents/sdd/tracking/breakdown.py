"""Ask → work items: the breakdown that becomes issues, tracking and metrics.

Two failure modes this exists to prevent. One ticket that says "do the refunds
thing" and is never finishable; or forty tickets nobody can trace back to why
they exist. So the tree is derived, not invented:

    objective ──► EPIC
      requirement ──► FEATURE | FIX | INTEGRATION | MIGRATION | SPIKE
        task ──────► SUBTASK (test, code)
      observability task ──► OBSERVABILITY
      structure / review ──► CHORE
      documentation ──────► DOCS

Every task in the graph lands somewhere, so nothing small is untracked; every
item carries the requirement, the criteria, the person who asked and the
capability it delivers, so nothing large is unexplained. The kind is read from
what the ask actually says — a bug report and a new capability are not tracked
the same way, and pretending they are is how "fix" work quietly loses its
regression test.
"""

from __future__ import annotations

import re
from typing import Optional

from future_agents.sdd.models import (
    Objective,
    ObservabilityPlan,
    Plan,
    Priority,
    SemanticModel,
    Spec,
    TaskGraph,
    TaskKind,
    WorkBreakdown,
    WorkItem,
    WorkItemKind,
)

_FIX = re.compile(
    r"\b(fix|bug|broken|regression|incorrect|wrong|fails?|failing|error|defect|"
    r"crash|does not work|doesn't work|stopped)\b",
    re.IGNORECASE,
)

_INTEGRATION = re.compile(
    r"\b(integrat\w*|webhook|third[- ]party|external|connector|api key|oauth|"
    r"sync with|import from|export to|upstream|downstream)\b",
    re.IGNORECASE,
)

_MIGRATION = re.compile(
    r"\b(migrat\w*|backfill|schema change|rename column|move (?:the )?data|"
    r"cut ?over|re-?index|upgrade to)\b",
    re.IGNORECASE,
)

_SPIKE = re.compile(
    r"\b(investigat\w*|spike|research|explore|proof of concept|poc|feasibilit\w*|"
    r"find out|understand why)\b",
    re.IGNORECASE,
)

#: What "done" means, per kind. Generic enough to apply anywhere, specific
#: enough that ticking them all means something.
_DEFINITION_OF_DONE: dict[WorkItemKind, tuple[str, ...]] = {
    WorkItemKind.FEATURE: (
        "every acceptance criterion has a passing test",
        "the change sits where the repository's conventions say it should",
        "signals and objectives for it are live",
        "docs and the delivery record updated",
    ),
    WorkItemKind.FIX: (
        "a test reproduces the failure before the fix",
        "that test passes after it",
        "the root cause is named in the issue, not just the symptom",
        "a signal would have caught it — if not, one is added",
    ),
    WorkItemKind.INTEGRATION: (
        "the contract with the other side is written down",
        "failure of the other side is handled and observable",
        "credentials come from the environment, never the code",
        "a test runs against a recorded or stubbed peer",
    ),
    WorkItemKind.MIGRATION: (
        "forward migration tested on a copy of real-shaped data",
        "rollback path written and tested",
        "the cutover is reversible, or a human has explicitly approved that it is not",
        "row counts and checksums reconciled after the run",
    ),
    WorkItemKind.SPIKE: (
        "the question is answered in writing",
        "the answer names what it would cost to act on",
        "a follow-up item exists, or the idea is explicitly dropped",
    ),
    WorkItemKind.OBSERVABILITY: (
        "the signals emit in a real run",
        "each objective has a burn-rate alert",
        "the runbook section the alert points at exists",
    ),
    WorkItemKind.CHORE: ("the check passes in CI, not only locally",),
    WorkItemKind.DOCS: ("a reader who was not in the room can follow it",),
    WorkItemKind.TEST: ("the test fails before the change and passes after",),
    WorkItemKind.SUBTASK: ("its parent's criteria are closer to provable than before",),
    WorkItemKind.EPIC: (
        "every child is closed or explicitly dropped",
        "QA coverage of MUST criteria is 100%",
        "the delivery record names what is still assumed",
    ),
}


class WorkBreakdownBuilder:
    """Spec + plan + task graph + semantics → a tracked tree of work items."""

    def __init__(self, repo: str = "") -> None:
        self.repo = repo

    def build(
        self,
        objective: Objective,
        spec: Spec,
        plan: Optional[Plan] = None,
        graph: Optional[TaskGraph] = None,
        semantics: Optional[SemanticModel] = None,
        observability: Optional[ObservabilityPlan] = None,
    ) -> WorkBreakdown:
        counter = _Counter()
        breakdown = WorkBreakdown(spec_id=spec.id)

        epic = self._epic(objective, spec, counter, semantics)
        breakdown.items.append(epic)
        breakdown.root_id = epic.id

        by_requirement: dict[str, WorkItem] = {}
        for requirement in spec.requirements:
            item = self._requirement_item(
                requirement, epic, spec, plan, semantics, observability, counter
            )
            breakdown.items.append(item)
            by_requirement[requirement.id] = item

        if graph is not None:
            breakdown.items.extend(
                self._task_items(graph, epic, by_requirement, observability, counter)
            )

        epic.definition_of_done = list(_DEFINITION_OF_DONE[WorkItemKind.EPIC])
        epic.task_ids = [t.id for t in graph.tasks] if graph else []
        return breakdown

    # ── The epic ──────────────────────────────────────────────────────────────

    def _epic(
        self,
        objective: Objective,
        spec: Spec,
        counter: "_Counter",
        semantics: Optional[SemanticModel],
    ) -> WorkItem:
        external = objective.external
        return WorkItem(
            id=counter.next(),
            kind=WorkItemKind.EPIC,
            title=spec.title or objective.statement[:80],
            intent=objective.statement,
            # Only a real "so that" counts. Falling back to the summary would
            # dress a restatement of the ask up as the reason for it.
            outcome=_outcome(objective.statement),
            description=spec.summary,
            requirement_ids=[r.id for r in spec.requirements],
            criterion_ids=[ac.id for ac in spec.criteria()],
            labels=_labels(
                WorkItemKind.EPIC,
                domain=semantics.domain if semantics else "",
                repo=self.repo,
            ),
            requested_by=(
                external.author if external and external.author else objective.submitted_by
            ),
            source=external.key if external else objective.source.value,
            source_url=external.url if external else "",
            status=_status_of(spec),
            risk="medium",
        )

    # ── One item per requirement ──────────────────────────────────────────────

    def _requirement_item(
        self,
        requirement,
        epic: WorkItem,
        spec: Spec,
        plan: Optional[Plan],
        semantics: Optional[SemanticModel],
        observability: Optional[ObservabilityPlan],
        counter: "_Counter",
    ) -> WorkItem:
        kind = self._kind_of(requirement.statement, spec)
        capability = semantics.capability_for(requirement.id) if semantics else None
        placement = plan.placement_for(requirement.id) if plan else None
        components = plan.components if plan else []
        component = next(
            (c.name for c in components if requirement.id in c.requirement_ids),
            "",
        )
        slos = [
            s
            for s in (observability.slos if observability else [])
            if s.requirement_id == requirement.id
        ]
        signals = [
            s
            for s in (observability.signals if observability else [])
            if requirement.id in s.requirement_ids
        ]
        return WorkItem(
            id=counter.next(),
            kind=kind,
            parent_id=epic.id,
            title=_short(requirement.statement),
            intent=requirement.statement,
            outcome=capability.outcome if capability else _outcome(requirement.statement),
            description=capability.render() if capability else requirement.rationale,
            requirement_ids=[requirement.id],
            criterion_ids=[ac.id for ac in requirement.acceptance_criteria],
            capability_id=capability.id if capability else "",
            component=component,
            target_paths=[p for p in [placement.target_path, placement.test_path] if p]
            if placement
            else [],
            forbidden_paths=[z.path for z in placement.forbidden] if placement else [],
            labels=_labels(
                kind,
                domain=semantics.domain if semantics else "",
                repo=self.repo,
                priority=requirement.priority,
                component=component,
            ),
            definition_of_done=list(_DEFINITION_OF_DONE.get(kind, ())),
            slo_ids=[s.id for s in slos],
            signal_ids=[s.id for s in signals],
            risk="high"
            if requirement.priority is Priority.MUST and kind is WorkItemKind.MIGRATION
            else ("medium" if requirement.priority is Priority.MUST else "low"),
            estimate=_estimate(requirement),
            requested_by=epic.requested_by,
            source=epic.source,
            source_url=epic.source_url,
        )

    @staticmethod
    def _kind_of(statement: str, spec: Spec) -> WorkItemKind:
        """Read the kind from the ask. Order matters: a migration that fixes a
        bug is still a migration, because that is what makes it dangerous."""
        blob = f"{statement} {spec.summary}"
        if _MIGRATION.search(blob):
            return WorkItemKind.MIGRATION
        if _SPIKE.search(statement):
            return WorkItemKind.SPIKE
        if _FIX.search(statement):
            return WorkItemKind.FIX
        if _INTEGRATION.search(blob):
            return WorkItemKind.INTEGRATION
        return WorkItemKind.FEATURE

    # ── One item per task, so nothing small is untracked ──────────────────────

    def _task_items(
        self,
        graph: TaskGraph,
        epic: WorkItem,
        by_requirement: dict[str, WorkItem],
        observability: Optional[ObservabilityPlan],
        counter: "_Counter",
    ) -> list[WorkItem]:
        items: list[WorkItem] = []
        for task in graph.tasks:
            parent = next(
                (by_requirement[rid] for rid in task.requirement_ids if rid in by_requirement),
                epic,
            )
            kind = _TASK_KIND.get(task.kind, WorkItemKind.SUBTASK)
            # A review or docs task that traces to every requirement belongs to
            # the epic, not to whichever requirement happens to be listed first.
            if (
                task.kind in (TaskKind.REVIEW, TaskKind.DOC, TaskKind.INFRA)
                or len(task.requirement_ids) > 1
            ):
                parent = epic
            item = WorkItem(
                id=counter.next(),
                kind=kind,
                parent_id=parent.id,
                title=task.title,
                intent=task.description.splitlines()[0] if task.description else task.title,
                description=task.description,
                requirement_ids=list(task.requirement_ids),
                criterion_ids=list(task.criterion_ids),
                task_ids=[task.id],
                component=task.component,
                target_paths=list(task.artifacts),
                depends_on=[i.id for i in items if set(i.task_ids) & set(task.depends_on)],
                labels=_labels(kind, repo=self.repo, component=task.component),
                definition_of_done=list(_DEFINITION_OF_DONE.get(kind, ())),
                requested_by=epic.requested_by,
                source=epic.source,
                source_url=epic.source_url,
                estimate="S",
            )
            if kind is WorkItemKind.OBSERVABILITY and observability is not None:
                item.signal_ids = [s.id for s in observability.signals_for(task.component)]
                item.slo_ids = [s.id for s in observability.slos]
            items.append(item)
        return items


# ── Helpers ───────────────────────────────────────────────────────────────────

_TASK_KIND = {
    TaskKind.TEST: WorkItemKind.TEST,
    TaskKind.CODE: WorkItemKind.SUBTASK,
    TaskKind.INFRA: WorkItemKind.CHORE,
    TaskKind.DOC: WorkItemKind.DOCS,
    TaskKind.REVIEW: WorkItemKind.CHORE,
    TaskKind.OBSERVABILITY: WorkItemKind.OBSERVABILITY,
}


def _labels(
    kind: WorkItemKind,
    *,
    domain: str = "",
    repo: str = "",
    priority: Optional[Priority] = None,
    component: str = "",
) -> list[str]:
    """Labels a board can filter on without anyone maintaining a taxonomy."""
    labels = [f"type:{kind.value}"]
    if domain:
        labels.append(f"domain:{domain}")
    if repo:
        labels.append(f"repo:{repo}")
    if priority is not None:
        labels.append(f"priority:{priority.value}")
    if component:
        labels.append(f"component:{component}")
    labels.append("sdd:generated")
    return labels


def _estimate(requirement) -> str:
    """S/M/L from how much has to be proved, not from how it feels."""
    criteria = len(requirement.acceptance_criteria)
    if criteria <= 1:
        return "S"
    return "M" if criteria <= 3 else "L"


def _status_of(spec: Spec):
    from future_agents.sdd.models import WorkItemStatus

    blocking = [q for q in spec.open_questions if q.blocking and not q.answered]
    return WorkItemStatus.BLOCKED if blocking else WorkItemStatus.READY


def _outcome(statement: str) -> str:
    match = re.search(r"\bso that\b(.+)$", statement, re.IGNORECASE)
    return match.group(1).strip().rstrip(".") if match else ""


def _short(text: str, limit: int = 90) -> str:
    flat = re.sub(r"\s+", " ", (text or "").strip())
    flat = re.sub(r"\s+so that\b.*$", "", flat, flags=re.IGNORECASE)
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


class _Counter:
    def __init__(self) -> None:
        self._n = 0

    def next(self) -> str:
        self._n += 1
        return f"WI-{self._n:03d}"
