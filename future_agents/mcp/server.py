"""MCP stdio server — connects VSCode / Claude Desktop to the IT Agents Orchestrator.

Protocol: Model Context Protocol (MCP) 2024-11-05 over JSON-RPC 2.0 / stdio.

Usage (VSCode / Claude Desktop):
    python mcp_server.py

The server exposes five tools that Claude in VSCode can call:

    ask_agent           Route a natural-language question to the best IT expert
    find_agents         Search the 10 K catalog for agents matching a task
    check_guardrails    Scan code / config for secrets, policy violations, escalations
    run_workflow        Execute a built-in workflow template with input data
    agent_detail        Load the full YAML definition for a specific agent ID

MCP spec reference: https://modelcontextprotocol.io/
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any

# Bootstrap path so the package is importable when run as a script
_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from future_agents.agents.orchestrator_agent import OrchestratorAgent  # noqa: E402

logger = logging.getLogger("mcp.server")

# ── Tool definitions (sent to the client on tools/list) ───────────────────────

_TOOLS: list[dict] = [
    {
        "name": "ask_agent",
        "description": (
            "Route any IT question to the single best-matching expert agent from the "
            "10,000-agent catalog. Returns the agent's persona as a system prompt, rich "
            "context, guardrails results (secrets, escalation triggers), and confidence score. "
            "Use this as the primary tool for any technical or IT-related question."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The user's question or task description (natural language).",
                },
                "domain": {
                    "type": "string",
                    "description": "Optional domain hint: frontend | backend | devops | security | data | mobile | ml | cloud",
                },
                "seniority": {
                    "type": "string",
                    "description": "Optional seniority preference: intern | junior | mid-level | senior | principal | architect",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of candidate agents to evaluate (default 3).",
                    "default": 3,
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "find_agents",
        "description": (
            "Search the 10,000-agent IT role catalog and return the top N matches for a "
            "task description. Returns agent IDs, names, roles, seniority levels, match "
            "scores, and reasons. Useful for browsing experts before committing to one."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Task or problem description to match against the catalog.",
                },
                "domain": {
                    "type": "string",
                    "description": "Optional domain filter.",
                },
                "seniority": {
                    "type": "string",
                    "description": "Optional seniority filter.",
                },
                "agent_type": {
                    "type": "string",
                    "description": "Filter by type: technical | non-technical | voice",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of results (default 5, max 20).",
                    "default": 5,
                },
            },
            "required": ["task"],
        },
    },
    {
        "name": "check_guardrails",
        "description": (
            "Scan any code snippet, configuration, or text for: embedded secrets / "
            "credentials, SQL injection patterns, unsafe Python (eval/pickle/shell=True), "
            "PCI/PHI/PII data, production escalation triggers, and package policy issues. "
            "Returns violations, warnings, escalation flags, and concrete recommendations."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Code, config, or text to check.",
                },
                "profile": {
                    "type": "string",
                    "description": "Guardrails profile: standard | strict | relaxed | architect (default standard)",
                    "default": "standard",
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "run_workflow",
        "description": (
            "Execute one of the built-in n8n-like workflow templates with provided input data. "
            "Templates: tpl-agent-search-notify | tpl-guardrails-pipeline | "
            "tpl-capability-onboarding | tpl-http-enrich-agent | tpl-batch-loop. "
            "Returns execution status, per-node results, and final output."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "template_id": {
                    "type": "string",
                    "description": "Template ID from the list above.",
                },
                "input_data": {
                    "description": "Input data passed to the first (trigger) node.",
                },
            },
            "required": ["template_id"],
        },
    },
    {
        "name": "agent_detail",
        "description": (
            "Load the full YAML definition for a specific agent ID (e.g. 'agent-00001'). "
            "Returns name, role, seniority, primary stack, tools, languages, skills, "
            "guardrails profile, industry specialisations, and cloud platforms."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Agent ID in the format agent-NNNNN.",
                },
            },
            "required": ["agent_id"],
        },
    },
]


# ── Server implementation ─────────────────────────────────────────────────────

class MCPServer:
    """Minimal MCP 2024-11-05 server over stdio."""

    SERVER_INFO = {
        "name": "it-agents-orchestrator",
        "version": "1.0.0",
    }
    PROTOCOL_VERSION = "2024-11-05"

    def __init__(self) -> None:
        self._orchestrator = OrchestratorAgent()
        self._initialized = False

    # ── I/O ────────────────────────────────────────────────────────────────────

    def _read_message(self) -> dict | None:
        """Read one newline-delimited JSON message from stdin."""
        try:
            line = sys.stdin.readline()
            if not line:
                return None
            return json.loads(line.strip())
        except json.JSONDecodeError as exc:
            logger.warning("Invalid JSON: %s", exc)
            return None

    def _send(self, obj: dict) -> None:
        """Write a JSON-RPC message to stdout."""
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()

    def _respond(self, msg_id: Any, result: Any) -> None:
        self._send({"jsonrpc": "2.0", "id": msg_id, "result": result})

    def _error(self, msg_id: Any, code: int, message: str, data: Any = None) -> None:
        err: dict = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        self._send({"jsonrpc": "2.0", "id": msg_id, "error": err})

    # ── Main loop ──────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Run until stdin is closed."""
        logger.info("IT Agents Orchestrator MCP server starting")
        while True:
            msg = self._read_message()
            if msg is None:
                break
            try:
                self._dispatch(msg)
            except Exception:
                logger.error("Unhandled error:\n%s", traceback.format_exc())
                self._error(msg.get("id"), -32603, "Internal server error")
        logger.info("MCP server exiting")

    def _dispatch(self, msg: dict) -> None:
        method = msg.get("method", "")
        msg_id = msg.get("id")
        params = msg.get("params") or {}

        # Notifications (no id) — acknowledged silently
        if msg_id is None:
            if method == "notifications/initialized":
                self._initialized = True
            return

        if method == "initialize":
            self._handle_initialize(msg_id, params)
        elif method == "tools/list":
            self._handle_tools_list(msg_id)
        elif method == "tools/call":
            self._handle_tools_call(msg_id, params)
        elif method == "ping":
            self._respond(msg_id, {})
        else:
            self._error(msg_id, -32601, f"Method not found: {method}")

    # ── MCP handlers ───────────────────────────────────────────────────────────

    def _handle_initialize(self, msg_id: Any, params: dict) -> None:
        self._respond(msg_id, {
            "protocolVersion": self.PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": self.SERVER_INFO,
        })

    def _handle_tools_list(self, msg_id: Any) -> None:
        self._respond(msg_id, {"tools": _TOOLS})

    def _handle_tools_call(self, msg_id: Any, params: dict) -> None:
        tool_name = params.get("name", "")
        arguments: dict = params.get("arguments") or {}

        try:
            result_text = self._call_tool(tool_name, arguments)
            self._respond(msg_id, {
                "content": [{"type": "text", "text": result_text}],
                "isError": False,
            })
        except ValueError as exc:
            self._respond(msg_id, {
                "content": [{"type": "text", "text": f"Error: {exc}"}],
                "isError": True,
            })

    # ── Tool implementations ───────────────────────────────────────────────────

    def _call_tool(self, name: str, args: dict) -> str:
        if name == "ask_agent":
            return self._tool_ask_agent(args)
        if name == "find_agents":
            return self._tool_find_agents(args)
        if name == "check_guardrails":
            return self._tool_check_guardrails(args)
        if name == "run_workflow":
            return self._tool_run_workflow(args)
        if name == "agent_detail":
            return self._tool_agent_detail(args)
        raise ValueError(f"Unknown tool: {name}")

    def _tool_ask_agent(self, args: dict) -> str:
        question = args.get("question", "")
        if not question:
            raise ValueError("'question' is required")

        resp = self._orchestrator.ask(
            question=question,
            domain=args.get("domain"),
            seniority=args.get("seniority"),
            top_k=min(int(args.get("top_k", 3)), 5),
        )

        parts = [
            "# IT Agents Orchestrator Response\n",
            f"**Intent:** `{resp.intent}`  |  "
            f"**Domains:** {', '.join(resp.domains[:3]) or 'general'}  |  "
            f"**Confidence:** {resp.confidence:.0%}",
        ]

        if resp.primary_agent:
            pa = resp.primary_agent
            parts.append(
                f"\n## Selected Expert: {pa.agent_name}\n"
                f"- **Role:** `{pa.role}`\n"
                f"- **Seniority:** {pa.seniority}\n"
                f"- **Guardrails profile:** `{pa.guardrails_profile}`\n"
                f"- **Match score:** {pa.match_score:.0%}\n"
                f"- **Match reasons:** {', '.join(pa.match_reasons)}"
            )
            if pa.top_skills:
                parts.append(f"- **Top skills:** {', '.join(pa.top_skills[:5])}")
            if pa.primary_stack:
                parts.append(f"- **Stack:** {', '.join(pa.primary_stack[:5])}")

        # Guardrails
        g = resp.guardrails
        if g.secrets_found or g.escalation_required or g.warnings:
            parts.append("\n## ⚠️ Guardrails Alerts")
            if g.secrets_found:
                parts.append(f"🔴 **Secrets found:** {', '.join(g.secrets_found)}")
            if g.escalation_required:
                parts.append("🚨 **Escalation required:**")
                for r in g.escalation_reasons:
                    parts.append(f"  - {r}")
            if g.warnings:
                parts.append("⚠️ **Warnings:**")
                for w in g.warnings:
                    parts.append(f"  - {w}")
        if g.recommendations:
            parts.append("\n## Recommendations")
            for r in g.recommendations:
                parts.append(f"- {r}")

        if resp.detected_stack:
            parts.append(f"\n**Detected stack:** {', '.join(resp.detected_stack)}")

        if resp.multi_agent_suggested:
            parts.append(
                f"\n💡 **Multi-agent workflow suggested** — consider running template "
                f"`{resp.suggested_workflow}` via the `run_workflow` tool."
            )

        parts.append("\n---\n## Expert System Prompt (use as context)\n")
        parts.append(resp.system_prompt)

        if resp.matched_agents and len(resp.matched_agents) > 1:
            parts.append("\n---\n## Other Candidate Agents")
            for a in resp.matched_agents[1:]:
                parts.append(f"- **{a.agent_name}** (`{a.role}`, {a.seniority}) — {a.match_score:.0%}")

        return "\n".join(parts)

    def _tool_find_agents(self, args: dict) -> str:
        task = args.get("task", "")
        if not task:
            raise ValueError("'task' is required")

        limit = min(int(args.get("limit", 5)), 20)
        matches = self._orchestrator.find_agents(
            task=task,
            domain=args.get("domain"),
            seniority=args.get("seniority"),
            agent_type=args.get("agent_type"),
            limit=limit,
        )

        if not matches:
            return "No agents found matching your criteria."

        lines = [f"# {len(matches)} Agent(s) Found for: \"{task}\"\n"]
        for i, m in enumerate(matches, 1):
            lines.append(
                f"## {i}. {m.agent_name} (`{m.agent_id}`)\n"
                f"- **Role:** {m.role}\n"
                f"- **Seniority:** {m.seniority}  |  **Type:** {m.agent_type}\n"
                f"- **Match score:** {m.match_score:.0%}\n"
                f"- **Reasons:** {', '.join(m.match_reasons)}"
            )
        return "\n".join(lines)

    def _tool_check_guardrails(self, args: dict) -> str:
        content = args.get("content", "")
        if not content:
            raise ValueError("'content' is required")

        profile = args.get("profile", "standard")
        result = self._orchestrator.check_guardrails(content, profile)

        lines = [f"# Guardrails Check — Profile: `{profile.upper()}`\n"]
        status = "✅ PASSED" if result.passed else "❌ FAILED"
        lines.append(f"**Status:** {status}")

        if result.secrets_found:
            lines.append(f"\n🔴 **Secrets detected ({len(result.secrets_found)}):**")
            for s in result.secrets_found:
                lines.append(f"  - `{s}`")
            lines.append("\n> Remove all credentials and use `os.environ['VAR_NAME']` instead.")

        if result.escalation_required:
            lines.append(f"\n🚨 **Human escalation required ({len(result.escalation_reasons)}):**")
            for r in result.escalation_reasons:
                lines.append(f"  - {r}")

        if result.warnings:
            lines.append(f"\n⚠️ **Security warnings ({len(result.warnings)}):**")
            for w in result.warnings:
                lines.append(f"  - {w}")

        if result.recommendations:
            lines.append("\n## Recommendations")
            for r in result.recommendations:
                lines.append(f"- {r}")

        if result.passed:
            lines.append("\nNo critical issues found. Review warnings above if any.")

        return "\n".join(lines)

    def _tool_run_workflow(self, args: dict) -> str:
        import asyncio

        template_id = args.get("template_id", "")
        if not template_id:
            raise ValueError("'template_id' is required")

        try:
            from future_agents.workflows.engine import WorkflowEngine
            from future_agents.workflows.templates import TEMPLATES_BY_ID

            template = TEMPLATES_BY_ID.get(template_id)
            if not template:
                available = ", ".join(TEMPLATES_BY_ID.keys())
                raise ValueError(f"Template '{template_id}' not found. Available: {available}")

            engine = WorkflowEngine()
            execution = asyncio.run(
                engine.execute(template.workflow, trigger_data=args.get("input_data"))
            )
        except ImportError as exc:
            return f"Workflow engine not available: {exc}"

        lines = [
            f"# Workflow Execution: {template.name}\n",
            f"**Template:** `{template_id}`  |  "
            f"**Status:** {execution.status}  |  "
            f"**Duration:** {execution.duration_ms:.0f}ms",
            f"**Execution ID:** `{execution.id}`",
        ]

        if execution.node_executions:
            lines.append("\n## Node Results")
            for ne in execution.node_executions:
                icon = "✅" if str(ne.status).endswith("SUCCESS") else "❌"
                lines.append(
                    f"{icon} **{ne.node_name}** (`{ne.node_type}`) "
                    f"→ port: `{ne.output_port}` ({ne.duration_ms:.0f}ms)"
                )
                if ne.error:
                    lines.append(f"   Error: {ne.error}")

        if execution.output_data is not None:
            output_str = json.dumps(execution.output_data, indent=2, default=str)
            if len(output_str) > 800:
                output_str = output_str[:800] + "\n... (truncated)"
            lines.append(f"\n## Output\n```json\n{output_str}\n```")

        return "\n".join(lines)

    def _tool_agent_detail(self, args: dict) -> str:
        agent_id = args.get("agent_id", "")
        if not agent_id:
            raise ValueError("'agent_id' is required")

        data = self._orchestrator._load_yaml(agent_id)
        if not data:
            return f"Agent '{agent_id}' not found or YAML not yet indexed."

        lines = [f"# {data.get('name', agent_id)}\n"]
        fields = [
            ("Role", "role"), ("Seniority", "seniority"), ("Type", "type"),
            ("Guardrails Profile", "guardrails_profile"),
            ("Primary Stack", "primary_stack"), ("Languages", "languages"),
            ("Tools", "tools"), ("Key Skills", "key_skills"),
            ("Industries", "industries"), ("Cloud Platforms", "cloud_platforms"),
        ]
        for label, key in fields:
            val = data.get(key)
            if val:
                if isinstance(val, list):
                    val = ", ".join(str(v) for v in val[:8])
                lines.append(f"**{label}:** {val}")

        if data.get("description"):
            lines.append(f"\n**Description:** {data['description']}")

        return "\n".join(lines)


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(
        level=logging.WARNING,   # keep stdout clean for MCP protocol
        stream=sys.stderr,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    MCPServer().run()


if __name__ == "__main__":
    main()
