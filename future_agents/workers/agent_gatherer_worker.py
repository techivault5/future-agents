"""Agent Gatherer Worker — discovers capability gaps and generates skeleton definitions."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from future_agents.core.events import Event, EventBus
from future_agents.core.registry import AgentRegistry
from future_agents.definitions.factory import AgentFactory
from future_agents.infrastructure.knowledge_store import KnowledgeStore
from future_agents.infrastructure.metric_tracker import MetricTracker
from future_agents.infrastructure.sync_engine import Improvement, ImprovementType, SyncEngine
from future_agents.models.knowledge import KnowledgeEntry
from future_agents.workers.base_worker import BaseWorker, WorkerResult

logger = logging.getLogger(__name__)

# Domains we want the system to cover
_TARGET_DOMAINS: dict[str, dict] = {
    "monitoring": {
        "description": "Health monitoring, alerting, and metrics collection",
        "intents": ["monitoring.health", "monitoring.alert", "monitoring.metrics"],
        "importance": 0.9,
    },
    "security": {
        "description": "Security auditing, scanning, and policy enforcement",
        "intents": ["security.audit", "security.scan", "security.policy"],
        "importance": 0.9,
    },
    "data": {
        "description": "Data transformation, validation, and pipeline management",
        "intents": ["data.transform", "data.validate", "data.pipeline"],
        "importance": 0.8,
    },
    "notification": {
        "description": "Multi-channel notification routing and escalation",
        "intents": ["notification.send", "notification.route", "notification.escalate"],
        "importance": 0.6,
    },
    "analytics": {
        "description": "Reporting, querying, and data aggregation",
        "intents": ["analytics.report", "analytics.query", "analytics.aggregate"],
        "importance": 0.6,
    },
    "scheduler": {
        "description": "Task scheduling, planning, and execution tracking",
        "intents": ["scheduler.plan", "scheduler.execute", "scheduler.status"],
        "importance": 0.55,
    },
}


class AgentGathererWorker(BaseWorker):
    """Discovers capability gaps and auto-generates skeleton agent definitions.

    Each cycle:
    1. Scans the definitions directory for new JSON files not yet registered.
    2. Loads and registers any new definitions found.
    3. Compares registered capabilities against target domains → finds gaps.
    4. Generates skeleton definition JSONs for the highest-priority gaps.
    5. Records the current agent landscape in the KnowledgeStore.
    6. Emits a ``worker.agent_gatherer.cycle_complete`` event.
    """

    def __init__(
        self,
        registry: AgentRegistry,
        factory: AgentFactory,
        sync_engine: SyncEngine,
        knowledge_store: KnowledgeStore,
        metrics: MetricTracker,
        event_bus: EventBus,
        definitions_dir: Path | str = "agents",
        interval_seconds: int = 900,
        **kwargs: Any,
    ) -> None:
        super().__init__(interval_seconds=interval_seconds, **kwargs)
        self.registry = registry
        self.factory = factory
        self.sync_engine = sync_engine
        self.knowledge_store = knowledge_store
        self.metrics = metrics
        self.event_bus = event_bus
        self.definitions_dir = Path(definitions_dir)
        self._known_files: set[str] = set()

    @property
    def worker_type(self) -> str:
        return "agent_gatherer"

    async def on_start(self) -> None:
        if self.definitions_dir.exists():
            self._known_files = {f.name for f in self.definitions_dir.glob("*.json")}

    async def run(self) -> WorkerResult:
        new_loaded = gaps_found = skeletons_created = 0

        for def_file in self._new_definition_files():
            if await self._load_definition(def_file):
                self._known_files.add(def_file.name)
                new_loaded += 1

        gaps = self._coverage_gaps()
        gaps_found = len(gaps)
        for gap in gaps:
            self._propose_gap(gap)

        for gap in sorted(gaps, key=lambda g: -g["importance"])[:2]:
            if self._generate_skeleton(gap):
                skeletons_created += 1

        self._record_landscape()

        await self.event_bus.emit(Event(
            type="worker.agent_gatherer.cycle_complete",
            source=self.worker_id,
            data={
                "new_agents_loaded": new_loaded,
                "gaps_found": gaps_found,
                "skeletons_created": skeletons_created,
            },
        ))
        self.metrics.increment("workers.agent_gatherer.runs")

        return WorkerResult(
            worker_id=self.worker_id,
            success=True,
            data={
                "new_agents_loaded": new_loaded,
                "gaps_found": gaps_found,
                "skeletons_created": skeletons_created,
                "registered_agents": len(self.registry.agents),
            },
        )

    # ── Private ───────────────────────────────────────────────────────────────

    def _new_definition_files(self) -> list[Path]:
        if not self.definitions_dir.exists():
            return []
        return [
            f for f in self.definitions_dir.glob("*.json")
            if f.name not in self._known_files
        ]

    async def _load_definition(self, def_file: Path) -> bool:
        try:
            agents = self.factory.build_from_file(def_file)
            # build_from_file returns a single DefinedAgent, not a list
            if hasattr(agents, "agent_id"):
                agents = [agents]
            for agent in agents:
                if agent.agent_id not in self.registry.agents:
                    await self.registry.register(agent)
                    logger.info("Auto-loaded new agent: %s from %s", agent.agent_id, def_file.name)
            return True
        except Exception as exc:
            logger.warning("Could not load %s: %s", def_file.name, exc)
            return False

    def _coverage_gaps(self) -> list[dict]:
        covered_domains = {a.agent_type for a in self.registry.agents.values()}
        seen: set[str] = set()
        gaps = []
        for domain, info in _TARGET_DOMAINS.items():
            if domain not in covered_domains and domain not in seen:
                seen.add(domain)
                gaps.append({"domain": domain, **info})
        return gaps

    def _propose_gap(self, gap: dict) -> None:
        title = f"Missing agent domain: {gap['domain']}"
        if any(i.title == title for i in self.sync_engine.improvements):
            return
        self.sync_engine._improvements.append(Improvement(
            type=ImprovementType.CAPABILITY_GAP,
            title=title,
            description=(
                f"No agent covers '{gap['domain']}' intents "
                f"(e.g. {gap['intents'][0]}). "
                f"Create a {gap['domain'].capitalize()}Agent."
            ),
            priority=gap["importance"],
            evidence=[f"example={gap['intents'][0]}"],
        ))

    def _generate_skeleton(self, gap: dict) -> bool:
        out = self.definitions_dir / f"{gap['domain']}.json"
        if out.exists():
            return False
        skeleton = {
            "id": f"{gap['domain']}_agent",
            "name": f"{gap['domain'].capitalize()} Agent",
            "type": gap["domain"],
            "version": "0.1.0",
            "description": gap["description"],
            "skills": [
                {
                    "name": intent.replace(".", "_"),
                    "description": f"Handles {intent} operations",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "target": {"type": "string"},
                            "options": {"type": "object"},
                        },
                        "required": ["target"],
                    },
                    "output_schema": {"type": "object"},
                }
                for intent in gap["intents"]
            ],
            "constraints": {"max_concurrent_tasks": 5, "timeout_seconds": 30},
            "metadata": {
                "auto_generated": True,
                "status": "skeleton",
                "importance": gap["importance"],
            },
        }
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(skeleton, indent=2) + "\n")
            logger.info("Generated skeleton: %s", out.name)
            self.knowledge_store.add(KnowledgeEntry(
                title=f"Skeleton Generated: {gap['domain'].capitalize()}Agent",
                domain="agents",
                content=(
                    f"Skeleton definition created at {out}. "
                    f"Needs Python implementation for: "
                    f"{', '.join(s['name'] for s in skeleton['skills'][:3])}."
                ),
                tags=["agent", "skeleton", gap["domain"], "needs-implementation"],
                source_agent=self.worker_id,
                confidence=0.7,
            ))
            return True
        except OSError as exc:
            logger.warning("Failed to write skeleton for %s: %s", gap["domain"], exc)
            return False

    def _record_landscape(self) -> None:
        agents = self.registry.agents
        all_types = list({a.agent_type for a in agents.values()})
        all_caps: list[str] = []
        for a in agents.values():
            all_caps.extend(a.capabilities)
        self.knowledge_store.add(KnowledgeEntry(
            title="Current Agent Landscape",
            domain="system",
            content=(
                f"{len(agents)} agents registered covering {len(all_caps)} capabilities: "
                f"{', '.join(sorted(all_types))}."
            ),
            tags=["agents", "landscape", "registry"],
            source_agent=self.worker_id,
            confidence=1.0,
        ))
