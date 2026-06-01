"""Pre-built workflow templates — one per common IT automation pattern."""

from __future__ import annotations

from future_agents.workflows.models import (
    NodePosition,
    NodeType,
    WorkflowConnection,
    WorkflowDefinition,
    WorkflowNode,
    WorkflowTemplate,
)

# ── Helper ─────────────────────────────────────────────────────────────────────


def _node(node_id: str, ntype: NodeType, name: str, x: float, y: float, **params) -> WorkflowNode:
    return WorkflowNode(
        id=node_id,
        type=ntype,
        name=name,
        parameters=params if params else {},
        position=NodePosition(x=x, y=y),
    )


def _conn(src: str, tgt: str, src_port: str = "main") -> WorkflowConnection:
    return WorkflowConnection(source_node=src, source_output=src_port, target_node=tgt)


# ── Template definitions ───────────────────────────────────────────────────────


def _tpl_agent_search() -> WorkflowTemplate:
    return WorkflowTemplate(
        id="tpl-agent-search-notify",
        name="Agent Search → Transform → Notify",
        description=(
            "Receive a task description via webhook, call a role agent, "
            "transform the result, and emit a platform event."
        ),
        category="agents",
        tags=["webhook", "agent", "event"],
        workflow=WorkflowDefinition(
            id="wf-tpl-agent-search",
            name="Agent Search & Notify",
            description="Search for an agent role and emit result as event",
            nodes=[
                _node("n1", NodeType.WEBHOOK, "Webhook Trigger", 100, 200),
                _node(
                    "n2",
                    NodeType.AGENT,
                    "Call Role Agent",
                    350,
                    200,
                    agent_role="{{ input.role }}",
                    prompt="{{ input.task }}",
                ),
                _node(
                    "n3",
                    NodeType.TRANSFORM,
                    "Shape Output",
                    600,
                    200,
                    mapping={
                        "agent": "{{ nodes['Call Role Agent'].agent_name }}",
                        "response": "{{ nodes['Call Role Agent'].response }}",
                        "profile": "{{ nodes['Call Role Agent'].guardrails_profile }}",
                    },
                ),
                _node(
                    "n4",
                    NodeType.EMIT_EVENT,
                    "Emit Event",
                    850,
                    200,
                    event_type="workflow.agent_result",
                    data="{{ input }}",
                ),
            ],
            connections=[
                _conn("n1", "n2"),
                _conn("n2", "n3"),
                _conn("n3", "n4"),
            ],
            tags=["webhook", "agent", "event"],
        ),
    )


def _tpl_guardrails_check() -> WorkflowTemplate:
    return WorkflowTemplate(
        id="tpl-guardrails-pipeline",
        name="Guardrails Check Pipeline",
        description=(
            "Run a guardrails check on code context. If violations are found, escalate; otherwise mark as clean."
        ),
        category="guardrails",
        tags=["security", "guardrails", "if-condition"],
        workflow=WorkflowDefinition(
            id="wf-tpl-guardrails",
            name="Guardrails Check Pipeline",
            description="Policy check with escalation on violation",
            nodes=[
                _node("n1", NodeType.MANUAL, "Start", 100, 200),
                _node(
                    "n2",
                    NodeType.SYSTEM_AGENT,
                    "Check Policy",
                    350,
                    200,
                    agent_id="policy",
                    intent="policy.check",
                    parameters={
                        "action": "{{ input.action }}",
                        "context": "{{ input.context }}",
                    },
                ),
                _node(
                    "n3",
                    NodeType.IF_CONDITION,
                    "Violations?",
                    600,
                    200,
                    condition="{{ input.data.get('allowed', True) == False if isinstance(input, dict) else False }}",
                ),
                _node(
                    "n4",
                    NodeType.SET,
                    "Flag Violation",
                    850,
                    100,
                    values={"status": "BLOCKED", "escalated": True},
                    mode="merge",
                ),
                _node(
                    "n5",
                    NodeType.SET,
                    "Mark Clean",
                    850,
                    300,
                    values={"status": "ALLOWED", "escalated": False},
                    mode="merge",
                ),
                _node("n6", NodeType.MERGE, "Merge Results", 1100, 200),
                _node("n7", NodeType.STOP, "Done", 1300, 200),
            ],
            connections=[
                _conn("n1", "n2"),
                _conn("n2", "n3"),
                _conn("n3", "n4", "true"),
                _conn("n3", "n5", "false"),
                _conn("n4", "n6"),
                _conn("n5", "n6"),
                _conn("n6", "n7"),
            ],
            tags=["guardrails", "policy", "branching"],
        ),
    )


def _tpl_capability_onboarding() -> WorkflowTemplate:
    return WorkflowTemplate(
        id="tpl-capability-onboarding",
        name="New Employee Capability Onboarding",
        description=(
            "Register a new employee's capabilities, analyse gaps against a target role, and log the growth plan."
        ),
        category="hr",
        tags=["capability", "knowledge", "onboarding"],
        workflow=WorkflowDefinition(
            id="wf-tpl-onboarding",
            name="Capability Onboarding",
            description="Register capabilities and analyse gaps for new hires",
            nodes=[
                _node("n1", NodeType.WEBHOOK, "New Employee Webhook", 100, 200),
                _node(
                    "n2",
                    NodeType.SYSTEM_AGENT,
                    "Register Capabilities",
                    350,
                    200,
                    agent_id="capability",
                    intent="capability.register",
                    parameters={
                        "name": "{{ input.capability }}",
                        "level": "{{ input.level or 'novice' }}",
                        "domain": "{{ input.domain or 'general' }}",
                    },
                ),
                _node(
                    "n3",
                    NodeType.SYSTEM_AGENT,
                    "Gap Analysis",
                    600,
                    200,
                    agent_id="capability",
                    intent="capability.gap_analysis",
                    parameters={
                        "role": "{{ input.target_role }}",
                        "current_capabilities": [],
                    },
                ),
                _node(
                    "n4",
                    NodeType.SYSTEM_AGENT,
                    "Store Knowledge",
                    850,
                    200,
                    agent_id="knowledge",
                    intent="knowledge.add",
                    parameters={
                        "content": "Gap analysis for {{ input.employee_name }}",
                        "domain": "hr",
                        "tags": ["onboarding", "gap-analysis"],
                    },
                ),
                _node("n5", NodeType.STOP, "Complete", 1100, 200),
            ],
            connections=[
                _conn("n1", "n2"),
                _conn("n2", "n3"),
                _conn("n3", "n4"),
                _conn("n4", "n5"),
            ],
            tags=["hr", "capability", "knowledge"],
        ),
    )


