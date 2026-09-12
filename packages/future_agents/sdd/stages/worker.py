"""Worker stage — executes the DAG; a failure blocks only its dependents."""

from __future__ import annotations

import time
from typing import Callable, Optional

from future_agents.sdd.models import (
    Evidence,
    Spec,
    TaskGraph,
    TaskKind,
    TaskStatus,
    TaskUnit,
    WorkResult,
)

WorkerBackend = Callable[[TaskUnit, Spec], WorkResult]


def dry_run_backend(task: TaskUnit, spec: Spec) -> WorkResult:
    """Default backend: records what *would* happen, and says so in its evidence.

    The evidence is marked `simulated`, which QA refuses to count. A dry run that
    reported PASS would be the most dangerous output this system could produce.
    """
    del spec
    return WorkResult(
        task_id=task.id,
        status=TaskStatus.DONE,
        summary=f"[dry-run] {task.title}",
        engine=task.engine,
        evidence=[
            Evidence(
                kind="simulated",
                summary=f"[dry-run] {task.title}",
                exit_code=0,
                criterion_ids=list(task.criterion_ids),
                produced_by="dry_run_backend",
            )
        ],
        criterion_ids=list(task.criterion_ids) if task.kind is TaskKind.TEST else [],
        tests_added=[f"test_{task.id.lower().replace('-', '_')}"]
        if task.kind is TaskKind.TEST
        else [],
    )


class WorkerStage:
    """Executes the DAG in dependency order; a failure blocks only its dependents."""

    role = "worker_agent"

    def __init__(self, backend: Optional[WorkerBackend] = None) -> None:
        self.backend = backend or dry_run_backend

    def execute(
        self, graph: TaskGraph, spec: Spec, guard: Optional[object] = None
    ) -> list[WorkResult]:
        """Run the DAG. `guard` (a BudgetGuard) stops the run at its ceilings."""
        results: list[WorkResult] = []
        failed: set[str] = set()
        for task in graph.topological_order():
            if guard is not None:
                guard.charge_task()  # raises BudgetExceeded, which the caller records
            if failed.intersection(task.depends_on):
                task.status = TaskStatus.BLOCKED
                results.append(
                    WorkResult(
                        task_id=task.id,
                        status=TaskStatus.BLOCKED,
                        summary="upstream task failed",
                    )
                )
                failed.add(task.id)
                continue

            task.status = TaskStatus.RUNNING
            started = time.perf_counter()
            try:
                result = self.backend(task, spec)
            except Exception as exc:  # a backend crash is a task failure, not a run crash
                result = WorkResult(task_id=task.id, status=TaskStatus.FAILED, error=str(exc)[:500])
            result.duration_ms = round((time.perf_counter() - started) * 1000, 3)
            task.status = result.status
            if result.status in (TaskStatus.FAILED, TaskStatus.BLOCKED):
                failed.add(task.id)
            results.append(result)
        return results
