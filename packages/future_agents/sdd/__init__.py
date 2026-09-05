"""Spec-Driven Delivery — objective in, verified delivery out.

from future_agents.sdd import DeliveryPipeline, Objective, SpecKitConfig

cfg = SpecKitConfig.load()
state = DeliveryPipeline(cfg).start(Objective(statement="…"))
if state.awaiting_human:
    state = pipeline.answer(state, {q.id: "…" for q in state.pending_questions()})
"""

from future_agents.sdd.clarify import IntentClarifier
from future_agents.sdd.config import ConfigError, SpecKitConfig
from future_agents.sdd.constitution import Constitution, PatchDecision, Severity, Violation
from future_agents.sdd.memory_hub import MemoryHub, RetrievalReport
from future_agents.sdd.models import (
    AcceptanceCriterion,
    Assumption,
    ClarificationOutcome,
    ClarificationResult,
    Delivery,
    IntakeSource,
    MeetingRequest,
    MemoryCase,
    Objective,
    Plan,
    Priority,
    QAReport,
    QAVerdict,
    Question,
    Requirement,
    RunState,
    Spec,
    Stage,
    TaskGraph,
    TaskKind,
    TaskStatus,
    TaskUnit,
    WorkResult,
)
from future_agents.sdd.pipeline import DeliveryPipeline, load_state, save_state
from future_agents.sdd.router import (
    AnthropicEngine,
    CallableEngine,
    EngineCall,
    EngineRouter,
    NullEngine,
)
from future_agents.sdd.stages import (
    ArchitectStage,
    DeliveryStage,
    PMStage,
    QAStage,
    TaskPlanner,
    WorkerStage,
    dry_run_backend,
)

__all__ = [
    "AcceptanceCriterion",
    "AnthropicEngine",
    "ArchitectStage",
    "Assumption",
    "CallableEngine",
    "ClarificationOutcome",
    "ClarificationResult",
    "ConfigError",
    "Constitution",
    "Delivery",
    "DeliveryPipeline",
    "DeliveryStage",
    "EngineCall",
    "EngineRouter",
    "IntakeSource",
    "IntentClarifier",
    "MeetingRequest",
    "MemoryCase",
    "MemoryHub",
    "NullEngine",
    "Objective",
    "PMStage",
    "PatchDecision",
    "Plan",
    "Priority",
    "QAReport",
    "QAStage",
    "QAVerdict",
    "Question",
    "Requirement",
    "RetrievalReport",
    "RunState",
    "Severity",
    "Spec",
    "SpecKitConfig",
    "Stage",
    "TaskGraph",
    "TaskKind",
    "TaskPlanner",
    "TaskStatus",
    "TaskUnit",
    "Violation",
    "WorkResult",
    "WorkerStage",
    "dry_run_backend",
    "load_state",
    "save_state",
]
