"""Adaptive Router — routes tasks to the optimal pattern + agent combination.

Synthesises:
  MRKL   → modular expert routing per task type
  Voyager → skill selection based on prior success rates
  BabyAGI → task complexity + priority awareness
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TaskDomain(str, Enum):
    REASONING = "reasoning"
    CODING = "coding"
    RESEARCH = "research"
    SYNTHESIS = "synthesis"
    COORDINATION = "coordination"
    VALIDATION = "validation"
    CREATIVITY = "creativity"
    PLANNING = "planning"


class TaskComplexity(str, Enum):
    TRIVIAL = "trivial"
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"
    CRITICAL = "critical"


@dataclass
class RouteDecision:
    pattern: str
    agent_type: str
    complexity: TaskComplexity
    domain: TaskDomain
    rationale: str
    confidence: float
    fallback_pattern: str = "ReAct"


@dataclass
class RoutingRecord:
    task_id: str
    decision: RouteDecision
    outcome: str  # "success" | "partial" | "failure"
    latency_ms: float = 0.0
    tokens_used: int = 0


# (domain, complexity) → preferred pattern
_ROUTING_TABLE: dict[tuple[TaskDomain, TaskComplexity], str] = {
    (TaskDomain.REASONING, TaskComplexity.TRIVIAL): "Chain-of-Thought",
    (TaskDomain.REASONING, TaskComplexity.SIMPLE): "Chain-of-Thought",
    (TaskDomain.REASONING, TaskComplexity.MODERATE): "ReAct",
    (TaskDomain.REASONING, TaskComplexity.COMPLEX): "Plan-and-Execute",
    (TaskDomain.REASONING, TaskComplexity.CRITICAL): "Reflection",
    (TaskDomain.CODING, TaskComplexity.TRIVIAL): "Tool-Use",
    (TaskDomain.CODING, TaskComplexity.SIMPLE): "ReAct",
    (TaskDomain.CODING, TaskComplexity.MODERATE): "ReAct",
    (TaskDomain.CODING, TaskComplexity.COMPLEX): "Plan-and-Execute",
    (TaskDomain.CODING, TaskComplexity.CRITICAL): "Reflection",
    (TaskDomain.RESEARCH, TaskComplexity.TRIVIAL): "Tool-Use",
    (TaskDomain.RESEARCH, TaskComplexity.SIMPLE): "ReAct",
    (TaskDomain.RESEARCH, TaskComplexity.MODERATE): "Memory-Augmented",
    (TaskDomain.RESEARCH, TaskComplexity.COMPLEX): "Memory-Augmented",
    (TaskDomain.RESEARCH, TaskComplexity.CRITICAL): "Plan-and-Execute",
    (TaskDomain.SYNTHESIS, TaskComplexity.TRIVIAL): "Chain-of-Thought",
    (TaskDomain.SYNTHESIS, TaskComplexity.SIMPLE): "Reflection",
    (TaskDomain.SYNTHESIS, TaskComplexity.MODERATE): "Reflection",
    (TaskDomain.SYNTHESIS, TaskComplexity.COMPLEX): "Subagent-Delegation",
    (TaskDomain.SYNTHESIS, TaskComplexity.CRITICAL): "Self-Consistency",
    (TaskDomain.COORDINATION, TaskComplexity.TRIVIAL): "Tool-Use",
    (TaskDomain.COORDINATION, TaskComplexity.SIMPLE): "Plan-and-Execute",
    (TaskDomain.COORDINATION, TaskComplexity.MODERATE): "Subagent-Delegation",
    (TaskDomain.COORDINATION, TaskComplexity.COMPLEX): "Subagent-Delegation",
    (TaskDomain.COORDINATION, TaskComplexity.CRITICAL): "Subagent-Delegation",
    (TaskDomain.VALIDATION, TaskComplexity.TRIVIAL): "Chain-of-Thought",
    (TaskDomain.VALIDATION, TaskComplexity.SIMPLE): "Self-Consistency",
    (TaskDomain.VALIDATION, TaskComplexity.MODERATE): "Reflection",
    (TaskDomain.VALIDATION, TaskComplexity.COMPLEX): "Self-Consistency",
    (TaskDomain.VALIDATION, TaskComplexity.CRITICAL): "Self-Consistency",
    (TaskDomain.CREATIVITY, TaskComplexity.TRIVIAL): "Chain-of-Thought",
    (TaskDomain.CREATIVITY, TaskComplexity.SIMPLE): "Reflection",
    (TaskDomain.CREATIVITY, TaskComplexity.MODERATE): "Reflection",
    (TaskDomain.CREATIVITY, TaskComplexity.COMPLEX): "Subagent-Delegation",
    (TaskDomain.CREATIVITY, TaskComplexity.CRITICAL): "Self-Consistency",
    (TaskDomain.PLANNING, TaskComplexity.TRIVIAL): "Chain-of-Thought",
    (TaskDomain.PLANNING, TaskComplexity.SIMPLE): "Plan-and-Execute",
    (TaskDomain.PLANNING, TaskComplexity.MODERATE): "Plan-and-Execute",
    (TaskDomain.PLANNING, TaskComplexity.COMPLEX): "Plan-and-Execute",
    (TaskDomain.PLANNING, TaskComplexity.CRITICAL): "Reflection",
}

_AGENT_TABLE: dict[TaskDomain, str] = {
    TaskDomain.REASONING: "digital_worker",
    TaskDomain.CODING: "digital_worker",
    TaskDomain.RESEARCH: "knowledge",
    TaskDomain.SYNTHESIS: "knowledge",
    TaskDomain.COORDINATION: "master",
    TaskDomain.VALIDATION: "quality",
    TaskDomain.CREATIVITY: "digital_worker",
    TaskDomain.PLANNING: "master",
}

# If pattern success rate drops below this, escalate
_ESCALATION_MAP: dict[str, str] = {
    "Chain-of-Thought": "ReAct",
    "Tool-Use": "ReAct",
    "ReAct": "Reflection",
    "Memory-Augmented": "ReAct",
    "Plan-and-Execute": "Reflection",
    "Reflection": "Self-Consistency",
    "Subagent-Delegation": "Plan-and-Execute",
}

_STOP_WORDS = {"a", "an", "the", "is", "it", "to", "for", "of", "in", "on", "at", "and", "or"}


class AdaptiveRouter:
    """Routes each task to the optimal (pattern, agent_type) pair.

    Learns from recorded outcomes: patterns with <50% success in recent
    history are escalated to more powerful alternatives.
    """

    def __init__(self) -> None:
        self._history: list[RoutingRecord] = []
        self._pattern_outcomes: dict[str, list[bool]] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def classify(self, task: str, hints: dict | None = None) -> tuple[TaskDomain, TaskComplexity]:
        """Classify task into (domain, complexity)."""
        t = task.lower()
        hints = hints or {}

        domain = TaskDomain.REASONING
        # Check more-specific domains before general ones to avoid substring false-positives
        _SYNTHESIS_WORDS = ("summarise", "summarize", "synthesize", "combine", "merge", "integrate")
        _PLANNING_WORDS = ("roadmap", "strategy", "schedule", "decompose", "break down", "sprint")
        if any(w in t for w in ("code", "implement", "function", "bug", "debug", "refactor")):
            domain = TaskDomain.CODING
        elif any(w in t for w in _SYNTHESIS_WORDS):
            domain = TaskDomain.SYNTHESIS
        elif any(w in t for w in ("coordinate", "delegate", "orchestrate", "spawn")):
            domain = TaskDomain.COORDINATION
        elif any(w in t for w in ("validate", "verify", "audit", "assess")):
            domain = TaskDomain.VALIDATION
        elif any(w in t for w in _PLANNING_WORDS):
            domain = TaskDomain.PLANNING
        elif any(w in t for w in ("invent", "brainstorm", "novel idea", "creative")):
            domain = TaskDomain.CREATIVITY
        elif any(w in t for w in ("research", "find", "search", "look up", "discover", "crawl")):
            domain = TaskDomain.RESEARCH

        if "complexity" in hints:
            try:
                return domain, TaskComplexity(hints["complexity"])
            except ValueError:
                pass

        words = len(task.split())
        clauses = task.count(",") + task.count(";") + t.count(" and ")

        if words < 8 and clauses == 0:
            complexity = TaskComplexity.TRIVIAL
        elif words < 20 and clauses <= 1:
            complexity = TaskComplexity.SIMPLE
        elif words < 50 and clauses <= 3:
            complexity = TaskComplexity.MODERATE
        elif any(w in t for w in ("critical", "production", "must not fail", "urgent")):
            complexity = TaskComplexity.CRITICAL
        else:
            complexity = TaskComplexity.COMPLEX

        return domain, complexity

    def route(self, task: str, task_id: str = "", hints: dict | None = None) -> RouteDecision:
        """Return the optimal RouteDecision for this task."""
        domain, complexity = self.classify(task, hints)
        pattern = _ROUTING_TABLE.get((domain, complexity), "ReAct")
        agent_type = _AGENT_TABLE.get(domain, "digital_worker")
        via = "static"

        # Adaptive escalation: if this pattern has been failing recently
        recent = self._pattern_outcomes.get(pattern, [])[-20:]
        if recent and (sum(recent) / len(recent)) < 0.5:
            pattern = _ESCALATION_MAP.get(pattern, "Reflection")
            via = "escalated"

        confidence = 0.9 if (domain, complexity) in _ROUTING_TABLE else 0.6
        return RouteDecision(
            pattern=pattern,
            agent_type=agent_type,
            complexity=complexity,
            domain=domain,
            rationale=f"{domain.value}/{complexity.value} → {pattern} ({via})",
            confidence=confidence,
        )

    def record_outcome(
        self,
        task_id: str,
        decision: RouteDecision,
        outcome: str,
        latency_ms: float = 0.0,
        tokens_used: int = 0,
    ) -> None:
        """Feed back execution result for adaptive learning."""
        self._history.append(
            RoutingRecord(
                task_id=task_id,
                decision=decision,
                outcome=outcome,
                latency_ms=latency_ms,
                tokens_used=tokens_used,
            )
        )
        if len(self._history) > 1000:
            self._history = self._history[-1000:]

        bucket = self._pattern_outcomes.setdefault(decision.pattern, [])
        bucket.append(outcome == "success")
        if len(bucket) > 100:
            self._pattern_outcomes[decision.pattern] = bucket[-100:]

    def stats(self) -> dict:
        pattern_perf = {}
        for p, outcomes in self._pattern_outcomes.items():
            pattern_perf[p] = {
                "success_rate": round(sum(outcomes) / len(outcomes), 3),
                "calls": len(outcomes),
            }
        return {"total_routed": len(self._history), "pattern_performance": pattern_perf}
