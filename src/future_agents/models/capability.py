"""Capability model — what the organization or agent can do."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class CapabilityLevel(str, Enum):
    NOVICE = "novice"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"
    MASTER = "master"


class Capability(BaseModel):
    """A discrete capability that an agent or organization possesses."""

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str
    description: str
    domain: str  # e.g. "engineering", "sales", "compliance"
    level: CapabilityLevel = CapabilityLevel.NOVICE
    tags: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)  # IDs of prerequisite capabilities
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    usage_count: int = 0
    success_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    last_used: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    version: int = 1

    def record_usage(self, success: bool) -> None:
        """Record a usage of this capability and update metrics."""
        self.usage_count += 1
        # Rolling average for success rate
        self.success_rate = (
            (self.success_rate * (self.usage_count - 1)) + (1.0 if success else 0.0)
        ) / self.usage_count
        self.last_used = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)
        self._maybe_level_up()

    def _maybe_level_up(self) -> None:
        """Automatically promote capability level based on usage and success."""
        thresholds = {
            CapabilityLevel.NOVICE: (10, 0.6),
            CapabilityLevel.INTERMEDIATE: (50, 0.7),
            CapabilityLevel.ADVANCED: (200, 0.8),
            CapabilityLevel.EXPERT: (500, 0.9),
        }
        if self.level in thresholds:
            required_uses, required_rate = thresholds[self.level]
            if self.usage_count >= required_uses and self.success_rate >= required_rate:
                levels = list(CapabilityLevel)
                current_idx = levels.index(self.level)
                if current_idx < len(levels) - 1:
                    self.level = levels[current_idx + 1]
                    self.version += 1
