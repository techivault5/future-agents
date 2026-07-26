"""Feedback model — captures execution outcomes for the improvement loop."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class FeedbackType(str, Enum):
    AUTOMATED = "automated"  # System-generated metrics
    HUMAN = "human"  # Human review / rating
    PEER_AGENT = "peer_agent"  # Feedback from another agent


class ExecutionOutcome(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILURE = "failure"
    SKIPPED = "skipped"


class Feedback(BaseModel):
    """Feedback from a task execution, feeding the improvement loop."""

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    task_id: str
    agent_id: str
    feedback_type: FeedbackType
    outcome: ExecutionOutcome
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    details: str = ""
    capabilities_used: list[str] = Field(default_factory=list)
    policies_checked: list[str] = Field(default_factory=list)
    policy_violations: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_positive(self) -> bool:
        return self.outcome == ExecutionOutcome.SUCCESS and self.score >= 0.7

    @property
    def has_violations(self) -> bool:
        return len(self.policy_violations) > 0
