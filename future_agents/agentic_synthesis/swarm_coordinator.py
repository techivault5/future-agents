"""Swarm Coordinator — parallel role-based agents with weighted consensus.

Synthesises:
  CrewAI   → named specialist roles with distinct instructions
  MetaGPT  → structured company roles (researcher, planner, executor, critic)
  AutoGen  → multi-agent conversation with round-based refinement
  CAMEL    → role-play between agents for richer outputs
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentRole(str, Enum):
    RESEARCHER  = "researcher"    # gathers facts and evidence
    PLANNER     = "planner"       # decomposes and sequences steps
    EXECUTOR    = "executor"      # produces concrete implementation
    CRITIC      = "critic"        # identifies flaws and edge cases
    SYNTHESIZER = "synthesizer"   # integrates all views into final answer


@dataclass
class SwarmSpec:
    task: str
    roles: list[AgentRole]
    context: dict[str, Any] = field(default_factory=dict)
    max_rounds: int = 2
    consensus_threshold: float = 0.65


@dataclass
class AgentVote:
    role: AgentRole
    answer: str
    confidence: float       # 0.0-1.0
    reasoning: str = ""
    tokens_used: int = 0


@dataclass
class SwarmResult:
    consensus: str
    confidence: float
    votes: list[AgentVote]
    rounds: int
    dissenting_views: list[str] = field(default_factory=list)


# Role-specific instructions (inspired by MetaGPT company roles)
_ROLE_INSTRUCTIONS: dict[AgentRole, str] = {
    AgentRole.RESEARCHER: (
        "Focus on gathering evidence, facts, and relevant context. Cite specifics."
    ),
    AgentRole.PLANNER: (
        "Focus on decomposing the task into clear, ordered steps. Prioritise structure."
    ),
    AgentRole.EXECUTOR: (
        "Focus on concrete, working implementation. Prefer actionable over abstract."
    ),
    AgentRole.CRITIC: (
        "Focus on flaws, edge cases, risks, and what could go wrong. Be constructive."
    ),
    AgentRole.SYNTHESIZER: "Integrate all perspectives into one coherent, balanced final response.",
}

# Synthesizer and Executor carry more weight; Critic is slightly downweighted
_ROLE_WEIGHTS: dict[AgentRole, float] = {
    AgentRole.RESEARCHER:  1.0,
    AgentRole.PLANNER:     1.0,
    AgentRole.EXECUTOR:    1.2,
    AgentRole.CRITIC:      0.8,
    AgentRole.SYNTHESIZER: 1.4,
}


class SwarmCoordinator:
    """Parallel multi-agent crew that reaches consensus through weighted voting.

    When client is None (no SDK), returns deterministic stub votes for testing.
    """

    def __init__(self, client=None) -> None:
        self._client = client

    async def execute(self, spec: SwarmSpec) -> SwarmResult:
        """Run the swarm for up to spec.max_rounds, stopping early on consensus."""
        all_votes: list[AgentVote] = []
        rounds_run = 0

        for round_num in range(1, spec.max_rounds + 1):
            rounds_run = round_num
            round_votes = await asyncio.gather(
                *[self._run_role(role, spec.task, spec.context, round_num) for role in spec.roles]
            )
            all_votes.extend(round_votes)

            consensus, confidence = self._aggregate(list(round_votes))
            if confidence >= spec.consensus_threshold:
                break

            # Feed this round's answers into context for the next round
            spec.context = {
                **spec.context,
                "round_{}_answers".format(round_num): {
                    v.role.value: v.answer[:200] for v in round_votes
                },
            }

        consensus, confidence = self._aggregate(all_votes)
        dissenters = [v.answer for v in all_votes if v.confidence < 0.35]

        return SwarmResult(
            consensus=consensus,
            confidence=round(confidence, 3),
            votes=all_votes,
            rounds=rounds_run,
            dissenting_views=dissenters,
        )

    async def _run_role(
        self, role: AgentRole, task: str, context: dict, round_num: int
    ) -> AgentVote:
        instruction = _ROLE_INSTRUCTIONS[role]
        ctx_str = (
            "\n".join(f"  {k}: {str(v)[:150]}" for k, v in context.items())
            if context else "  (none)"
        )

        if self._client is None:
            return AgentVote(
                role=role,
                answer=f"[{role.value} stub] {task[:80]}",
                confidence=0.72,
                reasoning="SDK unavailable",
            )

        prompt = (
            f"You are a {role.value} agent. {instruction}\n\n"
            f"Task: {task}\n\nContext:\n{ctx_str}\n\nRound: {round_num}\n\n"
            "Respond in exactly this format:\n"
            "ANSWER: <your answer>\n"
            "CONFIDENCE: <0.0–1.0>\n"
            "REASONING: <one sentence>"
        )
        try:
            response = self._client.messages.create(
                model="claude-opus-4-7",
                max_tokens=512,
                thinking={"type": "adaptive"},
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
            answer = confidence_raw = reasoning = ""
            for line in text.splitlines():
                if line.startswith("ANSWER:"):
                    answer = line[7:].strip()
                elif line.startswith("CONFIDENCE:"):
                    confidence_raw = line[11:].strip()
                elif line.startswith("REASONING:"):
                    reasoning = line[10:].strip()
            try:
                confidence = max(0.0, min(1.0, float(confidence_raw)))
            except ValueError:
                confidence = 0.7
            tokens = response.usage.input_tokens + response.usage.output_tokens
            return AgentVote(
                role=role,
                answer=answer or text[:300],
                confidence=confidence,
                reasoning=reasoning,
                tokens_used=tokens,
            )
        except Exception as exc:
            return AgentVote(role=role, answer=f"Error: {exc}", confidence=0.0)

    def _aggregate(self, votes: list[AgentVote]) -> tuple[str, float]:
        if not votes:
            return "", 0.0

        # Synthesizer with good confidence wins
        for v in votes:
            if v.role == AgentRole.SYNTHESIZER and v.confidence >= 0.55:
                weighted = self._weighted_confidence(votes)
                return v.answer, weighted

        # Fallback: highest weighted vote
        best = max(votes, key=lambda v: _ROLE_WEIGHTS.get(v.role, 1.0) * v.confidence)
        return best.answer, self._weighted_confidence(votes)

    @staticmethod
    def _weighted_confidence(votes: list[AgentVote]) -> float:
        total_weight = sum(_ROLE_WEIGHTS.get(v.role, 1.0) for v in votes)
        weighted_sum = sum(_ROLE_WEIGHTS.get(v.role, 1.0) * v.confidence for v in votes)
        return round(min(weighted_sum / total_weight, 1.0), 3) if total_weight else 0.0
