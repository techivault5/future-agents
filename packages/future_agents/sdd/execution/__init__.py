"""Execution — real work, inside a fence, under a budget.

    backend = DispatchBackend(dispatcher, repo_root=".", plan=plan, forbidden=zones)
    pipeline = DeliveryPipeline(config, backend=backend, repo_root=".")

`ToolchainBackend` runs the repository's own commands with no model involved —
the honest floor to measure any agent against.
"""

from future_agents.sdd.execution.backends import (
    KIND_COMMANDS,
    CompositeBackend,
    DispatchBackend,
    ToolchainBackend,
)
from future_agents.sdd.execution.resilience import (
    BudgetExceeded,
    BudgetGuard,
    CircuitBreaker,
    CircuitOpen,
    LoopDetector,
    retry,
)
from future_agents.sdd.execution.sandbox import HARD_DENY, SandboxViolation, WorkspacePolicy

__all__ = [
    "BudgetExceeded",
    "BudgetGuard",
    "CircuitBreaker",
    "CircuitOpen",
    "CompositeBackend",
    "DispatchBackend",
    "HARD_DENY",
    "KIND_COMMANDS",
    "LoopDetector",
    "SandboxViolation",
    "ToolchainBackend",
    "WorkspacePolicy",
    "retry",
]
