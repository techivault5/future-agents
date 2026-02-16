"""Policy model — rules and constraints agents must follow."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class PolicyScope(str, Enum):
    GLOBAL = "global"  # Applies to all agents
    DOMAIN = "domain"  # Applies to a specific domain
    AGENT = "agent"  # Applies to a specific agent
    TASK = "task"  # Applies to a specific task type


class PolicyStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    SUSPENDED = "suspended"


class PolicyRule(BaseModel):
    """A single rule within a policy."""

    condition: str  # Human-readable condition (e.g. "when handling PII data")
    action: str  # Required action (e.g. "must encrypt before storage")
    severity: str = "medium"  # low, medium, high, critical
    auto_enforce: bool = False  # Whether the system should block violations automatically


class Policy(BaseModel):
    """An organizational policy that governs agent behavior."""

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str
    description: str
    scope: PolicyScope = PolicyScope.GLOBAL
    scope_target: str | None = None  # Domain name, agent ID, or task type when scope != GLOBAL
    status: PolicyStatus = PolicyStatus.DRAFT
    rules: list[PolicyRule] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    version: int = 1
    violations_count: int = 0
    checks_count: int = 0

    @property
    def compliance_rate(self) -> float:
        if self.checks_count == 0:
            return 1.0
        return 1.0 - (self.violations_count / self.checks_count)

    def check(self, context: dict) -> list[PolicyRule]:
        """Return list of rules that are violated given the context.

        In a real system this would evaluate conditions against the context.
        This is a placeholder for the rule engine integration point.
        """
        # Returns empty (no violations) by default — override or plug in rule engine
        _ = context
        self.checks_count += 1
        self.updated_at = datetime.now(timezone.utc)
        return []

    def record_violation(self) -> None:
        self.violations_count += 1
        self.updated_at = datetime.now(timezone.utc)
