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
GET    /api/sdd/personas                   Seniority profiles the pipeline can run as
GET    /api/sdd/languages                  Supported toolchains and their commands
POST   /api/sdd/repos/detect               Profile a repository (language, toolchain, gaps)
POST   /api/sdd/repos/index                Index a repository: symbols, conventions, source roots
POST   /api/sdd/repos/context              What the repo already knows about a piece of work
POST   /api/sdd/repos/placement            Where a change goes, where it must not, alternatives
POST   /api/sdd/repos/scaffold             Plan (or write) the structure a repo is missing
POST   /api/sdd/programs                   Run one objective across many repositories
POST   /api/sdd/programs/{id}/answers      Answer the merged question set and resume
POST   /api/sdd/programs/{id}/meeting      Record one meeting for the whole program
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
    MasterOrchestrator,
    MemoryHub,
    Objective,
    ProgramRun,
    RepoKnowledge,
    RepoScaffolder,
    RunState,
    SpecKitConfig,
    detect_repo,
    get_persona,
    language_matrix,
    persona_catalog,
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
_PROGRAMS: dict[str, tuple[MasterOrchestrator, ProgramRun]] = {}


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


class RepoRequest(BaseModel):
    path: str
    language: Optional[str] = None
    name: str = ""
    description: str = ""
    persona: Optional[str] = None
    write: bool = False


class KnowledgeRequest(BaseModel):
    path: str = "."
    query: str = ""
    limit: int = 6


class PlacementRequest(BaseModel):
    path: str = "."
    what: str


class ProgramRepo(BaseModel):
    name: str
    path: str
    keywords: list[str] = []
    depends_on: list[str] = []
    persona: Optional[str] = None


class ProgramRequest(ObjectiveRequest):
    repos: list[ProgramRepo]
    persona: Optional[str] = None


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


@router.get("/api/sdd/personas", summary="Seniority profiles the pipeline can run as")
def get_personas() -> dict:
    return {"personas": persona_catalog()}


@router.get("/api/sdd/languages", summary="Supported toolchains and their commands")
def get_languages() -> dict:
    return {"languages": language_matrix()}


@router.post("/api/sdd/repos/detect", summary="Profile a repository")
def post_detect(body: RepoRequest) -> dict:
    profile = detect_repo(body.path)
    chain = profile.toolchain()
    scaffolder = RepoScaffolder(get_persona(body.persona))
    return {
        "profile": profile.model_dump(mode="json"),
        "toolchain": chain.model_dump(mode="json", exclude={"layout"}),
        "commands": chain.commands(),
        "missing_structure": scaffolder.validate(body.path, profile),
    }


@router.post("/api/sdd/repos/scaffold", summary="Plan or write the missing repo structure")
def post_scaffold(body: RepoRequest) -> dict:
    scaffolder = RepoScaffolder(get_persona(body.persona))
    plan = scaffolder.plan(
        body.path, language=body.language, name=body.name, description=body.description
    )
    written = scaffolder.apply(plan, dry_run=not body.write)
    return {
        "summary": plan.summary(),
        "written" if body.write else "would_write": written,
        "actions": [a.model_dump(mode="json", exclude={"content"}) for a in plan.actions],
    }


@router.post("/api/sdd/programs", summary="Run one objective across many repositories")
def post_program(body: ProgramRequest) -> dict:
    orchestrator = MasterOrchestrator(_config, memory=_memory, persona=get_persona(body.persona))
    for repo in body.repos:
        orchestrator.register(
            repo.name,
            repo.path,
            persona_id=repo.persona,
            keywords=repo.keywords or [repo.name],
            depends_on=repo.depends_on,
        )
    objective = Objective(**body.model_dump(exclude={"repos", "persona"}))
    program = orchestrator.start(objective)
    _PROGRAMS[program.id] = (orchestrator, program)
    return program.report()


def _program(program_id: str) -> tuple[MasterOrchestrator, ProgramRun]:
    entry = _PROGRAMS.get(program_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"program {program_id} not found")
    return entry


@router.post("/api/sdd/programs/{program_id}/answers", summary="Answer the merged question set")
def post_program_answers(program_id: str, body: AnswerRequest) -> dict:
    orchestrator, program = _program(program_id)
    program = orchestrator.answer(program, body.answers, answered_by=body.answered_by)
    _PROGRAMS[program_id] = (orchestrator, program)
    return program.report()


@router.post("/api/sdd/programs/{program_id}/meeting", summary="Record one program meeting")
def post_program_meeting(program_id: str, body: MeetingRequestBody) -> dict:
    orchestrator, program = _program(program_id)
    program = orchestrator.hold_meeting(program, body.notes, body.answers)
    _PROGRAMS[program_id] = (orchestrator, program)
    return program.report()


# Indexing a repository is cheap but not free; one index per path is plenty.
_KNOWLEDGE: dict[str, RepoKnowledge] = {}


def _knowledge(path: str) -> RepoKnowledge:
    if path not in _KNOWLEDGE:
        _KNOWLEDGE[path] = RepoKnowledge.build(path)
    return _KNOWLEDGE[path]


@router.post("/api/sdd/repos/index", summary="Index a repository")
def post_index(body: KnowledgeRequest) -> dict:
    knowledge = _knowledge(body.path)
    return {
        "stats": knowledge.stats(),
        "source_roots": knowledge.index.source_roots(),
        "conventions": [
            {"subject": r.subject, "destination": r.destination, "source": r.source}
            for r in knowledge.conventions.rules
        ],
        "prohibitions": [
            {"text": p.text, "paths": p.paths, "source": p.source}
            for p in knowledge.conventions.prohibitions
        ],
    }


@router.post("/api/sdd/repos/context", summary="What the repo already knows about this work")
def post_context(body: KnowledgeRequest) -> dict:
    if not body.query:
        raise HTTPException(status_code=400, detail="query is required")
    context = _knowledge(body.path).context(body.query, limit=body.limit)
    return context.model_dump(mode="json")


@router.post("/api/sdd/repos/placement", summary="Where a change goes, and where it must not")
def post_placement(body: PlacementRequest) -> dict:
    return _knowledge(body.path).advise(body.what).model_dump(mode="json")
