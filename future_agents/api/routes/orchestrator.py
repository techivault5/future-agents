"""Orchestrator REST API — n8n-style smart routing over HTTP.

Endpoints
---------
POST /api/orchestrator/ask          Route a question to the best agent
POST /api/orchestrator/find-agents  Catalog search with scoring
POST /api/orchestrator/check        Guardrails scan
GET  /api/orchestrator/history      Conversation history for the session
DELETE /api/orchestrator/history    Clear session history
GET  /api/orchestrator/status       Orchestrator health + catalog stats
GET  /api/orchestrator/intents      Supported intent categories
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from future_agents.agents.orchestrator_agent import (
    AgentMatch,
    GuardrailsResult,
    OrchestratorAgent,
    OrchestratorResponse,
)

router = APIRouter(tags=["Orchestrator"])

# Module-level singleton so conversation history persists across requests
_orchestrator = OrchestratorAgent()


# ── Request models ─────────────────────────────────────────────────────────────


class AskRequest(BaseModel):
    question: str
    domain: Optional[str] = None
    seniority: Optional[str] = None
    top_k: int = 3
    session_context: Optional[str] = None


class FindAgentsRequest(BaseModel):
    task: str
    domain: Optional[str] = None
    seniority: Optional[str] = None
    agent_type: Optional[str] = None
    limit: int = 10


class GuardrailsCheckRequest(BaseModel):
    content: str
    profile: str = "standard"


# ── Response shaping helpers ──────────────────────────────────────────────────


def _agent_match_dict(m: AgentMatch) -> dict:
    return {
        "agent_id": m.agent_id,
        "agent_name": m.agent_name,
        "role": m.role,
        "seniority": m.seniority,
        "type": m.agent_type,
        "match_score": m.match_score,
        "match_reasons": m.match_reasons,
        "guardrails_profile": m.guardrails_profile,
        "primary_stack": m.primary_stack,
        "top_skills": m.top_skills,
    }


def _guardrails_dict(g: GuardrailsResult) -> dict:
    return {
        "profile": g.profile,
        "passed": g.passed,
        "secrets_found": g.secrets_found,
        "escalation_required": g.escalation_required,
        "escalation_reasons": g.escalation_reasons,
        "warnings": g.warnings,
        "recommendations": g.recommendations,
    }


def _response_dict(r: OrchestratorResponse) -> dict:
    return {
        "question": r.question,
        "intent": r.intent,
        "domains": r.domains,
        "detected_stack": r.detected_stack,
        "primary_agent": _agent_match_dict(r.primary_agent) if r.primary_agent else None,
        "matched_agents": [_agent_match_dict(m) for m in r.matched_agents],
        "system_prompt": r.system_prompt,
        "context_block": r.context_block,
        "guardrails": _guardrails_dict(r.guardrails),
        "confidence": r.confidence,
        "multi_agent_suggested": r.multi_agent_suggested,
        "suggested_workflow": r.suggested_workflow,
        "timestamp": r.timestamp,
    }


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.post("/api/orchestrator/ask", summary="Route a question to the best IT role agent")
def ask(body: AskRequest) -> dict:
    """Classify intent, score 10K catalog, build expert persona + guardrails.

    Returns a rich response including:
    - The matched agent's system prompt (use as LLM system message)
    - Structured context block (inject into conversation)
    - Guardrails result (secrets, escalation triggers, warnings)
    - Top N candidate agents with scores
    """
    if not body.question.strip():
        raise HTTPException(400, "question must not be empty")

    resp = _orchestrator.ask(
        question=body.question,
        domain=body.domain,
        seniority=body.seniority,
        top_k=min(body.top_k, 10),
        session_context=body.session_context,
    )
    return _response_dict(resp)


@router.post("/api/orchestrator/find-agents", summary="Search the 10K catalog and return scored matches")
def find_agents(body: FindAgentsRequest) -> dict:
    if not body.task.strip():
        raise HTTPException(400, "task must not be empty")

    matches = _orchestrator.find_agents(
        task=body.task,
        domain=body.domain,
        seniority=body.seniority,
        agent_type=body.agent_type,
        limit=min(body.limit, 50),
    )
    return {
        "task": body.task,
        "total": len(matches),
        "agents": [_agent_match_dict(m) for m in matches],
    }


@router.post("/api/orchestrator/check", summary="Scan content for guardrails violations")
def check_guardrails(body: GuardrailsCheckRequest) -> dict:
    """Run secrets scanning, escalation detection, and security pattern checks."""
    if not body.content.strip():
        raise HTTPException(400, "content must not be empty")

    result = _orchestrator.check_guardrails(body.content, body.profile)
    return _guardrails_dict(result)


@router.get("/api/orchestrator/history", summary="Get session conversation history")
def get_history() -> dict:
    return {
        "turns": _orchestrator.history_summary(),
        "count": len(_orchestrator.history_summary()),
    }


@router.delete("/api/orchestrator/history", summary="Clear session conversation history")
def clear_history() -> dict:
    _orchestrator.clear_history()
    return {"cleared": True}


@router.get("/api/orchestrator/status", summary="Orchestrator health and catalog statistics")
def status() -> dict:
    return _orchestrator.status()


@router.get("/api/orchestrator/intents", summary="Supported intent categories with keyword hints")
def intents() -> dict:
    from future_agents.agents.orchestrator_agent import _DOMAIN_KEYWORDS, _INTENT_KEYWORDS

    return {
        "intents": {intent: kws[:5] for intent, kws in _INTENT_KEYWORDS.items()},
        "domains": {domain: kws[:5] for domain, kws in _DOMAIN_KEYWORDS.items()},
        "seniority_levels": ["intern", "junior", "mid-level", "senior", "principal", "architect"],
        "guardrails_profiles": ["standard", "strict", "relaxed", "architect"],
    }
