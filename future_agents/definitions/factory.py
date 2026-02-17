"""Agent Factory — constructs DefinedAgents from definitions + implementations.

Maps agent type strings (from definitions) to their concrete Python
implementations, then wraps them in DefinedAgent for definition-driven behavior.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from future_agents.core.base_agent import BaseAgent
from future_agents.core.events import EventBus
from future_agents.definitions.defined_agent import DefinedAgent
from future_agents.definitions.loader import DefinitionLoader
from future_agents.definitions.schema import AgentDefinition

logger = logging.getLogger(__name__)

# Type for implementation factory functions
ImplFactory = Callable[..., BaseAgent]


class AgentFactory:
    """Creates DefinedAgent instances from definition files.

    Usage:
        factory = AgentFactory()

        # Register implementation classes for each agent type
        factory.register_implementation("capability", lambda **kw: CapabilityAgent(**kw))
        factory.register_implementation("process", lambda **kw: ProcessAgent(**kw))

        # Build agents from a directory of definitions
        agents = factory.build_from_directory("agents/")

        # Or build from a single definition
        agent = factory.build(some_definition)
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.event_bus = event_bus or EventBus()
        self._loader = DefinitionLoader()
        self._implementations: dict[str, ImplFactory] = {}
        self._extra_kwargs: dict[str, dict[str, Any]] = {}

    def register_implementation(
        self, agent_type: str, factory_fn: ImplFactory, **kwargs: Any
    ) -> None:
        """Register a factory function for a given agent type.

        Args:
            agent_type: The agent type string (must match definition's 'type' field)
            factory_fn: A callable that creates a BaseAgent instance
            **kwargs: Extra keyword arguments passed to the factory function
        """
        self._implementations[agent_type] = factory_fn
        if kwargs:
            self._extra_kwargs[agent_type] = kwargs

    def build(self, definition: AgentDefinition) -> DefinedAgent:
        """Build a DefinedAgent from a definition."""
        impl_factory = self._implementations.get(definition.type)
        if not impl_factory:
            raise ValueError(
                f"No implementation registered for agent type '{definition.type}'. "
                f"Registered types: {list(self._implementations.keys())}"
            )

        extra = self._extra_kwargs.get(definition.type, {})
        implementation = impl_factory(**extra)

        agent = DefinedAgent(
            definition=definition,
            implementation=implementation,
            event_bus=self.event_bus,
        )

        # Validate and log warnings
        warnings = self._loader.validate(definition)
        for warning in warnings:
            logger.warning("Definition warning: %s", warning)

        logger.info(
            "Built DefinedAgent: %s (type=%s, skills=%d)",
            definition.name,
            definition.type,
            len(definition.skills),
        )
        return agent

    def build_from_file(self, path: str | Path) -> DefinedAgent:
        """Load a definition file and build a DefinedAgent."""
        definition = self._loader.load_file(path)
        return self.build(definition)

    def build_from_directory(self, path: str | Path) -> list[DefinedAgent]:
        """Load all definitions from a directory and build DefinedAgents."""
        definitions = self._loader.load_directory(path)
        agents: list[DefinedAgent] = []
        for defn in definitions:
            try:
                agent = self.build(defn)
                agents.append(agent)
            except ValueError as e:
                logger.warning("Skipping agent '%s': %s", defn.name, e)
        return agents

    @property
    def registered_types(self) -> list[str]:
        return list(self._implementations.keys())
