"""Pydantic schemas for the marketplace API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class AgentSummary(BaseModel):
    """Lightweight agent listing item (from index)."""

    id: str
    name: str
    role: str
    type: str
    seniority: str
    industry_focus: str | None = None
    cloud_preference: str | None = None
    primary_stack: str | None = None
    guardrails_profile: str | None = None
    tags: list[str] = []


class AgentDetail(AgentSummary):
    """Full agent definition (from YAML file)."""

    description: str | None = None
    skills: list[str] = []
    tools: list[str] = []
    certifications: list[str] = []
    human_input_required: bool = False
    package_policy: str | None = None
    folder_structure_template: str | None = None
    version: str | None = None
    created_by: str | None = None


class TestRequest(BaseModel):
    """Test an agent with a free-text prompt."""

    prompt: str
    context: dict[str, Any] | None = None


class TestResponse(BaseModel):
    """Simulated agent response based on its definition."""

    agent_id: str
    agent_name: str
    role: str
    response: str
    relevant_skills: list[str]
    recommended_tools: list[str]
    guardrails_profile: str
    human_escalation_required: bool


class PaginatedAgents(BaseModel):
    """Paginated agent listing."""

    agents: list[AgentSummary]
    total: int
    page: int
    page_size: int
    pages: int


class CategorySummary(BaseModel):
    """Role category with agent counts."""

    category: str
    type: str
    count: int
    roles: list[str]


class MarketplaceStats(BaseModel):
    """High-level marketplace statistics."""

    total_agents: int
    technical: int
    non_technical: int
    voice: int
    seniority_breakdown: dict[str, int]
    top_roles: list[dict[str, Any]]
    guardrails_profiles: dict[str, int]
