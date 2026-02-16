"""DefinedAgent — an agent constructed from an AgentDefinition.

A DefinedAgent wraps the definition with runtime behavior. It delegates
actual task execution to a concrete agent implementation (from the agents/
package) while using the definition for:
  - Prompt rendering
  - Input/output validation
  - Constraint enforcement
  - Self-description (for the Master Agent)
"""

from __future__ import annotations

import logging
from typing import Any

from future_agents.core.base_agent import BaseAgent, TaskContext, TaskResult
from future_agents.core.events import EventBus
from future_agents.core.protocol.messages import (
    AgentMessage,
    DelegationRequest,
    DelegationResponse,
    MessageRole,
    MessageType,
)
from future_agents.definitions.schema import AgentDefinition, SkillDef
from future_agents.models.feedback import ExecutionOutcome

logger = logging.getLogger(__name__)


class DefinedAgent(BaseAgent):
    """An agent that is fully described by an AgentDefinition.

    It wraps a concrete implementation agent (CapabilityAgent, ProcessAgent, etc.)
    and layers on definition-driven features:
    - Input validation against skill parameter definitions
    - Prompt rendering from templates
    - Constraint checking before execution
    - Rich self-description for discovery by the Master Agent
    """

    def __init__(
        self,
        definition: AgentDefinition,
        implementation: BaseAgent,
        event_bus: EventBus | None = None,
    ) -> None:
        super().__init__(agent_id=definition.id, event_bus=event_bus)
        self.definition = definition
        self.implementation = implementation

    @property
    def agent_type(self) -> str:
        return self.definition.type

    @property
    def capabilities(self) -> list[str]:
        return self.definition.capability_names

    async def initialize(self) -> None:
        self.implementation.event_bus = self.event_bus
        await self.implementation.initialize()
        logger.info(
            "DefinedAgent initialized: %s v%s (%d skills)",
            self.definition.name,
            self.definition.version,
            len(self.definition.skills),
        )

    async def shutdown(self) -> None:
        await self.implementation.shutdown()

    async def _execute(self, context: TaskContext) -> TaskResult:
        """Execute via the implementation, with definition-driven pre/post processing."""
        skill = self.definition.get_skill(context.intent)

        # Pre-execution: validate inputs against skill definition
        if skill:
            validation_errors = self._validate_inputs(skill, context.parameters)
            if validation_errors:
                return TaskResult(
                    task_id=context.task_id,
                    agent_id=self.agent_id,
                    outcome=ExecutionOutcome.FAILURE,
                    errors=validation_errors,
                )

        # Pre-execution: check constraints
        constraint_violations = self._check_constraints(context)
        if constraint_violations:
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.FAILURE,
                errors=constraint_violations,
            )

        # Delegate to the concrete implementation
        result = await self.implementation._execute(context)

        return result

    async def handle_message(self, message: AgentMessage) -> AgentMessage:
        """Handle a protocol message (used by Master Agent for delegation)."""
        context = TaskContext(
            task_id=message.id,
            intent=message.intent,
            parameters=message.content,
            metadata=message.metadata,
        )
        result = await self.execute(context)
        return message.reply(
            content=result.data,
            text=f"Outcome: {result.outcome.value}",
            msg_type=(
                MessageType.RESPONSE
                if result.outcome == ExecutionOutcome.SUCCESS
                else MessageType.ERROR
            ),
        )

    async def handle_delegation(self, delegation: DelegationRequest) -> DelegationResponse:
        """Handle a delegation from the Master Agent."""
        context = TaskContext(
            task_id=delegation.id,
            intent=delegation.intent,
            parameters=delegation.parameters,
            metadata={"delegated_by": delegation.from_agent},
        )
        result = await self.execute(context)
        return DelegationResponse(
            delegation_id=delegation.id,
            agent_id=self.agent_id,
            success=result.outcome == ExecutionOutcome.SUCCESS,
            data=result.data,
            errors=result.errors,
            suggestions=result.suggestions,
            duration_ms=result.duration_ms,
        )

    def describe(self) -> dict[str, Any]:
        """Return a rich self-description for the Master Agent.

        This is what the Master Agent uses to understand what this agent
        can do and how to interact with it.
        """
        return {
            "id": self.definition.id,
            "name": self.definition.name,
            "type": self.definition.type,
            "version": self.definition.version,
            "description": self.definition.description,
            "domain": self.definition.domain,
            "tags": self.definition.tags,
            "skills": [
                {
                    "name": s.name,
                    "description": s.description,
                    "intent": s.intent,
                    "level": s.level.value,
                    "inputs": [
                        {
                            "name": p.name,
                            "type": p.type.value,
                            "description": p.description,
                            "required": p.required,
                        }
                        for p in s.inputs
                    ],
                    "outputs": [
                        {"name": p.name, "type": p.type.value, "description": p.description}
                        for p in s.outputs
                    ],
                }
                for s in self.definition.skills
            ],
            "interaction_modes": [m.value for m in self.definition.interaction.modes],
            "personality": {
                "tone": self.definition.personality.tone,
                "traits": self.definition.personality.traits,
            },
            "constraints": [
                {"name": c.name, "description": c.description}
                for c in self.definition.constraints
            ],
            "metrics": {
                "success_rate": self.success_rate,
                "execution_count": self._execution_count,
            },
        }

    def render_system_prompt(self) -> str:
        """Render this agent's system prompt from its definition."""
        return self.definition.render_prompt("system") or ""

    def render_task_prompt(self, intent: str, parameters: dict) -> str | None:
        """Render a task execution prompt for a given intent."""
        return self.definition.render_prompt(
            "task_execution",
            intent=intent,
            parameters=str(parameters),
        )

    async def assess_self(self) -> dict[str, Any]:
        """Combine implementation assessment with definition metadata."""
        impl_assessment = await self.implementation.assess_self()
        return {
            **impl_assessment,
            "definition_version": self.definition.version,
            "skill_count": len(self.definition.skills),
            "constraint_count": len(self.definition.constraints),
            "prompt_count": len(self.definition.prompts),
        }

    def _validate_inputs(self, skill: SkillDef, params: dict) -> list[str]:
        """Validate input parameters against the skill definition."""
        errors: list[str] = []
        for input_def in skill.inputs:
            if input_def.required and input_def.name not in params:
                if input_def.default is None:
                    errors.append(
                        f"Missing required parameter: '{input_def.name}' "
                        f"({input_def.description})"
                    )
        return errors

    def _check_constraints(self, context: TaskContext) -> list[str]:
        """Check constraints before execution."""
        violations: list[str] = []
        for constraint in self.definition.constraints:
            if constraint.enforcement == "strict":
                # Constraint checking logic would go here — for now, pass
                pass
        return violations
