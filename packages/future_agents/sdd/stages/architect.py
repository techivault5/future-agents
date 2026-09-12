"""Architect stage — spec into a plan, bounded by memory, persona and toolchain."""

from __future__ import annotations

from typing import Optional

from future_agents.sdd.config import SpecKitConfig
from future_agents.sdd.knowledge import RepoKnowledge
from future_agents.sdd.memory import RetrievalReport
from future_agents.sdd.models import (
    Component,
    PlacementDecision,
    Plan,
    RepoMatch,
    Risk,
    Spec,
)
from future_agents.sdd.observability import ObservabilityPlanner
from future_agents.sdd.personas import DEFAULT_PERSONA, Persona
from future_agents.sdd.repos.languages import Toolchain
from future_agents.sdd.router import EngineCall, EngineRouter
from future_agents.sdd.stages._extract import _components


class ArchitectStage:
    """Spec → plan, with the memory hub's past pitfalls injected as constraints."""

    role = "architect_agent"

    def __init__(
        self,
        config: Optional[SpecKitConfig] = None,
        router: Optional[EngineRouter] = None,
        persona: Optional[Persona] = None,
        toolchain: Optional[Toolchain] = None,
        knowledge: Optional[RepoKnowledge] = None,
    ) -> None:
        self.config = config or SpecKitConfig()
        self.router = router or EngineRouter(self.config)
        self.persona = persona or DEFAULT_PERSONA
        self.toolchain = toolchain
        self.knowledge = knowledge

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
        # A lesson recurred across runs; a case pitfall happened once. The plan
        # should not weigh those the same.
        lesson_texts = {lesson.text for lesson in memory.lessons} if memory else set()
        for warning in warnings:
            recurring = any(warning.startswith(text) for text in lesson_texts)
            risks.append(
                Risk(
                    description=warning,
                    severity="high" if recurring else "medium",
                    mitigation="address explicitly in the task graph",
                    source="memory-lesson" if recurring else "memory",
                )
            )

        # Experience enters the plan as risks, not as advice in a prompt.
        risks.extend(self.persona.risks_for(spec))

        placements, reuse = self._placements(spec, components)
        risks.extend(self._placement_risks(placements, spec))

        # Monitoring is designed with the feature, not after it: a change nobody
        # can see failing is not finished, whatever the tests say.
        observability = None
        if self.config.observability.enabled:
            for component in components:
                placement = _placement_path(placements, component)
                if placement and not component.target_path:
                    component.target_path = placement
            observability = ObservabilityPlanner(self.config.observability, self.toolchain).build(
                spec, components
            )
            risks.extend(
                Risk(
                    description=f"observability gap: {gap}",
                    severity="medium",
                    mitigation="add the missing signal or make the criterion measurable",
                    source="observability",
                )
                for gap in observability.gaps
            )

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
            memory_lesson_ids=[ln.id for ln in memory.lessons] if memory else [],
            placements=placements,
            reuse_candidates=reuse,
            observability=observability,
            confidence=round(max(0.0, spec.confidence - 0.05 * high), 3),
        )

    def _placements(
        self, spec: Spec, components: list[Component]
    ) -> tuple[list[PlacementDecision], list[RepoMatch]]:
        """Where each requirement's code goes, decided from the repository itself."""
        if self.knowledge is None:
            return [], []
        placements = self.knowledge.plan_placements(spec)
        by_requirement = {p.requirement_id: p for p in placements}
        for component in components:
            paths = [
                by_requirement[req].target_path
                for req in component.requirement_ids
                if req in by_requirement and by_requirement[req].target_path
            ]
            if paths:
                component.target_path = _common_root(paths)
        reuse: list[RepoMatch] = []
        seen: set[str] = set()
        for placement in placements:
            for match in placement.reuse:
                if match.path in seen:
                    continue
                seen.add(match.path)
                reuse.append(match)
        return placements, reuse[:6]

    def _placement_risks(self, placements: list[PlacementDecision], spec: Spec) -> list[Risk]:
        risks: list[Risk] = []
        for placement in placements:
            for zone in placement.forbidden:
                if zone.path == placement.target_path:
                    risks.append(
                        Risk(
                            description=f"{placement.requirement_id}: {zone.reason}",
                            severity="high",
                            mitigation=f"place it in {placement.alternatives[0].path}"
                            if placement.alternatives
                            else "choose another location",
                            source="repo-knowledge",
                        )
                    )
        for note in spec.context_notes:
            risks.append(
                Risk(
                    description=note,
                    severity="medium",
                    mitigation="read the existing implementation before writing a new one",
                    source="repo-knowledge",
                )
            )
        return risks

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


def _common_root(paths: list[str]) -> str:
    """The deepest directory every placement shares — a component's home."""
    directories = [p.rsplit("/", 1)[0] if "/" in p else "" for p in paths]
    if not directories:
        return ""
    parts = [d.split("/") for d in directories]
    shared: list[str] = []
    for segments in zip(*parts):
        if len(set(segments)) != 1:
            break
        shared.append(segments[0])
    return "/".join(shared)


def _placement_path(placements: list[PlacementDecision], component: Component) -> str:
    """The file a component's instrumentation belongs in, if one was decided."""
    for placement in placements:
        if placement.requirement_id in component.requirement_ids and placement.target_path:
            return placement.target_path
    return ""
