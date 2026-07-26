"""Memory taxonomy for the finance advisor.

Five memory types, mirroring the cognitive taxonomy that agent-memory
frameworks (Letta/MemGPT, Mem0, Zep/Graphiti, Cognee) converge on:

    WORKING     — short-lived scratch state for the current session (TTL)
    EPISODIC    — timestamped events: what the user did/asked
    SEMANTIC    — durable facts: income, risk appetite, holdings, goals
    PROCEDURAL  — how-to sequences the agent has learned or been taught
    GRAPH       — entities and typed relations between them

Every record carries provenance, importance and access statistics so
retrieval can rank on relevance + recency + importance, and so retention
policies can forget cheaply.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    """The five supported memory kinds."""

    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    GRAPH = "graph"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryRecord(BaseModel):
    """A single memory item, uniform across all types and backends."""

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    type: MemoryType = MemoryType.SEMANTIC
    content: str
    subject: str = "user"  # whose memory this is (multi-tenant safe)
    tags: list[str] = Field(default_factory=list)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    ttl_seconds: int | None = None  # None = never expires
    source: str = "user"  # user | agent | knowledge_base | market_data
    sensitive: bool = False  # income, account details: redact in logs/exports
    embedding: list[float] = Field(default_factory=list)
    relations: list[MemoryRelation] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    last_access: datetime = Field(default_factory=_now)
    access_count: int = 0

    def age_seconds(self, now: datetime | None = None) -> float:
        """Seconds since this record was created."""
        return ((now or _now()) - self.created_at).total_seconds()

    def is_expired(self, now: datetime | None = None) -> bool:
        """True when a TTL is set and has elapsed."""
        if self.ttl_seconds is None:
            return False
        return self.age_seconds(now) > self.ttl_seconds

    def recency_score(self, half_life_seconds: float = 7 * 24 * 3600) -> float:
        """Exponential recency decay in [0, 1]; 1.0 == just written."""
        return math.pow(0.5, self.age_seconds() / max(half_life_seconds, 1.0))

    def touch(self) -> None:
        """Record an access, used by retrieval ranking and consolidation."""
        self.access_count += 1
        self.last_access = _now()

    def redacted(self) -> MemoryRecord:
        """Copy with sensitive content masked, for logs, exports and prompts."""
        if not self.sensitive:
            return self
        return self.model_copy(update={"content": "[redacted:sensitive]"})


class MemoryRelation(BaseModel):
    """A typed edge from this record to another entity or record."""

    predicate: str  # e.g. "holds", "owes", "goal_of", "derived_from"
    target: str  # entity name or memory id
    weight: float = Field(default=1.0, ge=0.0)


MemoryRecord.model_rebuild()


class RecallHit(BaseModel):
    """A retrieved record plus the score components that ranked it."""

    record: MemoryRecord
    score: float
    similarity: float = 0.0
    keyword: float = 0.0
    recency: float = 0.0
