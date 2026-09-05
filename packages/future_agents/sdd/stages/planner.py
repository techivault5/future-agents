"""Planner stage — a plan into a dependency-ordered, test-first task DAG."""

from __future__ import annotations

from typing import Optional

from future_agents.sdd.config import SpecKitConfig
from future_agents.sdd.models import (
    PlacementDecision,
    Plan,
    Spec,
    TaskGraph,
    TaskKind,
    TaskUnit,
)
from future_agents.sdd.personas import DEFAULT_PERSONA, Persona
from future_agents.sdd.repos.languages import Toolchain
from future_agents.sdd.repos.scaffold import RepoScaffolder
from future_agents.sdd.router import EngineRouter
from future_agents.sdd.stages._extract import _short


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

    def build(self, plan: Plan, spec: Spec) -> TaskGraph:  # noqa: C901
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
                    artifacts=[component.target_path] if component.target_path else [],
                    engine=self.router.decide("worker_agent", component.name).engine,
                )
            )
            code_ids.append(scaffold_id)

            for req_id in component.requirement_ids:
                requirement = spec.requirement(req_id)
                if requirement is None:
                    continue
                criterion_ids = [ac.id for ac in requirement.acceptance_criteria]
                placement = plan.placement_for(req_id)
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
                        artifacts=[placement.test_path] if placement else [],
                    )
                )
                impl_id = next_id()
                tasks.append(
                    TaskUnit(
                        id=impl_id,
                        title=f"Implement {req_id}: {_short(requirement.statement)}",
                        description=_with_placement(requirement.statement, placement),
                        kind=TaskKind.CODE,
                        requirement_ids=[req_id],
                        criterion_ids=criterion_ids,
                        depends_on=[test_id],  # test first — the unit is red before it is green
                        component=component.name,
                        engine=self.router.decide("worker_agent", requirement.statement).engine,
                        artifacts=[placement.target_path] if placement else [],
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


def _with_placement(statement: str, placement: Optional[PlacementDecision]) -> str:
    """Tell the worker where the change goes — and where it must not."""
    if placement is None:
        return statement
    lines = [statement, f"Goes in: {placement.target_path} ({placement.approach})"]
    if placement.rationale:
        lines.append(f"Why there: {placement.rationale}")
    if placement.reuse:
        lines.append("Read first: " + ", ".join(m.render() for m in placement.reuse[:2]))
    if placement.alternatives:
        alternative = placement.alternatives[0]
        lines.append(f"Alternative: {alternative.path} — {alternative.tradeoff}")
    if placement.forbidden:
        lines.append(
            "Do not put it in: "
            + "; ".join(f"{z.path} ({z.reason})" for z in placement.forbidden[:3])
        )
    return "\n".join(lines)
