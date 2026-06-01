"""Workflow automation API — n8n-like CRUD + execution endpoints.

Routes
------
POST   /api/workflows                    Create a workflow
GET    /api/workflows                    List / search workflows
GET    /api/workflows/templates          Browse built-in templates
GET    /api/workflows/templates/{id}     Get a single template (includes workflow JSON)
GET    /api/workflows/node-types         Reference for all node types + parameters
GET    /api/workflows/executions         Recent executions across all workflows
GET    /api/workflows/{id}               Get a workflow definition
PUT    /api/workflows/{id}               Update a workflow
DELETE /api/workflows/{id}               Delete a workflow
POST   /api/workflows/{id}/activate      Activate
POST   /api/workflows/{id}/deactivate    Deactivate
POST   /api/workflows/{id}/execute       Run manually
GET    /api/workflows/{id}/executions    Execution history for one workflow
GET    /api/executions/{execution_id}    Get full execution detail
POST   /api/webhooks/{workflow_id}       Webhook trigger endpoint
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel

from future_agents.workflows.engine import WorkflowEngine
from future_agents.workflows.models import (
    NodeType,
    WorkflowDefinition,
    WorkflowExecution,
)
from future_agents.workflows.store import execution_store, workflow_store
from future_agents.workflows.templates import BUILTIN_TEMPLATES, TEMPLATES_BY_ID

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Workflows"])

# ── Shared engine instance (no system-agent integration for now) ───────────────
_AGENTS_ROOT = str(Path(__file__).parent.parent.parent.parent / "agents")
_engine = WorkflowEngine(agents_root=_AGENTS_ROOT)


# ── Request / response helpers ─────────────────────────────────────────────────


class WorkflowCreateRequest(BaseModel):
    name: str
    description: str = ""
    nodes: list[dict] = []
    connections: list[dict] = []
    active: bool = True
    tags: list[str] = []


class WorkflowUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    nodes: Optional[list[dict]] = None
    connections: Optional[list[dict]] = None
    active: Optional[bool] = None
    tags: Optional[list[str]] = None


class ExecuteRequest(BaseModel):
    input_data: Any = None
    trigger: str = "manual"


# ── CRUD ────────────────────────────────────────────────────────────────────────


@router.post("/api/workflows", summary="Create a workflow")
def create_workflow(body: WorkflowCreateRequest) -> WorkflowDefinition:
    wf = WorkflowDefinition(**body.model_dump())
    return workflow_store.save(wf)


@router.get("/api/workflows", summary="List / search workflows")
def list_workflows(
    q: Optional[str] = Query(None, description="Search name/description"),
    tags: Optional[str] = Query(None, description="Comma-separated tag filter"),
    active_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    results = workflow_store.list(tags=tag_list, active_only=active_only, q=q)
    total = len(results)
    page = results[offset : offset + limit]
    return {"total": total, "offset": offset, "limit": limit, "workflows": page}


@router.get("/api/workflows/templates", summary="Browse built-in workflow templates")
def list_templates(
    category: Optional[str] = Query(None),
) -> list[dict]:
    templates = BUILTIN_TEMPLATES
    if category:
        templates = [t for t in templates if t.category == category]
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "category": t.category,
            "tags": t.tags,
            "node_count": len(t.workflow.nodes),
        }
        for t in templates
    ]


@router.get("/api/workflows/templates/{template_id}", summary="Get a built-in template with full workflow JSON")
def get_template(template_id: str) -> dict:
    tpl = TEMPLATES_BY_ID.get(template_id)
    if not tpl:
        raise HTTPException(404, f"Template '{template_id}' not found")
    return tpl.model_dump()


@router.get("/api/workflows/node-types", summary="Reference for all node types and their parameters")
def node_types() -> dict:
    return {
        "node_types": _NODE_TYPE_REFERENCE,
        "expression_syntax": {
            "description": "Use {{ expr }} in any string parameter for dynamic values",
            "examples": {
                "{{ input.field }}": "Access a field from current input",
                "{{ input['key'] }}": "Dict access",
                "{{ nodes['NodeName'].field }}": "Previous node output by name",
                "{{ workflow.id }}": "Workflow metadata",
                "{{ execution.id }}": "Execution ID",
                "{{ len(input.items) }}": "Python built-in in expression",
            },
        },
    }


@router.get("/api/workflows/executions", summary="Recent executions across all workflows")
def all_executions(limit: int = Query(50, ge=1, le=200)) -> list[WorkflowExecution]:
    return execution_store.list_all(limit=limit)


@router.get("/api/workflows/{workflow_id}", summary="Get a workflow definition")
def get_workflow(workflow_id: str) -> WorkflowDefinition:
    wf = workflow_store.get(workflow_id)
    if not wf:
        raise HTTPException(404, f"Workflow '{workflow_id}' not found")
    return wf


@router.put("/api/workflows/{workflow_id}", summary="Update a workflow")
def update_workflow(workflow_id: str, body: WorkflowUpdateRequest) -> WorkflowDefinition:
    existing = workflow_store.get(workflow_id)
    if not existing:
        raise HTTPException(404, f"Workflow '{workflow_id}' not found")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    updated = workflow_store.update(workflow_id, **updates)
    return updated


@router.delete("/api/workflows/{workflow_id}", summary="Delete a workflow")
def delete_workflow(workflow_id: str) -> dict:
    if not workflow_store.delete(workflow_id):
        raise HTTPException(404, f"Workflow '{workflow_id}' not found")
    return {"deleted": True, "workflow_id": workflow_id}


@router.post("/api/workflows/{workflow_id}/activate", summary="Activate a workflow")
def activate_workflow(workflow_id: str) -> WorkflowDefinition:
    wf = workflow_store.update(workflow_id, active=True)
    if not wf:
        raise HTTPException(404, f"Workflow '{workflow_id}' not found")
    return wf


@router.post("/api/workflows/{workflow_id}/deactivate", summary="Deactivate a workflow")
def deactivate_workflow(workflow_id: str) -> WorkflowDefinition:
    wf = workflow_store.update(workflow_id, active=False)
    if not wf:
        raise HTTPException(404, f"Workflow '{workflow_id}' not found")
    return wf


# ── Execution ───────────────────────────────────────────────────────────────────


@router.post("/api/workflows/{workflow_id}/execute", summary="Execute a workflow manually")
async def execute_workflow(
    workflow_id: str,
    body: ExecuteRequest = Body(default=ExecuteRequest()),
) -> WorkflowExecution:
    wf = workflow_store.get(workflow_id)
    if not wf:
        raise HTTPException(404, f"Workflow '{workflow_id}' not found")
    if not wf.active:
        raise HTTPException(400, f"Workflow '{workflow_id}' is inactive. Activate it first.")
    if not wf.nodes:
        raise HTTPException(400, "Workflow has no nodes")

    execution = await _engine.execute(wf, trigger_data=body.input_data, trigger=body.trigger)
    execution_store.save(execution)
    return execution


@router.get("/api/workflows/{workflow_id}/executions", summary="Execution history for a workflow")
def workflow_executions(
    workflow_id: str,
    limit: int = Query(20, ge=1, le=100),
) -> list[WorkflowExecution]:
    if not workflow_store.get(workflow_id):
        raise HTTPException(404, f"Workflow '{workflow_id}' not found")
    return execution_store.list_for_workflow(workflow_id, limit=limit)


@router.get("/api/executions/{execution_id}", summary="Get full execution detail with per-node results")
def get_execution(execution_id: str) -> WorkflowExecution:
    ex = execution_store.get(execution_id)
    if not ex:
        raise HTTPException(404, f"Execution '{execution_id}' not found")
    return ex


# ── Webhook trigger ─────────────────────────────────────────────────────────────


@router.post("/api/webhooks/{workflow_id}", summary="Webhook trigger — execute workflow with POST body as input")
async def webhook_trigger(workflow_id: str, body: Any = Body(default=None)) -> dict:
    wf = workflow_store.get(workflow_id)
    if not wf:
        raise HTTPException(404, f"Workflow '{workflow_id}' not found")
    if not wf.active:
        raise HTTPException(400, "Workflow is inactive")

    # Check that workflow has a webhook trigger node
    has_webhook = any(n.type == NodeType.WEBHOOK for n in wf.nodes)
    if not has_webhook:
        raise HTTPException(400, "Workflow has no webhook trigger node")

    execution = await _engine.execute(wf, trigger_data=body, trigger="webhook")
    execution_store.save(execution)

    return {
        "execution_id": execution.id,
        "status": execution.status,
        "output": execution.output_data,
        "duration_ms": execution.duration_ms,
    }


# ── From template ───────────────────────────────────────────────────────────────


@router.post("/api/workflows/from-template/{template_id}", summary="Create a new workflow from a built-in template")
def create_from_template(template_id: str, name: Optional[str] = Query(None)) -> WorkflowDefinition:
    tpl = TEMPLATES_BY_ID.get(template_id)
    if not tpl:
        raise HTTPException(404, f"Template '{template_id}' not found")

    import uuid

    wf_data = tpl.workflow.model_dump()
    wf_data["id"] = f"wf-{uuid.uuid4().hex[:8]}"
    wf_data["name"] = name or tpl.workflow.name
    from datetime import datetime, timezone

    wf_data["created_at"] = datetime.now(timezone.utc)
    wf_data["updated_at"] = datetime.now(timezone.utc)

    wf = WorkflowDefinition(**wf_data)
    return workflow_store.save(wf)


# ── Node type reference ────────────────────────────────────────────────────────

_NODE_TYPE_REFERENCE = {
    "triggers": {
        NodeType.MANUAL: {
            "description": "Entry point for manual / API-triggered executions. Passes input_data through.",
            "parameters": {},
        },
        NodeType.WEBHOOK: {
            "description": "Entry point for HTTP POST webhook calls (/api/webhooks/{workflow_id}). Body becomes input_data.",  # noqa: E501
            "parameters": {},
        },
        NodeType.SCHEDULE: {
            "description": "Cron-based trigger (schedule management coming soon). For manual runs treated as MANUAL.",
            "parameters": {
                "cron": "Cron expression e.g. '0 9 * * 1-5'",
                "timezone": "IANA timezone e.g. 'UTC'",
            },
        },
        NodeType.EVENT_TRIGGER: {
            "description": "Trigger on platform events. For manual runs treated as MANUAL.",
            "parameters": {
                "event_type": "Event type pattern e.g. 'capability.*'",
            },
        },
    },
    "agents": {
        NodeType.AGENT: {
            "description": "Invoke an IT role agent from the 10K catalog.",
            "parameters": {
                "agent_id": "Agent ID e.g. 'agent-00123' (mutually exclusive with agent_role)",
                "agent_role": "Role slug e.g. 'backend-development' — finds first matching agent",
                "prompt": "Task prompt (supports {{ expr }})",
                "context": "Optional dict of additional context",
            },
            "outputs": {"main": "agent_id, agent_name, prompt, response, guardrails_profile"},
        },
        NodeType.SYSTEM_AGENT: {
            "description": "Invoke a live system agent (capability, knowledge, policy, process, skills, master).",
            "parameters": {
                "agent_id": "One of: capability | knowledge | policy | process | skills | master",
                "intent": "Intent string e.g. 'capability.register'",
                "parameters": "Dict of intent parameters (supports {{ expr }} values)",
            },
            "outputs": {"main": "agent_id, intent, outcome, data, errors"},
        },
    },
    "http": {
        NodeType.HTTP_REQUEST: {
            "description": "Make an HTTP request to any URL.",
            "parameters": {
                "url": "Target URL (supports {{ expr }})",
                "method": "GET | POST | PUT | PATCH | DELETE (default GET)",
                "headers": "Dict of HTTP headers",
                "body": "Request body — dict is JSON-encoded automatically",
                "timeout_seconds": "Request timeout (default 30)",
            },
            "outputs": {"main": "status_code, body, url, method"},
        },
    },
    "control_flow": {
        NodeType.IF_CONDITION: {
            "description": "Branch execution based on a boolean condition.",
            "parameters": {
                "condition": 'Boolean expression e.g. "{{ input.score > 80 }}"',
            },
            "outputs": {
                "true": "Input data — taken when condition is truthy",
                "false": "Input data — taken when condition is falsy",
            },
        },
        NodeType.SWITCH: {
            "description": "Route to one of N output ports based on an expression value.",
            "parameters": {
                "expression": "Expression whose string value names the output port",
            },
            "outputs": {"<value>": "Input data routed to port matching expression result"},
        },
        NodeType.LOOP: {
            "description": "Iterate over an array and apply an inline transform to each item.",
            "parameters": {
                "items": 'Array expression e.g. "{{ input.tasks }}"',
                "item_var": "Variable name for current item (default 'item')",
                "transform": 'Expression returning transformed item e.g. "{{ item.name }}"',
            },
            "outputs": {"main": "Array of transformed items"},
        },
        NodeType.MERGE: {
            "description": "Wait for all incoming branches and combine their outputs into a list.",
            "parameters": {},
            "outputs": {"main": "List of all predecessor outputs"},
        },
    },
    "data": {
        NodeType.SET: {
            "description": "Set or override fields on the data object.",
            "parameters": {
                "values": "Dict of key: value to set (values support {{ expr }})",
                "mode": "'merge' (default) — extend input dict | 'replace' — return values only",
            },
            "outputs": {"main": "Modified data object"},
        },
        NodeType.FILTER: {
            "description": "Filter an array by a condition expression.",
            "parameters": {
                "items_path": "Expression resolving to array (optional — uses input if omitted)",
                "condition": "Boolean expression evaluated per item. Item available as item_var.",
                "item_var": "Variable name for current item (default 'item')",
            },
            "outputs": {"main": "Filtered array"},
        },
        NodeType.TRANSFORM: {
            "description": "Map input to a new structure using a field mapping.",
            "parameters": {
                "mapping": 'Dict of output_key: expression e.g. {"name": "{{ input.full_name }}"}',
            },
            "outputs": {"main": "Transformed object"},
        },
        NodeType.CODE: {
            "description": "Execute a Python snippet. Assign result to `output`.",
            "parameters": {
                "code": (
                    "Python code. `input` = current data. `nodes` = dict of previous outputs. "
                    "Assign result to `output`. Imports are blocked."
                ),
            },
            "outputs": {"main": "Value of `output` variable"},
        },
    },
    "output": {
        NodeType.RESPOND_WEBHOOK: {
            "description": "Mark data as the HTTP response for webhook-triggered executions.",
            "parameters": {
                "data": "Response data expression (default: pass input through)",
            },
        },
        NodeType.EMIT_EVENT: {
            "description": "Emit a named platform event.",
            "parameters": {
                "event_type": "Event type string e.g. 'workflow.completed'",
                "data": "Event payload (default: current input)",
            },
        },
        NodeType.STOP: {
            "description": "Terminate the workflow at this node and set execution output.",
            "parameters": {
                "output": "Final output data (default: pass input through)",
            },
        },
    },
}
