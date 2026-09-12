"""Pipeline stages — PM, Architect, Planner, Worker, QA, Delivery.

Every stage is deterministic on its own: it derives its artifact from the
upstream one with explicit rules, and an engine (when configured) only enriches
free-text fields. That is what makes runs reproducible and testable — the model
is an accelerator, never the source of truth.
"""

from future_agents.sdd.stages.architect import ArchitectStage
from future_agents.sdd.stages.delivery import DeliveryStage
from future_agents.sdd.stages.planner import TaskPlanner
from future_agents.sdd.stages.pm import PMStage
from future_agents.sdd.stages.qa import QAStage
from future_agents.sdd.stages.worker import WorkerBackend, WorkerStage, dry_run_backend

__all__ = [
    "ArchitectStage",
    "DeliveryStage",
    "PMStage",
    "QAStage",
    "TaskPlanner",
    "WorkerBackend",
    "WorkerStage",
    "dry_run_backend",
]
