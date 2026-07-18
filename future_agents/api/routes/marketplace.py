"""Marketplace discovery endpoints — stats, categories, testing, recommendations."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from future_agents.api import loader
from future_agents.api.schemas import (
    CategorySummary,
    MarketplaceStats,
    TestRequest,
    TestResponse,
)

router = APIRouter(prefix="/api", tags=["marketplace"])


class RecommendRequest(BaseModel):
    task: str
    limit: int = 10


@router.get("/health")
def health() -> dict:
    """Health check — includes rich index readiness."""
    index = loader.load_index()
    return {
        "status": "ok",
        "agents_loaded": len(index),
        "rich_index_ready": loader._rich_index_ready.is_set(),
        "rich_index_size": len(loader._rich_index),
    }


@router.post("/agents/recommend")
def recommend_agents(body: RecommendRequest) -> dict:
    """Recommend the best agents for a given task description.

    Uses the rich index to score agents by skill/tool/role relevance.
    Returns an empty list with a hint if the rich index isn't built yet.
    """
    if not loader._rich_index_ready.is_set():
        return {
            "task": body.task,
            "agents": [],
            "note": "Rich index is still building (10–20 s after startup). Try again shortly.",
        }

    matches = loader.recommend_agents(body.task, limit=body.limit)
    return {
        "task": body.task,
        "agents": [
            {
                "id": a.get("id", ""),
                "name": a.get("name", ""),
                "role": a.get("role", ""),
                "seniority": a.get("seniority", ""),
                "primary_stack": a.get("primary_stack", ""),
                "skills": a.get("skills", [])[:6],
                "tools": a.get("tools", [])[:4],
                "guardrails_profile": a.get("guardrails_profile", "standard"),
            }
            for a in matches
        ],
    }


@router.get("/stats", response_model=MarketplaceStats)
def stats() -> MarketplaceStats:
    """Marketplace-wide statistics."""
    return MarketplaceStats(**loader.get_stats())


@router.get("/categories", response_model=list[CategorySummary])
def categories() -> list[CategorySummary]:
    """All role categories with agent counts."""
    cats = loader.get_categories()
    return [CategorySummary(**c) for c in cats]


@router.post("/agents/{agent_id}/test", response_model=TestResponse)
def test_agent(agent_id: str, body: TestRequest) -> TestResponse:
    """Simulate calling an agent with a prompt.

    Returns a structured response based on the agent's role definition,
    including which of its skills are relevant and its guardrails profile.
    """
    data = loader.load_agent_yaml(agent_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    skills: list[str] = data.get("skills", [])
    tools: list[str] = data.get("tools", [])
    prompt_lower = body.prompt.lower()

    # Surface skills that match keywords in the prompt
    relevant = [s for s in skills if any(w in prompt_lower for w in s.replace("-", " ").split())]
    if not relevant:
        relevant = skills[:3]  # fallback: show first 3

    response_text = (
        f"As a **{data.get('seniority', '').title()} {data.get('role', '').replace('-', ' ').title()}**, "
        f"I would approach this by leveraging my expertise in: "
        f"{', '.join(relevant[:5]) if relevant else 'general IT practices'}.\n\n"
        f"My primary stack is **{data.get('primary_stack', 'N/A')}** "
        f"with preferred cloud platform **{data.get('cloud_preference', 'N/A')}**.\n\n"
        f"For this task I would use: {', '.join(tools[:4]) if tools else 'standard tooling'}."
    )

    return TestResponse(
        agent_id=agent_id,
        agent_name=data.get("name", agent_id),
        role=data.get("role", ""),
        response=response_text,
        relevant_skills=relevant[:5],
        recommended_tools=tools[:4],
        guardrails_profile=data.get("guardrails_profile", "standard"),
        human_escalation_required=data.get("human_input_required", False),
    )
