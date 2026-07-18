"""Workflow execution engine — DAG runner with per-node handlers.

Execution model (n8n-inspired):
- Each node receives ``input_data`` from its predecessor(s).
- After execution a node emits ``output_data`` on a named *port* (default ``"main"``).
- Connections filter by ``source_output`` port so IF / SWITCH nodes can branch.
- MERGE waits for every predecessor that has been activated before executing.

Expression syntax inside parameter strings:
    {{ input.field }}          — current input data
    {{ nodes['MyNode'].field }} — previous node output by name or id
    {{ workflow.id }}          — workflow metadata
    {{ execution.id }}         — execution metadata
"""

from __future__ import annotations

import ast
import json
import logging
import re
import time
import urllib.request
import urllib.error
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

from future_agents.workflows.models import (
    ExecutionStatus,
    NodeExecution,
    NodeType,
    WorkflowDefinition,
    WorkflowExecution,
)

logger = logging.getLogger(__name__)

# ── Expression evaluation ─────────────────────────────────────────────────────

_SAFE_BUILTINS: dict[str, Any] = {
    "len": len, "str": str, "int": int, "float": float,
    "bool": bool, "list": list, "dict": dict, "set": set,
    "tuple": tuple, "range": range, "enumerate": enumerate,
    "zip": zip, "map": map, "filter": filter,
    "min": min, "max": max, "sum": sum,
    "any": any, "all": all,
    "sorted": sorted, "reversed": reversed,
    "abs": abs, "round": round,
    "True": True, "False": False, "None": None,
}


def _eval_expr(expr: str, ctx_vars: dict) -> Any:
    """Evaluate ``expr`` in a restricted namespace."""
    try:
        # Validate AST before eval to block dangerous constructs
        tree = ast.parse(expr, mode="eval")
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef,
                                  ast.AsyncFunctionDef, ast.ClassDef)):
                return expr
        return eval(expr, {"__builtins__": _SAFE_BUILTINS}, ctx_vars)  # noqa: S307
    except Exception:
        return expr


def _resolve(value: Any, ctx_vars: dict) -> Any:
    """Recursively resolve ``{{ expr }}`` templates inside ``value``."""
    if isinstance(value, str):
        # Entire string is a single expression → preserve type
        m = re.fullmatch(r"\{\{\s*(.*?)\s*\}\}", value.strip())
        if m:
            return _eval_expr(m.group(1), ctx_vars)
        # Inline templates: replace each {{ … }} with its string representation
        def _sub(match: re.Match) -> str:
            result = _eval_expr(match.group(1).strip(), ctx_vars)
            return "" if result is None else str(result)
        return re.sub(r"\{\{(.*?)\}\}", _sub, value)
    if isinstance(value, dict):
        return {k: _resolve(v, ctx_vars) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(item, ctx_vars) for item in value]
    return value


# ── Execution context ─────────────────────────────────────────────────────────

class _ExecCtx:
    """Mutable context threaded through a single workflow execution."""

    def __init__(
        self,
        execution_id: str,
        workflow: WorkflowDefinition,
        input_data: Any = None,
    ) -> None:
        self.execution_id = execution_id
        self.workflow = workflow
        self.input_data = input_data
        self._outputs: dict[str, Any] = {}   # node_id -> output data
        self._ports: dict[str, str] = {}     # node_id -> output port used
        self._by_id: dict[str, Any] = {n.id: n for n in workflow.nodes}
        self._by_name: dict[str, Any] = {n.name: n for n in workflow.nodes}

    def set_output(self, node_id: str, data: Any, port: str = "main") -> None:
        self._outputs[node_id] = data
        self._ports[node_id] = port

    def get_output(self, node_id: str) -> Any:
        return self._outputs.get(node_id)

    def get_port(self, node_id: str) -> str:
        return self._ports.get(node_id, "main")

    def template_vars(self, current_input: Any) -> dict:
        nodes: dict[str, Any] = {}
        for nid, data in self._outputs.items():
            nodes[nid] = data
            node = self._by_id.get(nid)
            if node:
                nodes[node.name] = data
        return {
            "input": current_input,
            "nodes": nodes,
            "workflow": {"id": self.workflow.id, "name": self.workflow.name},
            "execution": {"id": self.execution_id},
        }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _deep_merge(base: Any, patch: Any) -> Any:
    """Shallow merge: patch overrides keys in base dict."""
    if isinstance(base, dict) and isinstance(patch, dict):
        merged = dict(base)
        merged.update(patch)
        return merged
    return patch


