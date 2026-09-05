"""QA stage — BDD/AAA checks, scope fences, coverage arithmetic, short reports."""

from __future__ import annotations

from typing import Optional

from future_agents.sdd.config import SpecKitConfig
from future_agents.sdd.models import (
    AcceptanceCriterion,
    BehaviourCheck,
    Priority,
    QAFinding,
    QAReport,
    QAVerdict,
    Requirement,
    Spec,
    TaskGraph,
    TaskKind,
    TaskStatus,
    WorkResult,
)


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
