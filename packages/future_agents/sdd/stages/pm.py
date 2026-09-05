"""PM stage — transcript, ticket or chat into a spec with traceable ids."""

from __future__ import annotations

from typing import Optional

from future_agents.sdd.config import SpecKitConfig
from future_agents.sdd.knowledge import RepoKnowledge
from future_agents.sdd.models import ClarificationResult, Objective, Requirement, Spec
from future_agents.sdd.router import EngineCall, EngineRouter
from future_agents.sdd.stages._extract import (
    _ACTION,
    _IMPERATIVE,
    _OUT_OF_SCOPE,
    _answer_context,
    _candidate_lines,
    _clean,
    _criterion,
    _dedupe_lines,
    _metrics,
    _priority,
    _rationale,
    _title,
)


class PMStage:
    """Meeting transcript / ticket / chat → a functional spec with traceable IDs."""

    role = "pm_agent"

    def __init__(
        self,
        config: Optional[SpecKitConfig] = None,
        router: Optional[EngineRouter] = None,
        knowledge: Optional[RepoKnowledge] = None,
    ) -> None:
        self.config = config or SpecKitConfig()
        self.router = router or EngineRouter(self.config)
        self.knowledge = knowledge

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
            # The objective itself is never out of scope, whatever words it uses.
            if idx > 1 and _OUT_OF_SCOPE.search(statement):
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
        context_notes = self._context_notes(requirements)
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
            context_notes=context_notes,
            confidence=clarification.confidence if clarification else 0.5,
        )

    def _context_notes(self, requirements: list[Requirement]) -> list[str]:
        """What the repository already does about each requirement.

        A requirement that closely matches existing code is a duplicate risk, and
        saying so before the plan is drawn is far cheaper than finding out after.
        """
        if self.knowledge is None:
            return []
        notes: list[str] = []
        for requirement in requirements:
            for match in self.knowledge.duplicate_risk(requirement):
                notes.append(
                    f"{requirement.id} may already be covered by {match.render()} — "
                    "confirm this is a change, not a duplicate"
                )
        return notes[:8]

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
