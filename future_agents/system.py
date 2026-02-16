"""System — factory that wires everything together into a running system."""

from __future__ import annotations

from future_agents.agents.capability_agent import CapabilityAgent
from future_agents.agents.knowledge_agent import KnowledgeAgent
from future_agents.agents.policy_agent import PolicyAgent
from future_agents.agents.process_agent import ProcessAgent
from future_agents.agents.skills_agent import SkillsAgent
from future_agents.core.events import EventBus
from future_agents.core.orchestrator import Orchestrator
from future_agents.core.registry import AgentRegistry
from future_agents.infrastructure.knowledge_store import KnowledgeStore
from future_agents.infrastructure.metric_tracker import MetricTracker
from future_agents.infrastructure.sync_engine import SyncEngine


class AgentSystem:
    """Top-level container that wires all components together.

    Usage:
        system = AgentSystem()
        await system.start()

        result = await system.handle("capability.register", {
            "name": "Python Development",
            "domain": "engineering",
        })

        health = await system.health()
        await system.run_sync_cycle()
        await system.stop()
    """

    def __init__(self) -> None:
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

        # Orchestrator (task routing + planning)
        self.orchestrator = Orchestrator(
            registry=self.registry,
            sync_engine=self.sync_engine,
            metrics=self.metrics,
            event_bus=self.event_bus,
        )

        # Domain agents
        self._capability_agent = CapabilityAgent()
        self._process_agent = ProcessAgent()
        self._policy_agent = PolicyAgent()
        self._skills_agent = SkillsAgent()
        self._knowledge_agent = KnowledgeAgent(knowledge_store=self.knowledge_store)

    async def start(self) -> None:
        """Initialize and register all agents."""
        await self.registry.register(self._capability_agent)
        await self.registry.register(self._process_agent)
        await self.registry.register(self._policy_agent)
        await self.registry.register(self._skills_agent)
        await self.registry.register(self._knowledge_agent)

    async def stop(self) -> None:
        """Shut down all agents and stop the sync engine."""
        self.sync_engine.stop()
        for agent_id in list(self.registry.agents.keys()):
            await self.registry.deregister(agent_id)

    async def handle(self, intent: str, parameters: dict | None = None) -> dict:
        """Execute a task through the orchestrator. Returns result data."""
        result = await self.orchestrator.handle(intent, parameters)
        return {
            "task_id": result.task_id,
            "outcome": result.outcome.value,
            "data": result.data,
            "errors": result.errors,
            "suggestions": result.suggestions,
            "duration_ms": result.duration_ms,
        }

    async def run_sync_cycle(self) -> dict:
        """Manually trigger one improvement cycle."""
        return await self.sync_engine.run_cycle()

    async def health(self) -> dict:
        """Get system-wide health report."""
        return await self.orchestrator.system_health()
