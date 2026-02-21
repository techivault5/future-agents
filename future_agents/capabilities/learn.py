"""Learning engine — agents can learn from experience and evolve.

The learning system enables agents to:
  - **Remember** — Build episodic and semantic memory from executions
  - **Detect patterns** — Identify recurring successes, failures, and behaviors
  - **Evolve skills** — Propose changes to their own skill definitions
  - **Absorb teachings** — Integrate knowledge shared by other agents
  - **Self-improve** — Update confidence, strategies, and approaches

Learning is per-agent — each agent has its own memory and learning
context. The Master Agent can aggregate and cross-pollinate learnings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from future_agents.capabilities.speech import Utterance, SpeechType

logger = logging.getLogger(__name__)


# ── Memory Models ────────────────────────────────────────────────


class MemoryType(str, Enum):
    EPISODIC = "episodic"  # Specific execution events
    SEMANTIC = "semantic"  # General knowledge/rules learned
    PROCEDURAL = "procedural"  # How to do things (strategies)
    TEACHING = "teaching"  # Knowledge received from other agents


@dataclass
class Memory:
    """A single memory entry — something the agent learned."""

    id: str = field(default_factory=lambda: uuid4().hex[:12])
    memory_type: MemoryType = MemoryType.EPISODIC
    topic: str = ""
    content: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    source: str = ""  # Where this came from (task_id, agent_id, etc.)
    confidence: float = 1.0
    access_count: int = 0
    reinforcement_count: int = 0  # How many times this was confirmed
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_accessed: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tags: list[str] = field(default_factory=list)

    def reinforce(self, boost: float = 0.05) -> None:
        """Strengthen this memory — seen again / confirmed."""
        self.reinforcement_count += 1
        self.confidence = min(1.0, self.confidence + boost)
        self.last_accessed = datetime.now(timezone.utc)

    def decay(self, amount: float = 0.01) -> None:
        """Weaken this memory over time if not accessed."""
        self.confidence = max(0.0, self.confidence - amount)

    def access(self) -> None:
        self.access_count += 1
        self.last_accessed = datetime.now(timezone.utc)


class InsightType(str, Enum):
    SUCCESS_PATTERN = "success_pattern"
    FAILURE_PATTERN = "failure_pattern"
    SKILL_GAP = "skill_gap"
    STRATEGY_LEARNED = "strategy_learned"
    TEACHING_ABSORBED = "teaching_absorbed"
    CORRELATION = "correlation"


@dataclass
class Insight:
    """A higher-order learning — a pattern or conclusion derived from memories."""

    id: str = field(default_factory=lambda: uuid4().hex[:12])
    insight_type: InsightType = InsightType.SUCCESS_PATTERN
    title: str = ""
    description: str = ""
    evidence: list[str] = field(default_factory=list)  # Memory IDs
    confidence: float = 0.5
    actionable: bool = False
    suggested_action: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    applied: bool = False


@dataclass
class SkillEvolution:
    """A proposed change to an agent's skill based on learning."""

    id: str = field(default_factory=lambda: uuid4().hex[:12])
    skill_intent: str = ""
    change_type: str = ""  # "level_up", "new_strategy", "new_constraint", "deprecate"
    description: str = ""
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.5
    status: str = "proposed"  # proposed, approved, applied, rejected
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ── Agent Memory Store ───────────────────────────────────────────


