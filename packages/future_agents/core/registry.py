"""Agent Registry — manages agent lifecycle and discovery."""

from __future__ import annotations

import logging
from typing import Any

from future_agents.core.base_agent import BaseAgent
from future_agents.core.events import Event, EventBus

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Central registry for all agents in the system.

    Responsibilities:
    - Register / deregister agents
    - Discover agents by type or capability
    - Route tasks to the right agent
    - Track agent health and metrics
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.event_bus = event_bus or EventBus()
        self._agents: dict[str, BaseAgent] = {}
        self._type_index: dict[str, list[str]] = {}  # agent_type -> [agent_id]
        self._capability_index: dict[str, list[str]] = {}  # capability -> [agent_id]

    @property
    def agents(self) -> dict[str, BaseAgent]:
        return dict(self._agents)

    async def register(self, agent: BaseAgent) -> None:
        """Register an agent and initialize it."""
        if agent.agent_id in self._agents:
            raise ValueError(f"Agent {agent.agent_id} already registered")

        # Inject shared event bus
        agent.event_bus = self.event_bus

        self._agents[agent.agent_id] = agent

        # Index by type
        self._type_index.setdefault(agent.agent_type, []).append(agent.agent_id)

        # Index by capabilities
        for cap in agent.capabilities:
            self._capability_index.setdefault(cap, []).append(agent.agent_id)

        await agent.initialize()

        await self.event_bus.emit(
            Event(
                type="registry.agent_registered",
                source="registry",
                data={"agent_id": agent.agent_id, "agent_type": agent.agent_type},
            )
        )
        logger.info("Registered agent %s (type=%s)", agent.agent_id, agent.agent_type)

    async def deregister(self, agent_id: str) -> None:
        """Deregister and shut down an agent."""
        agent = self._agents.pop(agent_id, None)
        if agent is None:
            return

        # Clean up indexes
        type_list = self._type_index.get(agent.agent_type, [])
        if agent_id in type_list:
            type_list.remove(agent_id)

        for cap in agent.capabilities:
            cap_list = self._capability_index.get(cap, [])
            if agent_id in cap_list:
                cap_list.remove(agent_id)

        await agent.shutdown()

        await self.event_bus.emit(
            Event(
                type="registry.agent_deregistered",
                source="registry",
                data={"agent_id": agent_id, "agent_type": agent.agent_type},
            )
        )

    def get(self, agent_id: str) -> BaseAgent | None:
        """Get an agent by ID."""
        return self._agents.get(agent_id)

    def find_by_type(self, agent_type: str) -> list[BaseAgent]:
        """Find all agents of a given type."""
        ids = self._type_index.get(agent_type, [])
        return [self._agents[aid] for aid in ids if aid in self._agents]

    def find_by_capability(self, capability: str) -> list[BaseAgent]:
        """Find all agents that provide a given capability."""
        ids = self._capability_index.get(capability, [])
        return [self._agents[aid] for aid in ids if aid in self._agents]

    def best_agent_for(self, capability: str) -> BaseAgent | None:
        """Find the best agent for a capability based on success rate."""
        agents = self.find_by_capability(capability)
        if not agents:
            return None
        return max(agents, key=lambda a: (a.success_rate, a._execution_count))

    async def health_check(self) -> dict[str, Any]:
        """Return health status of all registered agents."""
        statuses = {}
        for agent_id, agent in self._agents.items():
            assessment = await agent.assess_self()
            statuses[agent_id] = {
                "type": agent.agent_type,
                "success_rate": agent.success_rate,
                "execution_count": agent._execution_count,
                "assessment": assessment,
            }
        return statuses
