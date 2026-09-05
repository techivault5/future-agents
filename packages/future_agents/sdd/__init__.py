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
from future_agents.sdd.languages import (
    TOOLCHAINS,
    LayoutEntry,
    RepoProfile,
    Toolchain,
    detect_repo,
    language_matrix,
    toolchain_for,
)
from future_agents.sdd.master import MasterOrchestrator, ProgramRun, RepoTarget
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
from future_agents.sdd.personas import (
    DEFAULT_PERSONA,
    PERSONAS,
    Persona,
    get_persona,
    persona_catalog,
)
from future_agents.sdd.pipeline import DeliveryPipeline, load_state, save_state
from future_agents.sdd.router import (
    AnthropicEngine,
    CallableEngine,
    EngineCall,
    EngineRouter,
    NullEngine,
)
from future_agents.sdd.scaffold import RepoScaffolder, ScaffoldAction, ScaffoldPlan
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
    "DEFAULT_PERSONA",
    "Delivery",
    "DeliveryPipeline",
    "DeliveryStage",
    "detect_repo",
    "dry_run_backend",
    "EngineCall",
    "EngineRouter",
    "get_persona",
    "IntakeSource",
    "IntentClarifier",
    "language_matrix",
    "LayoutEntry",
    "load_state",
    "MasterOrchestrator",
    "MeetingRequest",
    "MemoryCase",
    "MemoryHub",
    "NullEngine",
    "Objective",
    "PatchDecision",
    "Persona",
    "persona_catalog",
    "PERSONAS",
    "Plan",
    "PMStage",
    "Priority",
    "ProgramRun",
    "QAReport",
    "QAStage",
    "QAVerdict",
    "Question",
    "RepoProfile",
    "RepoScaffolder",
    "RepoTarget",
    "Requirement",
    "RetrievalReport",
    "RunState",
    "save_state",
    "ScaffoldAction",
    "ScaffoldPlan",
    "Severity",
    "Spec",
    "SpecKitConfig",
    "Stage",
    "TaskGraph",
    "TaskKind",
    "TaskPlanner",
    "TaskStatus",
    "TaskUnit",
    "Toolchain",
    "toolchain_for",
    "TOOLCHAINS",
    "Violation",
    "WorkerStage",
    "WorkResult",
]