class AgentMemory:
    """Per-agent memory store with episodic, semantic, and procedural memory.

    Each agent has its own memory that accumulates over time.
    Memory decays if not reinforced, and strong memories drive insights.
    """

    def __init__(self, agent_id: str, max_memories: int = 2000) -> None:
        self.agent_id = agent_id
        self._memories: dict[str, Memory] = {}
        self._max_memories = max_memories

    def remember(
        self,
        content: str,
        memory_type: MemoryType = MemoryType.EPISODIC,
        topic: str = "",
        source: str = "",
        confidence: float = 1.0,
        context: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> Memory:
        """Store a new memory."""
        # Check for similar existing memories to reinforce
        for mem in self._memories.values():
            if mem.topic == topic and mem.content == content and mem.memory_type == memory_type:
                mem.reinforce()
                return mem

        memory = Memory(
            memory_type=memory_type,
            topic=topic,
            content=content,
            source=source,
            confidence=confidence,
            context=context or {},
            tags=tags or [],
        )
        self._memories[memory.id] = memory

        # Evict lowest-confidence memories if over limit
        if len(self._memories) > self._max_memories:
            weakest = min(self._memories.values(), key=lambda m: m.confidence)
            del self._memories[weakest.id]

        return memory

    def recall(
        self,
        topic: str = "",
        memory_type: MemoryType | None = None,
        min_confidence: float = 0.0,
        limit: int = 20,
        tags: list[str] | None = None,
    ) -> list[Memory]:
        """Recall memories matching criteria, sorted by relevance."""
        results: list[Memory] = []
        for mem in self._memories.values():
            if mem.confidence < min_confidence:
                continue
            if memory_type and mem.memory_type != memory_type:
                continue
            if topic and topic.lower() not in mem.topic.lower() and topic.lower() not in mem.content.lower():
                continue
            if tags and not any(t in mem.tags for t in tags):
                continue
            mem.access()
            results.append(mem)

        # Sort by confidence * reinforcement (most reliable first)
        results.sort(key=lambda m: (m.confidence, m.reinforcement_count), reverse=True)
        return results[:limit]

    def forget_weak(self, threshold: float = 0.1) -> int:
        """Remove memories below a confidence threshold."""
        to_remove = [mid for mid, m in self._memories.items() if m.confidence < threshold]
        for mid in to_remove:
            del self._memories[mid]
        return len(to_remove)

    def decay_all(self, amount: float = 0.005) -> None:
        """Apply decay to all memories (call periodically)."""
        for mem in self._memories.values():
            mem.decay(amount)

    @property
    def size(self) -> int:
        return len(self._memories)

    def by_type(self, memory_type: MemoryType) -> list[Memory]:
        return [m for m in self._memories.values() if m.memory_type == memory_type]

    def strongest(self, limit: int = 10) -> list[Memory]:
        return sorted(self._memories.values(), key=lambda m: m.confidence, reverse=True)[:limit]

    def stats(self) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        total_confidence = 0.0
        for m in self._memories.values():
            by_type[m.memory_type.value] = by_type.get(m.memory_type.value, 0) + 1
            total_confidence += m.confidence
        return {
            "total_memories": len(self._memories),
            "by_type": by_type,
            "avg_confidence": total_confidence / len(self._memories) if self._memories else 0,
        }


# ── Learning Engine ──────────────────────────────────────────────


class LearningEngine:
    """Per-agent learning engine that analyzes memory and produces insights.

    The learning cycle:
      1. Record experiences (from executions, speech, teachings)
      2. Analyze patterns across memories
      3. Generate insights (success patterns, failure patterns, gaps)
      4. Propose skill evolutions
      5. Apply learnings (update agent behavior)
    """

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        self.memory = AgentMemory(agent_id)
        self._insights: list[Insight] = []
        self._evolutions: list[SkillEvolution] = []

    # ── Record ───────────────────────────────────────────────────

    def record_execution(
        self,
        intent: str,
        success: bool,
        duration_ms: float,
        context: dict[str, Any] | None = None,
        errors: list[str] | None = None,
    ) -> Memory:
        """Record an execution outcome into episodic memory."""
        outcome_str = "succeeded" if success else "failed"
        content = f"Task '{intent}' {outcome_str} in {duration_ms:.0f}ms"
        if errors:
            content += f". Errors: {'; '.join(errors[:3])}"

        return self.memory.remember(
            content=content,
            memory_type=MemoryType.EPISODIC,
            topic=intent,
            source="execution",
            confidence=1.0,
            context={
                "intent": intent,
                "success": success,
                "duration_ms": duration_ms,
                **(context or {}),
                "errors": errors or [],
            },
            tags=["execution", "success" if success else "failure", intent.split(".")[0]],
        )

    def record_teaching(self, utterance: Utterance) -> Memory:
        """Absorb a teaching from another agent."""
        return self.memory.remember(
            content=utterance.text,
            memory_type=MemoryType.TEACHING,
            topic=utterance.topic,
            source=utterance.speaker,
            confidence=utterance.confidence,
            context=utterance.content,
            tags=["teaching", *utterance.tags],
        )

    def record_strategy(
        self, strategy: str, topic: str, confidence: float = 0.7
    ) -> Memory:
        """Record a procedural memory — how to do something."""
        return self.memory.remember(
            content=strategy,
            memory_type=MemoryType.PROCEDURAL,
            topic=topic,
            source="self",
            confidence=confidence,
            tags=["strategy", topic.split(".")[0] if "." in topic else topic],
        )

    def record_knowledge(
        self, fact: str, topic: str, confidence: float = 0.8, tags: list[str] | None = None,
    ) -> Memory:
        """Record a semantic memory — a general fact or rule."""
        return self.memory.remember(
            content=fact,
            memory_type=MemoryType.SEMANTIC,
            topic=topic,
            source="self",
            confidence=confidence,
            tags=tags or [],
        )

    # ── Analyze ──────────────────────────────────────────────────

    def analyze(self) -> list[Insight]:
        """Analyze all memories and generate new insights."""
        new_insights: list[Insight] = []

        new_insights.extend(self._detect_success_patterns())
        new_insights.extend(self._detect_failure_patterns())
        new_insights.extend(self._detect_teaching_insights())

        self._insights.extend(new_insights)
        return new_insights

    def _detect_success_patterns(self) -> list[Insight]:
        """Find recurring success patterns."""
        insights: list[Insight] = []
        successes = self.memory.recall(tags=["success"], limit=100)

        # Group by intent/topic
        by_topic: dict[str, list[Memory]] = {}
        for mem in successes:
            topic = mem.context.get("intent", mem.topic)
            by_topic.setdefault(topic, []).append(mem)

        for topic, memories in by_topic.items():
            if len(memories) >= 3:
                avg_duration = sum(
                    m.context.get("duration_ms", 0) for m in memories
                ) / len(memories)
                insights.append(Insight(
                    insight_type=InsightType.SUCCESS_PATTERN,
                    title=f"Strong at: {topic}",
                    description=(
                        f"Consistently succeeds at '{topic}' "
                        f"({len(memories)} successes, avg {avg_duration:.0f}ms)"
                    ),
                    evidence=[m.id for m in memories[:5]],
                    confidence=min(1.0, len(memories) / 10),
                ))

        return insights

    def _detect_failure_patterns(self) -> list[Insight]:
        """Find recurring failure patterns."""
        insights: list[Insight] = []
        failures = self.memory.recall(tags=["failure"], limit=100)

        by_topic: dict[str, list[Memory]] = {}
        for mem in failures:
            topic = mem.context.get("intent", mem.topic)
            by_topic.setdefault(topic, []).append(mem)

        for topic, memories in by_topic.items():
            if len(memories) >= 2:
                # Collect common error patterns
                all_errors: list[str] = []
                for m in memories:
                    all_errors.extend(m.context.get("errors", []))

                insights.append(Insight(
                    insight_type=InsightType.FAILURE_PATTERN,
                    title=f"Struggling with: {topic}",
                    description=(
                        f"Recurring failures on '{topic}' ({len(memories)} failures). "
                        f"Common errors: {'; '.join(list(set(all_errors))[:3]) or 'unknown'}"
                    ),
                    evidence=[m.id for m in memories[:5]],
                    confidence=min(1.0, len(memories) / 5),
                    actionable=True,
                    suggested_action=f"Review and improve handling of '{topic}'",
                ))

        return insights

    def _detect_teaching_insights(self) -> list[Insight]:
        """Convert absorbed teachings into insights."""
        insights: list[Insight] = []
        teachings = self.memory.by_type(MemoryType.TEACHING)

        for teaching in teachings:
            if teaching.confidence >= 0.6 and teaching.reinforcement_count == 0:
                insights.append(Insight(
                    insight_type=InsightType.TEACHING_ABSORBED,
                    title=f"Learned from {teaching.source}: {teaching.topic}",
                    description=teaching.content,
                    evidence=[teaching.id],
                    confidence=teaching.confidence,
                    actionable=True,
                    suggested_action=f"Apply teaching about '{teaching.topic}' to improve performance",
                ))
                teaching.reinforce(0.0)  # Mark as processed

        return insights

    # ── Evolve ───────────────────────────────────────────────────

    def propose_evolutions(self) -> list[SkillEvolution]:
        """Based on insights, propose changes to agent skills."""
        evolutions: list[SkillEvolution] = []

        for insight in self._insights:
            if insight.applied:
                continue

            if insight.insight_type == InsightType.SUCCESS_PATTERN and insight.confidence >= 0.7:
                topic = insight.title.replace("Strong at: ", "")
                evolutions.append(SkillEvolution(
                    skill_intent=topic,
                    change_type="level_up",
                    description=f"Consistently succeeds at {topic} — consider leveling up",
                    evidence=insight.evidence,
                    confidence=insight.confidence,
                ))

            elif insight.insight_type == InsightType.FAILURE_PATTERN:
                topic = insight.title.replace("Struggling with: ", "")
                evolutions.append(SkillEvolution(
                    skill_intent=topic,
                    change_type="new_strategy",
                    description=f"Needs new strategy for {topic}: {insight.description}",
                    evidence=insight.evidence,
                    confidence=insight.confidence,
                ))

            elif insight.insight_type == InsightType.TEACHING_ABSORBED:
                evolutions.append(SkillEvolution(
                    skill_intent=insight.title.split(": ")[-1] if ": " in insight.title else "",
                    change_type="new_strategy",
                    description=f"Apply teaching: {insight.description}",
                    evidence=insight.evidence,
                    confidence=insight.confidence,
                ))

        self._evolutions.extend(evolutions)
        return evolutions

    # ── Full learning cycle ──────────────────────────────────────

    def learn(self) -> dict[str, Any]:
        """Run one full learning cycle: analyze, generate insights, propose evolutions."""
        # Decay old memories slightly
        self.memory.decay_all(0.002)
        self.memory.forget_weak(0.05)

        # Analyze and generate insights
        new_insights = self.analyze()

        # Propose evolutions
        new_evolutions = self.propose_evolutions()

        return {
            "agent_id": self.agent_id,
            "memories": self.memory.size,
            "new_insights": len(new_insights),
            "total_insights": len(self._insights),
            "new_evolutions": len(new_evolutions),
            "total_evolutions": len(self._evolutions),
            "memory_stats": self.memory.stats(),
        }

    @property
    def insights(self) -> list[Insight]:
        return list(self._insights)

    @property
    def evolutions(self) -> list[SkillEvolution]:
        return list(self._evolutions)


# ── Learn Mixin ──────────────────────────────────────────────────


class LearnMixin:
    """Mixin that gives any agent the ability to learn and improve.

    Add to an agent class:
        class MyAgent(BaseAgent, SpeechMixin, ListenMixin, LearnMixin):
            ...

    Then learning happens automatically as the agent executes tasks
    and receives teachings. Call self.learn_cycle() to trigger analysis.
    """

    _learning_engine: LearningEngine | None = None

    def init_learning(self) -> None:
        """Initialize the learning engine. Call from agent's initialize()."""
        agent_id = getattr(self, "agent_id", "unknown")
        self._learning_engine = LearningEngine(agent_id)

    @property
    def learning(self) -> LearningEngine:
        if self._learning_engine is None:
            self.init_learning()
        return self._learning_engine  # type: ignore[return-value]

    def remember_execution(
        self,
        intent: str,
        success: bool,
        duration_ms: float,
        context: dict[str, Any] | None = None,
        errors: list[str] | None = None,
    ) -> Memory:
        """Record a task execution into memory."""
        return self.learning.record_execution(intent, success, duration_ms, context, errors)

    def absorb_teaching(self, utterance: Utterance) -> Memory:
        """Absorb a teaching from another agent."""
        return self.learning.record_teaching(utterance)

    def learn_strategy(self, strategy: str, topic: str, confidence: float = 0.7) -> Memory:
        """Record a learned strategy for a task type."""
        return self.learning.record_strategy(strategy, topic, confidence)

    def learn_fact(self, fact: str, topic: str, confidence: float = 0.8) -> Memory:
        """Record a learned fact or rule."""
        return self.learning.record_knowledge(fact, topic, confidence)

    def learn_cycle(self) -> dict[str, Any]:
        """Run one learning cycle — analyze memories and propose improvements."""
        return self.learning.learn()

    def recall(
        self, topic: str = "", min_confidence: float = 0.3, limit: int = 10
    ) -> list[Memory]:
        """Recall relevant memories."""
        return self.learning.memory.recall(topic=topic, min_confidence=min_confidence, limit=limit)

    def get_insights(self) -> list[Insight]:
        return self.learning.insights

    def get_evolutions(self) -> list[SkillEvolution]:
        return self.learning.evolutions