# ── Engine ─────────────────────────────────────────────────────────────────────

class WorkflowEngine:
    """Execute workflow definitions as directed acyclic graphs.

    Parameters
    ----------
    agent_system_factory:
        Optional callable that returns an initialised ``AgentSystem`` instance.
        Required for ``system_agent`` nodes.  Pass ``None`` to skip agent calls.
    agents_root:
        Path to the directory containing agent YAML files (for ``agent`` nodes).
    """

    _TRIGGER_TYPES = frozenset({
        NodeType.WEBHOOK,
        NodeType.SCHEDULE,
        NodeType.EVENT_TRIGGER,
        NodeType.MANUAL,
    })

    def __init__(
        self,
        agent_system_factory=None,
        agents_root: str | None = None,
    ) -> None:
        self._agent_system_factory = agent_system_factory
        self._agents_root = agents_root

    # ── Public entry point ────────────────────────────────────────────────────

    async def execute(
        self,
        workflow: WorkflowDefinition,
        trigger_data: Any = None,
        trigger: str = "manual",
    ) -> WorkflowExecution:
        """Run *workflow* and return a completed ``WorkflowExecution``."""
        t0 = time.perf_counter()
        execution = WorkflowExecution(
            workflow_id=workflow.id,
            workflow_name=workflow.name,
            status=ExecutionStatus.RUNNING,
            trigger=trigger,
            input_data=trigger_data,
        )
        ctx = _ExecCtx(execution.id, workflow, trigger_data)

        try:
            await self._run(workflow, trigger_data, ctx, execution)
        except Exception as exc:
            logger.exception("Unexpected engine error for workflow %s", workflow.id)
            execution.status = ExecutionStatus.FAILED
            execution.error = str(exc)

        execution.finished_at = datetime.now(timezone.utc)
        execution.duration_ms = (time.perf_counter() - t0) * 1000

        if execution.status == ExecutionStatus.RUNNING:
            execution.status = ExecutionStatus.SUCCESS
            # Output = last successful node's output
            for ne in reversed(execution.node_executions):
                if ne.status == ExecutionStatus.SUCCESS:
                    execution.output_data = ne.output_data
                    break

        return execution

    # ── Graph traversal ────────────────────────────────────────────────────────

    async def _run(
        self,
        workflow: WorkflowDefinition,
        trigger_data: Any,
        ctx: _ExecCtx,
        execution: WorkflowExecution,
    ) -> None:
        nodes_by_id = {n.id: n for n in workflow.nodes if not n.disabled}

        # Build out-edges: source_id -> [(source_port, target_id)]
        out_edges: dict[str, list[tuple[str, str]]] = defaultdict(list)
        # Count *active* (non-disabled) incoming connections per node
        in_count: dict[str, int] = defaultdict(int)
        for conn in workflow.connections:
            if conn.source_node in nodes_by_id and conn.target_node in nodes_by_id:
                out_edges[conn.source_node].append((conn.source_output, conn.target_node))
                in_count[conn.target_node] += 1

        # Nodes with no incoming edges, OR explicitly typed as triggers
        start_nodes = [
            n for n in nodes_by_id.values()
            if n.type in self._TRIGGER_TYPES or in_count[n.id] == 0
        ]
        if not start_nodes:
            start_nodes = list(nodes_by_id.values())[:1]

        # MERGE accumulator: node_id -> {predecessor_id: data}
        merge_acc: dict[str, dict[str, Any]] = defaultdict(dict)
        # How many active predecessors does each MERGE node expect?
        merge_expect: dict[str, int] = {
            n.id: in_count[n.id]
            for n in nodes_by_id.values()
            if n.type == NodeType.MERGE and in_count[n.id] > 0
        }

        # BFS queue: (node, input_data)
        queue: deque[tuple[Any, Any]] = deque(
            (n, trigger_data) for n in start_nodes
        )
        visited: set[str] = set()

        while queue:
            node, input_data = queue.popleft()

            if node.id in visited:
                continue
            visited.add(node.id)

            # Execute node
            ne = await self._execute_node(node, input_data, ctx)
            execution.node_executions.append(ne)
            ctx.set_output(node.id, ne.output_data, ne.output_port)

            if ne.status == ExecutionStatus.FAILED:
                execution.status = ExecutionStatus.FAILED
                execution.error = ne.error
                return

            if node.type == NodeType.STOP:
                execution.output_data = ne.output_data
                return

            # Route to successor nodes
            output_port = ne.output_port
            for src_port, target_id in out_edges[node.id]:
                target = nodes_by_id.get(target_id)
                if not target:
                    continue

                # Branching nodes: only follow matching port
                if node.type in (NodeType.IF_CONDITION, NodeType.SWITCH):
                    if src_port != output_port:
                        continue

                if target.type == NodeType.MERGE:
                    merge_acc[target.id][node.id] = ne.output_data
                    expected = merge_expect.get(target.id, 1)
                    if len(merge_acc[target.id]) >= expected:
                        queue.append((target, list(merge_acc[target.id].values())))
                else:
                    queue.append((target, ne.output_data))

    # ── Node dispatcher ───────────────────────────────────────────────────────

    async def _execute_node(
        self,
        node: Any,
        input_data: Any,
        ctx: _ExecCtx,
    ) -> NodeExecution:
        t0 = time.perf_counter()
        ne = NodeExecution(
            node_id=node.id,
            node_name=node.name,
            node_type=node.type.value,
            status=ExecutionStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
            input_data=input_data,
            output_port="main",
        )

        params = _resolve(node.parameters, ctx.template_vars(input_data))

        try:
            handler = self._handlers().get(node.type)
            if handler is None:
                ne.output_data = input_data
            else:
                output_data, output_port = await handler(params, input_data, ctx)
                ne.output_data = output_data
                ne.output_port = output_port
            ne.status = ExecutionStatus.SUCCESS
        except Exception as exc:
            logger.warning("Node %r (%s) failed: %s", node.name, node.type.value, exc)
            ne.status = ExecutionStatus.FAILED
            ne.error = str(exc)
            ne.output_data = input_data  # pass-through on error so graph can continue

        ne.finished_at = datetime.now(timezone.utc)
        ne.duration_ms = (time.perf_counter() - t0) * 1000
        return ne

    # ── Handler registry ──────────────────────────────────────────────────────

    def _handlers(self):
        return {
            # Triggers — mostly pass-through
            NodeType.MANUAL: self._h_manual,
            NodeType.WEBHOOK: self._h_manual,
            NodeType.SCHEDULE: self._h_manual,
            NodeType.EVENT_TRIGGER: self._h_manual,
            # Agents
            NodeType.AGENT: self._h_agent,
            NodeType.SYSTEM_AGENT: self._h_system_agent,
            # HTTP
            NodeType.HTTP_REQUEST: self._h_http_request,
            # Control flow
            NodeType.IF_CONDITION: self._h_if_condition,
            NodeType.SWITCH: self._h_switch,
            NodeType.LOOP: self._h_loop,
            NodeType.MERGE: self._h_merge,
            # Data
            NodeType.SET: self._h_set,
            NodeType.FILTER: self._h_filter,
            NodeType.TRANSFORM: self._h_transform,
            NodeType.CODE: self._h_code,
            # Output / side-effects
            NodeType.RESPOND_WEBHOOK: self._h_respond_webhook,
            NodeType.EMIT_EVENT: self._h_emit_event,
            NodeType.STOP: self._h_stop,
        }

    # ── Trigger handlers ───────────────────────────────────────────────────────

    async def _h_manual(self, params, input_data, ctx):
        return input_data, "main"

    # ── Agent handlers ─────────────────────────────────────────────────────────

    async def _h_agent(self, params, input_data, ctx):
        """Invoke an IT role agent from the 10K catalog (simulated response)."""
        agent_id = params.get("agent_id", "")
        agent_role = params.get("agent_role", "")
        prompt = params.get("prompt", str(input_data) if input_data is not None else "")
        context = params.get("context", {})

        agent_def = None
        if self._agents_root and (agent_id or agent_role):
            import yaml
            from pathlib import Path

            root = Path(self._agents_root)
            if agent_id:
                for yaml_file in root.rglob(f"{agent_id}.yaml"):
                    with open(yaml_file) as f:
                        agent_def = yaml.safe_load(f)
                    break
            elif agent_role:
                # Find first YAML with matching role
                for yaml_file in root.rglob("agent-*.yaml"):
                    with open(yaml_file) as f:
                        data = yaml.safe_load(f)
                    if data.get("role") == agent_role:
                        agent_def = data
                        break

        result = {
            "agent_id": agent_id or agent_role or "unknown",
            "agent_name": agent_def.get("name") if agent_def else agent_id,
            "prompt": prompt,
            "response": (
                f"[{agent_def['name']}] Processed: {prompt}"
                if agent_def
                else f"Agent '{agent_id or agent_role}' processed: {prompt}"
            ),
            "context": context,
            "guardrails_profile": agent_def.get("guardrails_profile", "standard") if agent_def else "standard",
        }
        return result, "main"

    async def _h_system_agent(self, params, input_data, ctx):
        """Invoke a live system agent (capability, knowledge, policy, …)."""
        agent_id = params.get("agent_id", "master")
        intent = params.get("intent", "master.status")
        agent_params = params.get("parameters", {})

        if not isinstance(agent_params, dict):
            agent_params = {}

        if self._agent_system_factory is None:
            return {
                "agent_id": agent_id,
                "intent": intent,
                "result": f"[simulated] {agent_id}.{intent}",
                "parameters": agent_params,
            }, "main"

        try:
            system = await self._agent_system_factory()
            result = await system.handle(intent, agent_params)
            return {
                "agent_id": agent_id,
                "intent": intent,
                "outcome": result.outcome.value,
                "data": result.data,
                "errors": result.errors,
            }, "main"
        except Exception as exc:
            raise RuntimeError(f"System agent {agent_id!r} failed: {exc}") from exc

    # ── HTTP handler ───────────────────────────────────────────────────────────

    async def _h_http_request(self, params, input_data, ctx):
        """Make an HTTP request using stdlib urllib."""
        method = str(params.get("method", "GET")).upper()
        url = str(params.get("url", ""))
        headers: dict = params.get("headers") or {}
        body = params.get("body")
        timeout = int(params.get("timeout_seconds", 30))

        if not url:
            raise ValueError("http_request node requires a 'url' parameter")

        # Encode body
        body_bytes: bytes | None = None
        if body is not None:
            if isinstance(body, (dict, list)):
                body_bytes = json.dumps(body).encode()
                headers.setdefault("Content-Type", "application/json")
            else:
                body_bytes = str(body).encode()

        req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                raw = resp.read()
                content_type = resp.headers.get("Content-Type", "")
                status_code = resp.status
                try:
                    response_body = json.loads(raw)
                except json.JSONDecodeError:
                    response_body = raw.decode(errors="replace")
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                response_body = json.loads(raw)
            except json.JSONDecodeError:
                response_body = raw.decode(errors="replace")
            status_code = exc.code
            content_type = ""

        result = {
            "status_code": status_code,
            "body": response_body,
            "url": url,
            "method": method,
        }
        return result, "main"

    # ── Control flow handlers ──────────────────────────────────────────────────

    async def _h_if_condition(self, params, input_data, ctx):
        """Branch to 'true' or 'false' output port based on a condition."""
        condition = params.get("condition", "True")
        ctx_vars = ctx.template_vars(input_data)

        if isinstance(condition, bool):
            result = condition
        elif isinstance(condition, str):
            result = bool(_eval_expr(condition, ctx_vars))
        else:
            result = bool(condition)

        port = "true" if result else "false"
        return input_data, port

    async def _h_switch(self, params, input_data, ctx):
        """Route to the output port matching the expression value."""
        expression = params.get("expression", "")
        ctx_vars = ctx.template_vars(input_data)

        value = _eval_expr(str(expression), ctx_vars) if isinstance(expression, str) else expression
        port = str(value) if value is not None else "default"
        return input_data, port

    async def _h_loop(self, params, input_data, ctx):
        """Iterate over items and collect results using an inline transform."""
        raw_items = params.get("items", input_data)
        if not isinstance(raw_items, list):
            raw_items = [raw_items]

        transform_expr = params.get("transform")
        item_var = params.get("item_var", "item")
        results = []
        for item in raw_items:
            if transform_expr:
                base_vars = ctx.template_vars(input_data)
                base_vars[item_var] = item
                results.append(_eval_expr(str(transform_expr), base_vars))
            else:
                results.append(item)

        return results, "main"

    async def _h_merge(self, params, input_data, ctx):
        """Combine multiple incoming data streams."""
        if isinstance(input_data, list):
            return input_data, "main"
        return [input_data], "main"

    # ── Data handlers ──────────────────────────────────────────────────────────

    async def _h_set(self, params, input_data, ctx):
        """Set or override fields on the data object."""
        values: dict = params.get("values") or {}
        mode = params.get("mode", "merge")

        if mode == "replace":
            return values, "main"

        if isinstance(input_data, dict):
            return _deep_merge(input_data, values), "main"
        # If input is not a dict, wrap it
        return {"data": input_data, **values}, "main"

    async def _h_filter(self, params, input_data, ctx):
        """Filter an array of items by a condition expression."""
        items_path = params.get("items_path")
        condition_expr = params.get("condition", "True")
        item_var = params.get("item_var", "item")

        items: list
        if items_path:
            ctx_vars = ctx.template_vars(input_data)
            items = _eval_expr(str(items_path), ctx_vars)
        elif isinstance(input_data, list):
            items = input_data
        else:
            items = [input_data]

        results = []
        for item in items:
            base_vars = ctx.template_vars(input_data)
            base_vars[item_var] = item
            if bool(_eval_expr(str(condition_expr), base_vars)):
                results.append(item)

        return results, "main"

    async def _h_transform(self, params, input_data, ctx):
        """Map input data to a new structure using a mapping dict."""
        mapping: dict = params.get("mapping") or {}
        ctx_vars = ctx.template_vars(input_data)
        return {k: _resolve(v, ctx_vars) for k, v in mapping.items()}, "main"

    async def _h_code(self, params, input_data, ctx):
        """Execute a Python snippet.

        The snippet has ``input`` (current data) and ``nodes`` in scope.
        It must assign its result to ``output``.
        """
        code: str = params.get("code", "output = input")
        ctx_vars = ctx.template_vars(input_data)
        local_ns: dict[str, Any] = {"input": input_data, "nodes": ctx_vars.get("nodes", {})}

        # Compile + check for dangerous constructs
        try:
            tree = ast.parse(code, mode="exec")
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    raise ValueError("import statements are not allowed in code nodes")
            exec(compile(tree, "<workflow_code>", "exec"), {"__builtins__": _SAFE_BUILTINS}, local_ns)  # noqa: S102
        except Exception as exc:
            raise RuntimeError(f"code node error: {exc}") from exc

        output = local_ns.get("output", input_data)
        return output, "main"

    # ── Output / side-effect handlers ─────────────────────────────────────────

    async def _h_respond_webhook(self, params, input_data, ctx):
        """Mark data as the webhook response."""
        response_data = params.get("data", input_data)
        ctx._webhook_response = response_data  # type: ignore[attr-defined]
        return response_data, "main"

    async def _h_emit_event(self, params, input_data, ctx):
        """Emit a platform event (no-op if event_bus not wired)."""
        event_type = params.get("event_type", "workflow.event")
        data = params.get("data", input_data)
        return {"emitted": True, "event_type": event_type, "data": data}, "main"

    async def _h_stop(self, params, input_data, ctx):
        """Terminate workflow execution at this node."""
        output = params.get("output", input_data)
        return output, "main"
