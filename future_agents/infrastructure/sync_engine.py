"""Sync Engine — the continuous self-improvement loop.

This is the heart of the system's ability to learn and improve.
It periodically:
1. Collects feedback from recent executions
2. Analyzes patterns and identifies gaps
3. Proposes improvements to knowledge, capabilities, and processes
4. Applies approved improvements
5. Syncs changes across all agents
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from future_agents.core.base_agent import BaseAgent
from future_agents.core.events import Event, EventBus
from future_agents.core.registry import AgentRegistry
from future_agents.infrastructure.knowledge_store import KnowledgeStore
from future_agents.infrastructure.metric_tracker import MetricTracker
from future_agents.models.feedback import ExecutionOutcome, Feedback

logger = logging.getLogger(__name__)


class ImprovementType(str, Enum):
    KNOWLEDGE_UPDATE = "knowledge_update"
    CAPABILITY_GAP = "capability_gap"
    PROCESS_OPTIMIZATION = "process_optimization"
    POLICY_REFINEMENT = "policy_refinement"
    SKILL_DEVELOPMENT = "skill_development"


@dataclass
class Improvement:
    """A proposed improvement identified by the sync engine."""

    type: ImprovementType
    title: str
    description: str
    target_agent: str | None = None
    priority: float = 0.5  # 0.0 to 1.0
    evidence: list[str] = field(default_factory=list)
    status: str = "proposed"  # proposed, approved, applied, rejected
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SyncEngine:
    """Continuous improvement engine that analyzes feedback and drives evolution.

    The sync loop:
        1. Gather feedback from all agents
        2. Analyze for patterns (recurring failures, low scores, violations)
        3. Identify improvement opportunities
        4. Apply improvements to knowledge store and agent configs
        5. Notify agents of changes via event bus
    """

    def __init__(
        self,
        registry: AgentRegistry,
        knowledge_store: KnowledgeStore,
        metrics: MetricTracker,
        event_bus: EventBus,
    ) -> None:
        self.registry = registry
        self.knowledge_store = knowledge_store
        self.metrics = metrics
        self.event_bus = event_bus
        self._feedback_buffer: list[Feedback] = []
        self._improvements: list[Improvement] = []
        self._running = False
        self._sync_interval = 60  # seconds

    @property
    def improvements(self) -> list[Improvement]:
        return list(self._improvements)

    def add_feedback(self, feedback: Feedback) -> None:
        """Buffer feedback for the next analysis cycle."""
        self._feedback_buffer.append(feedback)
        self.metrics.increment("sync.feedback_received")
        self.metrics.record(
            "sync.feedback_scores",
            feedback.score,
            labels={"agent": feedback.agent_id},
        )

    async def analyze(self) -> list[Improvement]:
        """Analyze buffered feedback and generate improvement proposals.

        This is the core intelligence of the system. In a production setup,
        you'd integrate an LLM here for deeper analysis.
        """
        if not self._feedback_buffer:
            return []

        improvements: list[Improvement] = []
        feedback = self._feedback_buffer
        self._feedback_buffer = []

        # --- Analysis 1: Identify agents with low success rates ---
        agent_scores: dict[str, list[float]] = {}
        for fb in feedback:
            agent_scores.setdefault(fb.agent_id, []).append(fb.score)

        for agent_id, scores in agent_scores.items():
            avg = sum(scores) / len(scores)
            if avg < 0.5 and len(scores) >= 3:
                improvements.append(
                    Improvement(
                        type=ImprovementType.CAPABILITY_GAP,
                        title=f"Low performance: {agent_id}",
                        description=(
                            f"Agent {agent_id} averaged {avg:.2f} over "
                            f"{len(scores)} executions. Needs capability review."
                        ),
                        target_agent=agent_id,
                        priority=1.0 - avg,
                        evidence=[f"avg_score={avg:.2f}", f"sample_size={len(scores)}"],
                    )
                )

        # --- Analysis 2: Identify policy violations ---
        violations = [fb for fb in feedback if fb.has_violations]
        if violations:
            unique_policies = set()
            for fb in violations:
                unique_policies.update(fb.policy_violations)
            improvements.append(
                Improvement(
                    type=ImprovementType.POLICY_REFINEMENT,
                    title="Policy violations detected",
                    description=(
                        f"{len(violations)} tasks had policy violations across "
                        f"policies: {', '.join(unique_policies)}"
                    ),
                    priority=0.9,
                    evidence=[f"violation_count={len(violations)}"],
                )
            )

        # --- Analysis 3: Identify recurring failures ---
        failures = [fb for fb in feedback if fb.outcome == ExecutionOutcome.FAILURE]
        if len(failures) >= 2:
            improvements.append(
                Improvement(
                    type=ImprovementType.PROCESS_OPTIMIZATION,
                    title="Recurring task failures",
                    description=(
                        f"{len(failures)} tasks failed. Review processes and "
                        f"capability assignments."
                    ),
                    priority=0.8,
                    evidence=[fb.details for fb in failures if fb.details],
                )
            )

        # --- Analysis 4: Harvest positive learnings ---
        successes = [fb for fb in feedback if fb.is_positive and fb.suggestions]
        for fb in successes:
            improvements.append(
                Improvement(
                    type=ImprovementType.KNOWLEDGE_UPDATE,
                    title=f"Learning from success: {fb.task_id}",
                    description=f"Suggestions from successful task: {'; '.join(fb.suggestions)}",
                    target_agent=fb.agent_id,
                    priority=0.4,
                    evidence=fb.suggestions,
                )
            )

        self._improvements.extend(improvements)
        self.metrics.increment("sync.improvements_proposed", len(improvements))

        await self.event_bus.emit(
            Event(
                type="sync.analysis_complete",
                source="sync_engine",
                data={"improvement_count": len(improvements)},
            )
        )

        return improvements

    async def apply_improvements(self, auto_apply_below_priority: float = 0.5) -> list[Improvement]:
        """Apply improvements that meet the auto-apply threshold.

        Higher-priority improvements require human approval (returned for review).
        Lower-priority improvements are applied automatically.
        """
        applied: list[Improvement] = []
        needs_review: list[Improvement] = []

        for imp in self._improvements:
            if imp.status != "proposed":
                continue

            if imp.priority <= auto_apply_below_priority:
                imp.status = "applied"
                applied.append(imp)
                self.metrics.increment("sync.improvements_applied")
            else:
                needs_review.append(imp)

        if applied:
            await self.event_bus.emit(
                Event(
                    type="sync.improvements_applied",
                    source="sync_engine",
                    data={
                        "count": len(applied),
                        "types": [i.type.value for i in applied],
                    },
                )
            )

        return needs_review

    async def sync_agents(self) -> None:
        """Notify all agents to refresh their state after improvements."""
        await self.event_bus.emit(
            Event(
                type="sync.refresh",
                source="sync_engine",
                data={"timestamp": datetime.now(timezone.utc).isoformat()},
            )
        )
        self.metrics.increment("sync.refresh_cycles")

    async def run_cycle(self) -> dict[str, Any]:
        """Run one full improvement cycle."""
        improvements = await self.analyze()
        needs_review = await self.apply_improvements()
        await self.sync_agents()

        return {
            "improvements_found": len(improvements),
            "needs_review": len(needs_review),
            "auto_applied": len(improvements) - len(needs_review),
        }

    async def start(self, interval: int | None = None) -> None:
        """Start the continuous sync loop."""
        if interval:
            self._sync_interval = interval
        self._running = True
        logger.info("Sync engine started (interval=%ds)", self._sync_interval)
        while self._running:
            try:
                result = await self.run_cycle()
                logger.info("Sync cycle: %s", result)
            except Exception:
                logger.exception("Sync cycle error")
            await asyncio.sleep(self._sync_interval)

    def stop(self) -> None:
        """Stop the continuous sync loop."""
        self._running = False
        logger.info("Sync engine stopped")
