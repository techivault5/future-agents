"""Pattern Discovery Worker — finds reusable patterns from execution history."""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from future_agents.core.events import Event, EventBus
from future_agents.core.registry import AgentRegistry
from future_agents.infrastructure.knowledge_store import KnowledgeStore
from future_agents.infrastructure.metric_tracker import MetricTracker
from future_agents.infrastructure.sync_engine import Improvement, ImprovementType, SyncEngine
from future_agents.models.knowledge import KnowledgeEntry
from future_agents.workers.base_worker import BaseWorker, WorkerResult

logger = logging.getLogger(__name__)


class PatternDiscoveryWorker(BaseWorker):
    """Identifies reusable patterns and anti-patterns from execution data.

    Each cycle:
    1. Finds agents with consistently high scores → records success patterns.
    2. Finds recurring failure improvements → records anti-patterns.
    3. Identifies high-performing agent types → records capability patterns.
    4. Proposes skill-development improvements for underutilised agents.
    5. Emits a ``worker.pattern_discovery.cycle_complete`` event.

    Patterns are de-duplicated across cycles via an in-memory set.
    """

    def __init__(
        self,
        registry: AgentRegistry,
        sync_engine: SyncEngine,
        knowledge_store: KnowledgeStore,
        metrics: MetricTracker,
        event_bus: EventBus,
        interval_seconds: int = 600,
        **kwargs: Any,
    ) -> None:
        super().__init__(interval_seconds=interval_seconds, **kwargs)
        self.registry = registry
        self.sync_engine = sync_engine
        self.knowledge_store = knowledge_store
        self.metrics = metrics
        self.event_bus = event_bus
        self._seen: set[str] = set()   # dedup across cycles

    @property
    def worker_type(self) -> str:
        return "pattern_discovery"

    async def run(self) -> WorkerResult:
        patterns = anti_patterns = skill_proposals = 0

        for p in self._success_patterns():
            if p["key"] not in self._seen:
                self._record_pattern(p)
                self._seen.add(p["key"])
                patterns += 1

        for p in self._anti_patterns():
            if p["key"] not in self._seen:
                self._record_anti_pattern(p)
                self._seen.add(p["key"])
                anti_patterns += 1

        for p in self._capability_patterns():
            if p["key"] not in self._seen:
                self._record_capability_pattern(p)
                self._seen.add(p["key"])
                patterns += 1

        skill_proposals = self._propose_skill_development()

        await self.event_bus.emit(Event(
            type="worker.pattern_discovery.cycle_complete",
            source=self.worker_id,
            data={
                "patterns_found": patterns,
                "anti_patterns_found": anti_patterns,
                "skill_proposals": skill_proposals,
                "total_known": len(self._seen),
            },
        ))
        self.metrics.increment("workers.pattern_discovery.runs")
        self.metrics.increment("workers.pattern_discovery.patterns_found", float(patterns))

        return WorkerResult(
            worker_id=self.worker_id,
            success=True,
            data={
                "patterns_found": patterns,
                "anti_patterns_found": anti_patterns,
                "skill_proposals": skill_proposals,
                "total_known_patterns": len(self._seen),
            },
        )

    # ── Analysis helpers ──────────────────────────────────────────────────────

    def _success_patterns(self) -> list[dict]:
        results = []
        for key, points in self.metrics._series.items():
            if "feedback_scores" not in key or len(points) < 3:
                continue
            scores = [p.value for p in points]
            avg = sum(scores) / len(scores)
            if avg >= 0.85:
                agent = key.split("agent=")[-1].rstrip("}")
                results.append({
                    "key": f"success_{agent}",
                    "agent": agent,
                    "avg_score": avg,
                    "sample_size": len(scores),
                })
        return results

    def _anti_patterns(self) -> list[dict]:
        titles = [
            i.title for i in self.sync_engine.improvements
            if i.type == ImprovementType.PROCESS_OPTIMIZATION and i.status == "proposed"
        ]
        results = []
        for title, count in Counter(titles).items():
            if count >= 2:
                results.append({
                    "key": f"antipattern_{title[:40].replace(' ', '_')}",
                    "title": title,
                    "count": count,
                })
        return results

    def _capability_patterns(self) -> list[dict]:
        results = []
        for agent_id, agent in self.registry.agents.items():
            if agent._execution_count >= 10 and agent.success_rate >= 0.8:
                results.append({
                    "key": f"capability_{agent_id}",
                    "agent_id": agent_id,
                    "agent_type": agent.agent_type,
                    "executions": agent._execution_count,
                    "success_rate": agent.success_rate,
                    "capabilities": agent.capabilities,
                })
        return results

    def _propose_skill_development(self) -> int:
        count = 0
        existing_titles = {i.title for i in self.sync_engine.improvements}
        for agent in self.registry.agents.values():
            if agent._execution_count < 5 and agent.agent_type != "master":
                title = f"Low utilisation: {agent.agent_type}"
                if title not in existing_titles:
                    self.sync_engine._improvements.append(Improvement(
                        type=ImprovementType.SKILL_DEVELOPMENT,
                        title=title,
                        description=(
                            f"Agent {agent.agent_id} has only {agent._execution_count} "
                            f"executions. Use its capabilities more: "
                            f"{', '.join(agent.capabilities[:3])}"
                        ),
                        target_agent=agent.agent_id,
                        priority=0.3,
                        evidence=[
                            f"executions={agent._execution_count}",
                            f"success_rate={agent.success_rate:.2f}",
                        ],
                    ))
                    count += 1
        return count

    # ── Knowledge recording ───────────────────────────────────────────────────

    def _record_pattern(self, p: dict) -> None:
        self.knowledge_store.add(KnowledgeEntry(
            title=f"Success Pattern: {p['agent']}",
            domain="patterns",
            content=(
                f"Agent '{p['agent']}' is consistently high-performing "
                f"(avg {p['avg_score']:.2f} over {p['sample_size']} runs). "
                f"Good candidate for high-stakes workflows."
            ),
            tags=["pattern", "success", p["agent"]],
            source_agent=self.worker_id,
            confidence=min(1.0, p["avg_score"]),
        ))

    def _record_anti_pattern(self, p: dict) -> None:
        self.knowledge_store.add(KnowledgeEntry(
            title=f"Anti-Pattern: {p['title']}",
            domain="patterns",
            content=(
                f"Recurring failure: '{p['title']}' occurred {p['count']} times. "
                f"Investigate root cause before adding more workload to this path."
            ),
            tags=["anti-pattern", "failure", "review-needed"],
            source_agent=self.worker_id,
            confidence=0.8,
        ))

    def _record_capability_pattern(self, p: dict) -> None:
        caps = ", ".join(p["capabilities"][:5])
        self.knowledge_store.add(KnowledgeEntry(
            title=f"Proven Capability: {p['agent_type']}",
            domain="patterns",
            content=(
                f"Agent type '{p['agent_type']}' is proven: "
                f"{p['executions']} executions at {p['success_rate']:.0%} success. "
                f"Capabilities: {caps}."
            ),
            tags=["pattern", "capability", p["agent_type"]],
            source_agent=self.worker_id,
            confidence=p["success_rate"],
        ))
