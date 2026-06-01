"""In-memory stores for workflow definitions and execution history.

Both stores are module-level singletons so all API routes share the same state.
For production use, swap these for database-backed implementations.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from future_agents.workflows.models import WorkflowDefinition, WorkflowExecution


class WorkflowStore:
    """CRUD store for workflow definitions."""

    def __init__(self) -> None:
        self._workflows: dict[str, WorkflowDefinition] = {}

    def save(self, workflow: WorkflowDefinition) -> WorkflowDefinition:
        workflow.updated_at = datetime.now(timezone.utc)
        self._workflows[workflow.id] = workflow
        return workflow

    def get(self, workflow_id: str) -> Optional[WorkflowDefinition]:
        return self._workflows.get(workflow_id)

    def list(
        self,
        tags: Optional[list[str]] = None,
        active_only: bool = False,
        q: Optional[str] = None,
    ) -> list[WorkflowDefinition]:
        workflows = list(self._workflows.values())
        if active_only:
            workflows = [w for w in workflows if w.active]
        if tags:
            workflows = [w for w in workflows if any(t in w.tags for t in tags)]
        if q:
            q_lower = q.lower()
            workflows = [w for w in workflows if q_lower in w.name.lower() or q_lower in w.description.lower()]
        return sorted(workflows, key=lambda w: w.updated_at, reverse=True)

    def update(self, workflow_id: str, **fields) -> Optional[WorkflowDefinition]:
        wf = self._workflows.get(workflow_id)
        if not wf:
            return None
        data = wf.model_dump()
        data.update(fields)
        data["updated_at"] = datetime.now(timezone.utc)
        data["version"] = wf.version + 1
        updated = WorkflowDefinition(**data)
        self._workflows[workflow_id] = updated
        return updated

    def delete(self, workflow_id: str) -> bool:
        if workflow_id in self._workflows:
            del self._workflows[workflow_id]
            return True
        return False

    def count(self) -> int:
        return len(self._workflows)


class ExecutionStore:
    """Store for workflow execution history."""

    def __init__(self, max_per_workflow: int = 100) -> None:
        self._executions: dict[str, WorkflowExecution] = {}
        self._by_workflow: dict[str, list[str]] = defaultdict(list)
        self.max_per_workflow = max_per_workflow

    def save(self, execution: WorkflowExecution) -> WorkflowExecution:
        self._executions[execution.id] = execution
        history = self._by_workflow[execution.workflow_id]
        if execution.id not in history:
            history.append(execution.id)
        # Trim oldest if over limit
        while len(history) > self.max_per_workflow:
            oldest_id = history.pop(0)
            self._executions.pop(oldest_id, None)
        return execution

    def get(self, execution_id: str) -> Optional[WorkflowExecution]:
        return self._executions.get(execution_id)

    def list_for_workflow(self, workflow_id: str, limit: int = 20) -> list[WorkflowExecution]:
        ids = self._by_workflow.get(workflow_id, [])
        execs = [self._executions[eid] for eid in ids if eid in self._executions]
        return sorted(execs, key=lambda e: e.started_at, reverse=True)[:limit]

    def list_all(self, limit: int = 50) -> list[WorkflowExecution]:
        execs = list(self._executions.values())
        return sorted(execs, key=lambda e: e.started_at, reverse=True)[:limit]

    def count(self) -> int:
        return len(self._executions)


# ── Module-level singletons ────────────────────────────────────────────────────
workflow_store = WorkflowStore()
execution_store = ExecutionStore()
