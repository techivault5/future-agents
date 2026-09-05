"""Spec-driven delivery API — intake an objective, answer its questions, ship.

Routes
------
POST   /api/sdd/objectives                 Intake an objective and run as far as it can
GET    /api/sdd/runs                       List runs
GET    /api/sdd/runs/{run_id}              Full run state
GET    /api/sdd/runs/{run_id}/questions    Open clarification questions
POST   /api/sdd/runs/{run_id}/answers      Answer questions and resume
POST   /api/sdd/runs/{run_id}/meeting      Record a clarification meeting and resume
GET    /api/sdd/cases                      Browse / search the memory hub
GET    /api/sdd/constitution               The constitution as markdown (MCP resource)
POST   /api/sdd/cicd/diff-gate             Check a pipeline change against the golden template
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from future_agents.sdd import (
    DeliveryPipeline,
    IntakeSource,
    MemoryHub,
    Objective,
    RunState,
    SpecKitConfig,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Spec-Driven Delivery"])

_ROOT = Path(__file__).resolve().parents[4]
_config = SpecKitConfig.load(root=_ROOT)
_memory = MemoryHub(_config.memory_hub, root=_ROOT)
_pipeline = DeliveryPipeline(_config, memory=_memory)

# Runs live in memory: a run is a conversation, not a record of truth. Persist
# with future_agents.sdd.save_state when a run must outlive the process.
_RUNS: dict[str, RunState] = {}


class ObjectiveRequest(BaseModel):
    statement: str
    context: str = ""
    source: IntakeSource = IntakeSource.CHAT
    submitted_by: str = "unknown"
    raw_inputs: list[str] = []
    constraints: list[str] = []
    deadline: Optional[str] = None


class AnswerRequest(BaseModel):
    answers: dict[str, str]
    answered_by: str = "human"


class MeetingRequestBody(BaseModel):
    notes: str = ""
    answers: dict[str, str] = {}


class DiffGateRequest(BaseModel):
    proposed: str
    golden: Optional[str] = None


def _summary(state: RunState) -> dict:
    return {
        "run_id": state.id,
        "stage": state.stage.value,
        "awaiting_human": state.awaiting_human,
        "confidence": state.clarification.confidence if state.clarification else None,
        "outcome": state.clarification.outcome.value if state.clarification else None,
        "questions": [
            {"id": q.id, "text": q.text, "blocking": q.blocking, "options": q.options}
            for q in state.pending_questions()
        ],
        "meeting": state.clarification.meeting.model_dump(mode="json")
        if state.clarification and state.clarification.meeting
        else None,
        "requirements": [
            {"id": r.id, "priority": r.priority.value, "statement": r.statement}
            for r in (state.spec.requirements if state.spec else [])
        ],
        "tasks": len(state.tasks.tasks) if state.tasks else 0,
        "qa": state.qa.summary_lines() if state.qa else [],
        "accepted": state.delivery.accepted if state.delivery else False,
        "case_id": state.case_id,
    }


def _get(run_id: str) -> RunState:
    state = _RUNS.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    return state


@router.post("/api/sdd/objectives", summary="Intake an objective and start delivery")
def create_objective(body: ObjectiveRequest) -> dict:
    state = _pipeline.start(Objective(**body.model_dump()))
    _RUNS[state.id] = state
    return _summary(state)


@router.get("/api/sdd/runs", summary="List runs")
def list_runs(limit: int = Query(50, ge=1, le=200)) -> dict:
    runs = sorted(_RUNS.values(), key=lambda s: s.updated_at, reverse=True)[:limit]
    return {"total": len(_RUNS), "runs": [_summary(s) for s in runs]}


@router.get("/api/sdd/runs/{run_id}", summary="Full run state")
def get_run(run_id: str) -> RunState:
    return _get(run_id)


@router.get("/api/sdd/runs/{run_id}/questions", summary="Open clarification questions")
def get_questions(run_id: str) -> dict:
    state = _get(run_id)
    return {
        "run_id": run_id,
        "questions": [q.model_dump(mode="json") for q in state.pending_questions()],
    }


@router.post("/api/sdd/runs/{run_id}/answers", summary="Answer questions and resume")
def post_answers(run_id: str, body: AnswerRequest) -> dict:
    state = _pipeline.answer(_get(run_id), body.answers, answered_by=body.answered_by)
    _RUNS[state.id] = state
    return _summary(state)


@router.post("/api/sdd/runs/{run_id}/meeting", summary="Record a meeting and resume")
def post_meeting(run_id: str, body: MeetingRequestBody) -> dict:
    state = _pipeline.hold_meeting(_get(run_id), body.notes, body.answers)
    _RUNS[state.id] = state
    return _summary(state)


@router.get("/api/sdd/cases", summary="Browse or search delivery memory cases")
def get_cases(q: Optional[str] = Query(None), limit: int = Query(20, ge=1, le=100)) -> dict:
    if q:
        report = _memory.retrieve(q, top_k=limit)
        return {
            "query": q,
            "matches": [
                {"score": m.score, "reason": m.reason, "case": m.case.model_dump(mode="json")}
                for m in report.matches
            ],
            "warnings": report.warnings(),
        }
    return {
        "stats": _memory.stats(),
        "cases": [c.model_dump(mode="json") for c in _memory.all_cases()[:limit]],
    }


@router.get("/api/sdd/constitution", summary="The constitution as markdown")
def get_constitution() -> dict:
    constitution = _config.constitution()
    return {"markdown": constitution.render_markdown(), "rules": constitution.model_dump()}


@router.post(
    "/api/sdd/cicd/diff-gate", summary="Check a pipeline change against the golden template"
)
def post_diff_gate(body: DiffGateRequest) -> dict:
    golden = body.golden or _config.golden_template(root=_ROOT)
    if golden is None:
        raise HTTPException(status_code=400, detail="no golden template configured")
    decision = _config.constitution().diff_gate(golden, body.proposed)
    return decision.model_dump()
