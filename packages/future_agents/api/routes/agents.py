"""Agent browse and detail endpoints."""

from __future__ import annotations

import math

from fastapi import APIRouter, HTTPException, Query

from future_agents.api import loader
from future_agents.api.schemas import AgentDetail, AgentSummary, PaginatedAgents

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("", response_model=PaginatedAgents)
def list_agents(
    q: str | None = Query(None, description="Free-text search on name/role"),
    role: str | None = Query(None, description="Filter by role slug"),
    type: str | None = Query(None, description="technical | non-technical | voice"),
    seniority: str | None = Query(None, description="intern | junior | mid | senior | …"),
    industry: str | None = Query(None, description="fintech | healthtech | edtech | …"),
    cloud: str | None = Query(None, description="aws | gcp | azure"),
    stack: str | None = Query(None, description="Filter by primary_stack"),
    profile: str | None = Query(None, description="standard | strict | relaxed | architect"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PaginatedAgents:
    """Browse and search the 10,000-agent marketplace."""
    results = loader.search_index(
        query=q,
        role=role,
        type_filter=type,
        seniority=seniority,
        industry=industry,
        cloud=cloud,
        stack=stack,
        profile=profile,
    )
    total = len(results)
    start = (page - 1) * page_size
    page_items = results[start : start + page_size]

    return PaginatedAgents(
        agents=[AgentSummary(**_coerce(a)) for a in page_items],
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/{agent_id}", response_model=AgentDetail)
def get_agent(agent_id: str) -> AgentDetail:
    """Fetch full agent definition by ID."""
    data = loader.load_agent_yaml(agent_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return AgentDetail(**_coerce(data))


def _coerce(raw: dict) -> dict:
    """Normalise raw dict so it fits the schema (handle missing fields safely)."""
    return {
        "id": raw.get("id", ""),
        "name": raw.get("name", ""),
        "role": raw.get("role", ""),
        "type": raw.get("type", ""),
        "seniority": raw.get("seniority", ""),
        "description": raw.get("description"),
        "industry_focus": raw.get("industry_focus"),
        "cloud_preference": raw.get("cloud_preference"),
        "primary_stack": raw.get("primary_stack"),
        "guardrails_profile": raw.get("guardrails_profile", "standard"),
        "tags": raw.get("tags", []),
        "skills": raw.get("skills", []),
        "tools": raw.get("tools", []),
        "certifications": raw.get("certifications", []),
        "human_input_required": raw.get("human_input_required", False),
        "package_policy": raw.get("package_policy"),
        "folder_structure_template": raw.get("folder_structure_template"),
        "version": raw.get("version"),
        "created_by": raw.get("created_by"),
    }
