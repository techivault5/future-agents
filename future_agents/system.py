"""System — factory that wires everything together into a running system.

Supports two modes:
1. **Definition-driven** (recommended) — Load agent definitions from files,
   construct DefinedAgents via the factory, and route everything through
   the Master Agent.
2. **Legacy** — Register plain Python agent classes directly (still works).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from future_agents.agents.capability_agent import CapabilityAgent
from future_agents.agents.knowledge_agent import KnowledgeAgent
from future_agents.agents.master_agent import MasterAgent
from future_agents.agents.policy_agent import PolicyAgent
from future_agents.agents.process_agent import ProcessAgent
from future_agents.agents.skills_agent import SkillsAgent
from future_agents.core.events import EventBus
from future_agents.core.orchestrator import Orchestrator
from future_agents.core.registry import AgentRegistry
from future_agents.definitions.defined_agent import DefinedAgent
from future_agents.definitions.factory import AgentFactory
from future_agents.infrastructure.knowledge_store import KnowledgeStore
from future_agents.infrastructure.metric_tracker import MetricTracker
from future_agents.infrastructure.sync_engine import SyncEngine
from future_agents.workers.agent_gatherer_worker import AgentGathererWorker
from future_agents.workers.code_improvement_worker import CodeImprovementWorker
from future_agents.workers.pattern_discovery_worker import PatternDiscoveryWorker
from future_agents.workers.scheduler import WorkerScheduler

logger = logging.getLogger(__name__)


class AgentSystem:
    """Top-level container that wires all components together.

    Usage (definition-driven with Master Agent):

        system = AgentSystem(definitions_dir="agents/")
        await system.start()

        # Everything goes through the Master Agent
        result = await system.ask("capability.register", {
            "name": "Python Development",
            "domain": "engineering",
        })

        # Discover all agents
        catalog = await system.discover()

        # Execute a multi-agent workflow
        result = await system.workflow("Onboard new capability", [
            {"intent": "capability.register", "parameters": {...}},
            {"intent": "policy.check", "parameters": {...}},
            {"intent": "knowledge.add", "parameters": {...}},
        ])

        # System health via Master Agent
        status = await system.status()

        await system.stop()
    """

    def __init__(self, definitions_dir: str | Path | None = None) -> None:
        # Shared infrastructure
        self.event_bus = EventBus()
        self.metrics = MetricTracker()
        self.knowledge_store = KnowledgeStore(event_bus=self.event_bus)
        self.registry = AgentRegistry(event_bus=self.event_bus)

        # Sync engine (continuous improvement)
        self.sync_engine = SyncEngine(
            registry=self.registry,
            knowledge_store=self.knowledge_store,
            metrics=self.metrics,
            event_bus=self.event_bus,
        )

        # Legacy orchestrator (still available for direct routing)
        self.orchestrator = Orchestrator(
            registry=self.registry,
            sync_engine=self.sync_engine,
            metrics=self.metrics,
            event_bus=self.event_bus,
        )

        # Agent factory for definition-driven construction
        self.factory = AgentFactory(event_bus=self.event_bus)
        self._register_default_implementations()

        # Master Agent
        self.master = MasterAgent(
            registry=self.registry,
            sync_engine=self.sync_engine,
            metrics=self.metrics,
            event_bus=self.event_bus,
        )

        self._definitions_dir = Path(definitions_dir) if definitions_dir else None
        self._defined_agents: list[DefinedAgent] = []

        # Worker scheduler (continuous improvement loops)
        self.scheduler = WorkerScheduler()
        self._register_default_workers()

    def _register_default_workers(self) -> None:
        """Register the three built-in scheduled workers."""
        source_root = self._definitions_dir.parent if self._definitions_dir else Path(".")
        self.scheduler.register(CodeImprovementWorker(
            sync_engine=self.sync_engine,
            knowledge_store=self.knowledge_store,
            metrics=self.metrics,
            event_bus=self.event_bus,
            source_root=source_root,
            interval_seconds=300,
        ))
        self.scheduler.register(PatternDiscoveryWorker(
            registry=self.registry,
            sync_engine=self.sync_engine,
            knowledge_store=self.knowledge_store,
            metrics=self.metrics,
            event_bus=self.event_bus,
            interval_seconds=600,
        ))
        self.scheduler.register(AgentGathererWorker(
            registry=self.registry,
            factory=self.factory,
            sync_engine=self.sync_engine,
            knowledge_store=self.knowledge_store,
            metrics=self.metrics,
            event_bus=self.event_bus,
            definitions_dir=self._definitions_dir or Path("agents"),
            interval_seconds=900,
        ))

    def _register_default_implementations(self) -> None:
        """Register the built-in implementation classes with the factory."""
        self.factory.register_implementation(
            "capability", lambda **kw: CapabilityAgent(**kw)
        )
        self.factory.register_implementation(
            "process", lambda **kw: ProcessAgent(**kw)
        )
        self.factory.register_implementation(
            "policy", lambda **kw: PolicyAgent(**kw)
        )
        self.factory.register_implementation(
            "skills", lambda **kw: SkillsAgent(**kw)
        )
        self.factory.register_implementation(
            "knowledge",
            lambda **kw: KnowledgeAgent(knowledge_store=self.knowledge_store, **kw),
        )

    async def start(self) -> None:
        """Initialize and register all agents.

        If a definitions directory was provided, loads definitions and
        creates DefinedAgents. Otherwise, registers plain implementations.
        """
        if self._definitions_dir and self._definitions_dir.exists():
            # Definition-driven mode
            self._defined_agents = self.factory.build_from_directory(self._definitions_dir)
            for agent in self._defined_agents:
                await self.registry.register(agent)
            logger.info(
                "Started %d definition-driven agents from %s",
                len(self._defined_agents),
                self._definitions_dir,
            )
        else:
            # Legacy mode — register plain implementations
            await self.registry.register(CapabilityAgent())
            await self.registry.register(ProcessAgent())
            await self.registry.register(PolicyAgent())
            await self.registry.register(SkillsAgent())
            await self.registry.register(KnowledgeAgent(knowledge_store=self.knowledge_store))
            logger.info("Started 5 legacy agents")

        # Register the Master Agent last (so it can discover all others)
        await self.registry.register(self.master)
        logger.info("Master Agent registered — system ready")

        # Start the background worker scheduler
        await self.scheduler.start()
        logger.info("Worker scheduler started")

    async def stop(self) -> None:
        """Shut down workers, agents, and the sync engine."""
        await self.scheduler.stop()
        self.sync_engine.stop()
        for agent_id in list(self.registry.agents.keys()):
            await self.registry.deregister(agent_id)

    # ── Master Agent interface (recommended) ─────────────────────

    async def ask(self, intent: str, parameters: dict | None = None) -> dict:
        """Route any task through the Master Agent."""
        from future_agents.core.base_agent import TaskContext

        context = TaskContext(
            intent="master.route",
            parameters={"intent": intent, "parameters": parameters or {}},
        )
        result = await self.master.execute(context)
        return self._format_result(result)

    async def discover(self, domain: str | None = None) -> dict:
        """Discover all agents via the Master Agent."""
        from future_agents.core.base_agent import TaskContext

        context = TaskContext(
            intent="master.discover",
            parameters={"domain": domain} if domain else {},
        )
        result = await self.master.execute(context)
        return self._format_result(result)

    async def workflow(self, name: str, steps: list[dict[str, Any]]) -> dict:
        """Execute a multi-agent workflow via the Master Agent."""
        from future_agents.core.base_agent import TaskContext

        context = TaskContext(
            intent="master.workflow",
            parameters={"name": name, "steps": steps},
        )
        result = await self.master.execute(context)
        return self._format_result(result)

    async def status(self) -> dict:
        """Get system status via the Master Agent."""
        from future_agents.core.base_agent import TaskContext

        context = TaskContext(intent="master.status", parameters={})
        result = await self.master.execute(context)
        return self._format_result(result)

    # ── Legacy interface (still works) ───────────────────────────

    async def handle(self, intent: str, parameters: dict | None = None) -> dict:
        """Execute a task through the legacy orchestrator."""
        result = await self.orchestrator.handle(intent, parameters)
        return self._format_result(result)

    async def run_sync_cycle(self) -> dict:
        """Manually trigger one improvement cycle."""
        return await self.sync_engine.run_cycle()

    async def health(self) -> dict:
        """Get system-wide health report."""
        return await self.orchestrator.system_health()

    def get_agent_catalog(self) -> str:
        """Get a text catalog of all agents (for prompts/LLM context)."""
        return self.master.build_agent_catalog()

    def worker_status(self) -> dict:
        """Return the current status of all scheduled workers."""
        return self.scheduler.get_status()

    async def run_worker(self, worker_id: str) -> dict | None:
        """Manually trigger one execution of a named worker."""
        result = await self.scheduler.run_now(worker_id)
        if result is None:
            return None
        return {
            "worker_id": result.worker_id,
            "success": result.success,
            "data": result.data,
            "errors": result.errors,
            "duration_ms": result.duration_ms,
        }

    # ── Private ──────────────────────────────────────────────────

    @staticmethod
    def _format_result(result: Any) -> dict:
        return {
            "task_id": result.task_id,
            "outcome": result.outcome.value,
            "data": result.data,
            "errors": result.errors,
            "suggestions": result.suggestions,
            "duration_ms": result.duration_ms,
        }
