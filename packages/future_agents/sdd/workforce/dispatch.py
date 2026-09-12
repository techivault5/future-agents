"""Dispatch — which agent takes this task, and which skill it uses.

Scoring is explicit and inspectable rather than learned end-to-end: the reason a
task went to an agent is written on the assignment, so a bad routing decision can
be argued with. Past outcomes do move the needle — an agent that keeps failing a
kind of work stops being chosen for it — but they never override a hard
constraint like language or concurrency.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from future_agents.sdd.models import Assignment, Spec, TaskUnit
from future_agents.sdd.workforce.registry import AgentSpec, SkillSpec, Workforce


class ScoreWeights(BaseModel):
    kind: float = 2.0
    domain: float = 1.5
    language: float = 1.0
    success: float = 2.0
    cost: float = 0.5
    headroom: float = 0.5


class Candidate(BaseModel):
    agent: AgentSpec
    score: float
    reasons: list[str] = Field(default_factory=list)


class NoAgentAvailable(RuntimeError):
    """Nobody can take this task — the caller decides whether that is fatal."""


class Dispatcher:
    """Matches tasks to agents and skills, and remembers how it went."""

    def __init__(
        self,
        workforce: Workforce,
        weights: Optional[ScoreWeights] = None,
        language: str = "",
    ) -> None:
        self.workforce = workforce
        self.weights = weights or ScoreWeights()
        self.language = language

    # ── Selection ─────────────────────────────────────────────────────────────

    def rank(self, task: TaskUnit) -> list[Candidate]:
        weights = self.weights
        ranked: list[Candidate] = []
        for spec in self.workforce.candidates(task, self.language):
            health = self.workforce.health[spec.id]
            reasons: list[str] = []
            score = 0.0

            if spec.kinds and task.kind.value in spec.kinds:
                score += weights.kind
                reasons.append(f"handles {task.kind.value} tasks")
            overlap = spec.domain_overlap(task)
            if overlap:
                score += weights.domain * overlap
                reasons.append(f"domain match {overlap:.0%}")
            if self.language and self.language in spec.languages:
                score += weights.language
                reasons.append(f"speaks {self.language}")
            score += weights.success * health.success_rate
            if health.attempts:
                reasons.append(f"{health.successes}/{health.attempts} past successes")
            score -= weights.cost * spec.cost_hint
            headroom = max(0, spec.max_concurrency - health.in_flight) / max(
                1, spec.max_concurrency
            )
            score += weights.headroom * headroom
            score -= spec.priority * 0.01  # stable tie-break

            ranked.append(Candidate(agent=spec, score=round(score, 4), reasons=reasons))

        ranked.sort(key=lambda c: c.score, reverse=True)
        return ranked

    def assign(self, task: TaskUnit, spec: Optional[Spec] = None) -> Assignment:
        """Pick an agent and a skill, and say why."""
        del spec  # the task carries everything routing needs
        ranked = self.rank(task)
        if not ranked:
            raise NoAgentAvailable(
                f"no agent available for {task.id} ({task.kind.value}, {self.language or 'any'})"
            )
        best = ranked[0]
        skill = self.pick_skill(task, best.agent)
        runner_up = f"; runner-up {ranked[1].agent.id}" if len(ranked) > 1 else ""
        why = "; ".join(best.reasons) or "default"
        assignment = Assignment(
            task_id=task.id,
            agent_id=best.agent.id,
            skill_id=skill.id if skill else "",
            rationale=f"{best.agent.id} scored {best.score} ({why}){runner_up}",
        )
        self.workforce.start(best.agent.id)
        return assignment

    def pick_skill(self, task: TaskUnit, agent: AgentSpec) -> Optional[SkillSpec]:
        skills = self.workforce.skills_for(task, agent, self.language)
        if not skills:
            return None
        # Prefer a skill that names this task kind explicitly over a generic one.
        skills.sort(key=lambda s: (0 if task.kind.value in s.kinds else 1, len(s.triggers) * -1))
        return skills[0]

    # ── Outcomes ──────────────────────────────────────────────────────────────

    def record(
        self,
        assignment: Assignment,
        ok: bool,
        seconds: float = 0.0,
        error: str = "",
    ) -> None:
        if assignment.agent_id:
            self.workforce.finish(assignment.agent_id, ok=ok, seconds=seconds, error=error)

    def explain(self, task: TaskUnit) -> list[str]:
        """Why each candidate scored what it did — for a human reading a plan."""
        return [
            f"{c.score:6.3f}  {c.agent.id:24s} {'; '.join(c.reasons) or 'no specific signal'}"
            for c in self.rank(task)
        ]