def _tpl_http_enrich() -> WorkflowTemplate:
    return WorkflowTemplate(
        id="tpl-http-enrich-agent",
        name="HTTP Enrich → Agent Decision",
        description=(
            "Fetch data from an external API, enrich the payload, pass it "
            "to a backend agent for analysis, then branch on confidence score."
        ),
        category="integration",
        tags=["http", "agent", "switch"],
        workflow=WorkflowDefinition(
            id="wf-tpl-http-enrich",
            name="HTTP Enrich + Agent Decision",
            description="Enrich data from external API and route by confidence",
            nodes=[
                _node("n1", NodeType.MANUAL, "Start", 100, 200),
                _node(
                    "n2",
                    NodeType.HTTP_REQUEST,
                    "Fetch External Data",
                    350,
                    200,
                    method="GET",
                    url="{{ input.api_url }}",
                    headers={"Accept": "application/json"},
                ),
                _node(
                    "n3",
                    NodeType.SET,
                    "Enrich Payload",
                    600,
                    200,
                    values={
                        "raw_data": "{{ input.body }}",
                        "source_url": "{{ input.url }}",
                        "fetched_at": "{{ str(workflow.id) }}",
                    },
                    mode="replace",
                ),
                _node(
                    "n4",
                    NodeType.AGENT,
                    "Analyse with Backend Agent",
                    850,
                    200,
                    agent_role="backend-development",
                    prompt="Analyse this data: {{ input.raw_data }}",
                ),
                _node(
                    "n5",
                    NodeType.SWITCH,
                    "Route by Profile",
                    1100,
                    200,
                    expression="{{ input.guardrails_profile }}",
                ),
                _node("n6", NodeType.SET, "Strict Path", 1350, 100, values={"path": "strict"}, mode="merge"),
                _node("n7", NodeType.SET, "Standard Path", 1350, 200, values={"path": "standard"}, mode="merge"),
                _node("n8", NodeType.SET, "Relaxed Path", 1350, 300, values={"path": "relaxed"}, mode="merge"),
                _node("n9", NodeType.MERGE, "Collect Results", 1600, 200),
            ],
            connections=[
                _conn("n1", "n2"),
                _conn("n2", "n3"),
                _conn("n3", "n4"),
                _conn("n4", "n5"),
                _conn("n5", "n6", "strict"),
                _conn("n5", "n7", "standard"),
                _conn("n5", "n8", "relaxed"),
                _conn("n6", "n9"),
                _conn("n7", "n9"),
                _conn("n8", "n9"),
            ],
            tags=["http", "agent", "switch", "merge"],
        ),
    )


def _tpl_batch_process() -> WorkflowTemplate:
    return WorkflowTemplate(
        id="tpl-batch-loop",
        name="Batch Process Agent List",
        description=(
            "Receive a list of tasks, loop over each, run a system agent, "
            "then filter and return only successful results."
        ),
        category="batch",
        tags=["loop", "filter", "system-agent"],
        workflow=WorkflowDefinition(
            id="wf-tpl-batch",
            name="Batch Agent Processing",
            description="Loop, process, filter",
            nodes=[
                _node("n1", NodeType.MANUAL, "Start", 100, 200),
                _node(
                    "n2",
                    NodeType.LOOP,
                    "Loop Over Tasks",
                    350,
                    200,
                    items="{{ input.tasks }}",
                    item_var="item",
                    transform="{{ {'task': item, 'status': 'pending'} }}",
                ),
                _node(
                    "n3",
                    NodeType.FILTER,
                    "Keep Pending Only",
                    600,
                    200,
                    condition="{{ item.get('status') == 'pending' }}",
                ),
                _node(
                    "n4",
                    NodeType.CODE,
                    "Count Results",
                    850,
                    200,
                    code=(
                        "output = {\n"
                        "    'total': len(input),\n"
                        "    'items': input,\n"
                        "    'summary': f'{len(input)} pending tasks processed'\n"
                        "}"
                    ),
                ),
                _node("n5", NodeType.STOP, "Done", 1100, 200),
            ],
            connections=[
                _conn("n1", "n2"),
                _conn("n2", "n3"),
                _conn("n3", "n4"),
                _conn("n4", "n5"),
            ],
            tags=["loop", "filter", "code"],
        ),
    )


# ── Public registry ────────────────────────────────────────────────────────────

BUILTIN_TEMPLATES: list[WorkflowTemplate] = [
    _tpl_agent_search(),
    _tpl_guardrails_check(),
    _tpl_capability_onboarding(),
    _tpl_http_enrich(),
    _tpl_batch_process(),
]

TEMPLATES_BY_ID: dict[str, WorkflowTemplate] = {t.id: t for t in BUILTIN_TEMPLATES}
