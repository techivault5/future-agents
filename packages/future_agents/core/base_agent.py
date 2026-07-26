"""Base agent — abstract foundation all agents extend."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from future_agents.core.events import Event, EventBus
from future_agents.models.feedback import ExecutionOutcome, Feedback, FeedbackType

logger = logging.getLogger(__name__)


@dataclass
class TaskContext:
    """Context passed to an agent when executing a task."""

    task_id: str = field(default_factory=lambda: uuid4().hex[:12])
    intent: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, str] = field(default_factory=dict)
    parent_task_id: str | None = None


@dataclass
class TaskResult:
    """Result returned by an agent after executing a task."""

    task_id: str
    agent_id: str
    outcome: ExecutionOutcome
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    duration_ms: float = 0.0


class BaseAgent(ABC):
    """Abstract base agent that all domain agents extend.

    Provides:
    - Lifecycle hooks (initialize, shutdown)
    - Event subscription/emission
    - Automatic feedback generation
    - Self-assessment interface
    """

    def __init__(self, agent_id: str | None = None, event_bus: EventBus | None = None) -> None:
        self.agent_id = agent_id or f"{self.agent_type}_{uuid4().hex[:8]}"
        self.event_bus = event_bus or EventBus()
        self.created_at = datetime.now(timezone.utc)
        self._execution_count = 0
        self._success_count = 0

    @property
    @abstractmethod
    def agent_type(self) -> str:
        """Unique type identifier for this agent class."""
        ...

    @property
    @abstractmethod
    def capabilities(self) -> list[str]:
        """List of capability names this agent provides."""
        ...

    @property
    def success_rate(self) -> float:
        if self._execution_count == 0:
            return 0.0
        return self._success_count / self._execution_count

    async def initialize(self) -> None:
        """Called once when the agent is registered. Override for setup logic."""
        logger.info("Agent %s initialized", self.agent_id)

    async def shutdown(self) -> None:
        """Called when the agent is being deregistered. Override for cleanup."""
        logger.info("Agent %s shutting down", self.agent_id)

    async def execute(self, context: TaskContext) -> TaskResult:
        """Execute a task — wraps _execute with metrics and feedback."""
        start = datetime.now(timezone.utc)
        self._execution_count += 1

        try:
            result = await self._execute(context)
        except Exception as exc:
            logger.error("Agent %s failed task %s: %s", self.agent_id, context.task_id, exc)
            result = TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.FAILURE,
                errors=[str(exc)],
            )

        end = datetime.now(timezone.utc)
        result.duration_ms = (end - start).total_seconds() * 1000

        if result.outcome == ExecutionOutcome.SUCCESS:
            self._success_count += 1

        # Emit completion event
        await self.event_bus.emit(
            Event(
                type=f"agent.{self.agent_type}.task_completed",
                source=self.agent_id,
                data={
                    "task_id": context.task_id,
                    "outcome": result.outcome.value,
                    "duration_ms": result.duration_ms,
                },
            )
        )

        return result

    @abstractmethod
    async def _execute(self, context: TaskContext) -> TaskResult:
        """Core execution logic — implement in subclasses."""
        ...

    def generate_feedback(self, result: TaskResult) -> Feedback:
        """Generate automated feedback from a task result."""
        score = {
            ExecutionOutcome.SUCCESS: 1.0,
            ExecutionOutcome.PARTIAL: 0.5,
            ExecutionOutcome.FAILURE: 0.0,
            ExecutionOutcome.SKIPPED: 0.0,
        }[result.outcome]

        return Feedback(
            task_id=result.task_id,
            agent_id=self.agent_id,
            feedback_type=FeedbackType.AUTOMATED,
            outcome=result.outcome,
            score=score,
            suggestions=result.suggestions,
        )

    @abstractmethod
    async def assess_self(self) -> dict[str, Any]:
        """Return a self-assessment of the agent's current state.

        Used by the sync engine to identify improvement opportunities.
        Should include metrics, known gaps, and confidence levels.
        """
        ...

    async def emit(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Convenience method to emit an event from this agent."""
        await self.event_bus.emit(Event(type=event_type, source=self.agent_id, data=data or {}))
