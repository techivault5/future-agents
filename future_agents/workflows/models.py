"""Workflow data models — definitions, nodes, connections, and execution state."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Node types ────────────────────────────────────────────────────────────────

class NodeType(str, Enum):
    # Triggers (entry points)
    MANUAL = "manual"
    WEBHOOK = "webhook"
    SCHEDULE = "schedule"
    EVENT_TRIGGER = "event_trigger"

    # Agent invocation
    AGENT = "agent"             # IT role agent (10K catalog)
    SYSTEM_AGENT = "system_agent"  # Live system agent (capability, knowledge, etc.)

    # HTTP / external
    HTTP_REQUEST = "http_request"

    # Control flow
    IF_CONDITION = "if_condition"
    SWITCH = "switch"
    LOOP = "loop"
    MERGE = "merge"

    # Data manipulation
    SET = "set"
    FILTER = "filter"
    TRANSFORM = "transform"
    CODE = "code"

    # Output / side effects
    RESPOND_WEBHOOK = "respond_webhook"
    EMIT_EVENT = "emit_event"
    STOP = "stop"


# ── Workflow definition ───────────────────────────────────────────────────────

class NodePosition(BaseModel):
    x: float = 0.0
    y: float = 0.0


class WorkflowNode(BaseModel):
    """A single node in the workflow graph."""

    id: str
    type: NodeType
    name: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    position: NodePosition = Field(default_factory=NodePosition)
    disabled: bool = False
    notes: str = ""


class WorkflowConnection(BaseModel):
    """Directed edge between two nodes.

    ``source_output`` selects which output port to follow:
    - ``"main"``  — default output
    - ``"true"`` / ``"false"`` — IF_CONDITION branches
    - case value — SWITCH branches
    """

    source_node: str
    source_output: str = "main"
    target_node: str
    target_input: str = "main"


class WorkflowDefinition(BaseModel):
    """A complete workflow graph that can be executed."""

    id: str = Field(default_factory=lambda: f"wf-{uuid.uuid4().hex[:8]}")
    name: str
    description: str = ""
    nodes: list[WorkflowNode] = Field(default_factory=list)
    connections: list[WorkflowConnection] = Field(default_factory=list)
    active: bool = True
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    version: int = 1


# ── Execution state ───────────────────────────────────────────────────────────

class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NodeExecution(BaseModel):
    """Execution record for a single node within a workflow run."""

    node_id: str
    node_name: str
    node_type: str
    status: ExecutionStatus
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    input_data: Any = None
    output_data: Any = None
    output_port: str = "main"
    error: Optional[str] = None
    duration_ms: Optional[float] = None


class WorkflowExecution(BaseModel):
    """A single run of a workflow, with per-node results."""

    id: str = Field(default_factory=lambda: f"exec-{uuid.uuid4().hex[:8]}")
    workflow_id: str
    workflow_name: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    trigger: str = "manual"
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None
    node_executions: list[NodeExecution] = Field(default_factory=list)
    input_data: Any = None
    output_data: Any = None
    error: Optional[str] = None
    duration_ms: Optional[float] = None


# ── Built-in templates ────────────────────────────────────────────────────────

class WorkflowTemplate(BaseModel):
    """A pre-built workflow template."""

    id: str
    name: str
    description: str
    category: str
    tags: list[str]
    workflow: WorkflowDefinition
