"""Process model — workflows and standard operating procedures."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class ProcessStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    RETIRED = "retired"


class ProcessStep(BaseModel):
    """A single step in a process workflow."""

    order: int
    name: str
    description: str
    responsible_agent: str | None = None  # Agent type or ID responsible
    required_capabilities: list[str] = Field(default_factory=list)
    required_policies: list[str] = Field(default_factory=list)  # Policy IDs to check
    timeout_seconds: int | None = None
    retry_count: int = 0
    is_optional: bool = False
    outputs: list[str] = Field(default_factory=list)  # Expected output keys


class Process(BaseModel):
    """A multi-step organizational process / SOP."""

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str
    description: str
    domain: str
    status: ProcessStatus = ProcessStatus.DRAFT
    steps: list[ProcessStep] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    trigger_conditions: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    version: int = 1
    execution_count: int = 0
    avg_completion_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    def add_step(self, step: ProcessStep) -> None:
        """Add a step, automatically ordering it."""
        step.order = len(self.steps) + 1
        self.steps.append(step)
        self.updated_at = datetime.now(timezone.utc)

    def record_execution(self, steps_completed: int) -> None:
        """Record a process execution and update metrics."""
        self.execution_count += 1
        total_steps = len(self.steps)
        if total_steps > 0:
            completion = steps_completed / total_steps
            self.avg_completion_rate = (
                (self.avg_completion_rate * (self.execution_count - 1)) + completion
            ) / self.execution_count
        self.updated_at = datetime.now(timezone.utc)
