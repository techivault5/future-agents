"""Knowledge model — versioned organizational knowledge entries."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


class KnowledgeVersion(BaseModel):
    """A snapshot of a knowledge entry at a specific version."""

    version: int
    content: str
    changed_by: str  # Agent ID or "human"
    change_reason: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class KnowledgeEntry(BaseModel):
    """A piece of organizational knowledge with full version history."""

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    title: str
    domain: str
    content: str
    tags: list[str] = Field(default_factory=list)
    source_agent: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    access_count: int = 0
    usefulness_score: float = Field(default=0.5, ge=0.0, le=1.0)
    history: list[KnowledgeVersion] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def version(self) -> int:
        return len(self.history) + 1

    def update_content(self, new_content: str, changed_by: str, reason: str) -> None:
        """Update content and push current version to history."""
        self.history.append(
            KnowledgeVersion(
                version=self.version,
                content=self.content,
                changed_by=changed_by,
                change_reason=reason,
            )
        )
        self.content = new_content
        self.updated_at = datetime.now(timezone.utc)

    def record_access(self, was_useful: bool) -> None:
        """Track how often and how usefully this knowledge is accessed."""
        self.access_count += 1
        # Exponential moving average for usefulness
        alpha = 0.1
        self.usefulness_score = alpha * (1.0 if was_useful else 0.0) + (1 - alpha) * self.usefulness_score
        self.updated_at = datetime.now(timezone.utc)

    def rollback(self, to_version: int) -> bool:
        """Rollback to a previous version."""
        for hist in self.history:
            if hist.version == to_version:
                self.update_content(hist.content, "system", f"rollback to v{to_version}")
                return True
        return False
