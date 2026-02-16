"""Skill model — tracks skills, titles, and growth paths."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class SkillCategory(str, Enum):
    TECHNICAL = "technical"
    LEADERSHIP = "leadership"
    COMMUNICATION = "communication"
    ANALYTICAL = "analytical"
    DOMAIN_EXPERTISE = "domain_expertise"
    OPERATIONAL = "operational"


class Skill(BaseModel):
    """A discrete skill with proficiency tracking."""

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str
    description: str
    category: SkillCategory
    proficiency: float = Field(default=0.0, ge=0.0, le=1.0)
    related_capabilities: list[str] = Field(default_factory=list)  # Capability IDs
    prerequisites: list[str] = Field(default_factory=list)  # Skill IDs
    evidence: list[str] = Field(default_factory=list)  # Descriptions of demonstrated skill
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def add_evidence(self, description: str, proficiency_delta: float = 0.05) -> None:
        """Record evidence of skill usage and bump proficiency."""
        self.evidence.append(description)
        self.proficiency = min(1.0, self.proficiency + proficiency_delta)
        self.updated_at = datetime.now(timezone.utc)


class TitleLevel(BaseModel):
    """A job title / role level in a growth path."""

    title: str  # e.g. "Junior Engineer", "Senior Engineer"
    level: int  # Numeric level (1, 2, 3...)
    required_skills: dict[str, float] = Field(default_factory=dict)  # skill_id -> min proficiency
    required_capabilities: list[str] = Field(default_factory=list)
    description: str = ""


class GrowthPath(BaseModel):
    """A progression path from one title/role to another."""

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str  # e.g. "Engineering IC Track"
    domain: str
    levels: list[TitleLevel] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def current_level(self, skills: dict[str, float], capabilities: list[str]) -> TitleLevel | None:
        """Determine the highest level achieved given current skills and capabilities."""
        achieved = None
        for level in sorted(self.levels, key=lambda l: l.level):
            # Check skill requirements
            skills_met = all(
                skills.get(skill_id, 0.0) >= min_prof
                for skill_id, min_prof in level.required_skills.items()
            )
            # Check capability requirements
            caps_met = all(cap in capabilities for cap in level.required_capabilities)
            if skills_met and caps_met:
                achieved = level
            else:
                break
        return achieved

    def next_level(self, skills: dict[str, float], capabilities: list[str]) -> TitleLevel | None:
        """Determine the next level to achieve."""
        current = self.current_level(skills, capabilities)
        if current is None:
            return self.levels[0] if self.levels else None
        for level in sorted(self.levels, key=lambda l: l.level):
            if level.level > current.level:
                return level
        return None

    def skill_gaps(
        self, target_level: TitleLevel, skills: dict[str, float]
    ) -> dict[str, float]:
        """Return map of skill_id -> deficit for reaching the target level."""
        gaps = {}
        for skill_id, required in target_level.required_skills.items():
            current = skills.get(skill_id, 0.0)
            if current < required:
                gaps[skill_id] = required - current
        return gaps
