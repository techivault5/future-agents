"""System Agents — the 6 live orchestration agents built into the platform.

These are different from the 10,000 role-definition agents.  They are running
Python agents (capability, knowledge, master, policy, process, skills) that
can be invoked at runtime via the AgentSystem.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from future_agents.api import loader

router = APIRouter(prefix="/api/system-agents", tags=["system-agents"])


class InvokeRequest(BaseModel):
    """Invoke a system agent intent."""

    intent: str
    parameters: dict[str, Any] | None = None


@router.get("")
def list_system_agents() -> list[dict[str, Any]]:
    """List all 6 built-in system agents with their skills and callable intents."""
    agents = loader.load_system_agents()
    result = []
    for a in agents:
        skills = a.get("skills", [])
        result.append(
            {
                "id": a["_id"],
                "name": a.get("name", a["_id"]),
                "type": a.get("type", ""),
                "version": a.get("version", "1.0.0"),
                "description": a.get("description", ""),
                "domain": a.get("domain", ""),
                "tags": a.get("tags", []),
                "skills": [
                    {
                        "name": s.get("name", ""),
                        "description": s.get("description", ""),
                        "intent": s.get("intent", ""),
                        "level": s.get("level", "basic"),
                        "tags": s.get("tags", []),
                        "inputs": s.get("inputs", []),
                        "outputs": s.get("outputs", []),
                        "examples": s.get("examples", [])[:2],
                    }
                    for s in skills
                ],
                "callable_intents": [s.get("intent") for s in skills if s.get("intent")],
                "personality": a.get("personality", {}),
                "constraints": a.get("constraints", {}),
            }
        )
    return result


@router.get("/{agent_id}")
def get_system_agent(agent_id: str) -> dict[str, Any]:
    """Get full definition for a specific system agent."""
    agents = loader.load_system_agents()
    for a in agents:
        if a["_id"] == agent_id:
            return a
    raise HTTPException(status_code=404, detail=f"System agent '{agent_id}' not found")


@router.post("/{agent_id}/invoke")
async def invoke_system_agent(agent_id: str, body: InvokeRequest) -> dict[str, Any]:
    """Invoke a system agent intent via AgentSystem.

    Uses the live AgentSystem (capability, knowledge, master, policy, process, skills).
    The intent must match one of the agent's callable_intents.
    """
    valid_ids = [a["_id"] for a in loader.load_system_agents()]
    if agent_id not in valid_ids:
        raise HTTPException(status_code=404, detail=f"System agent '{agent_id}' not found")

    try:
        from future_agents.system import AgentSystem

        system = AgentSystem()
        await system.start()
        result = await system.ask(body.intent, body.parameters or {})
        await system.stop()
        return {"agent_id": agent_id, "intent": body.intent, "result": result}
    except Exception as exc:
        # AgentSystem may not be fully wired in all environments —
        # return a structured error rather than 500
        raise HTTPException(
            status_code=503,
            detail=(
                f"System agent invoke failed: {exc}. Ensure the AgentSystem dependencies are installed and configured."
            ),
        ) from exc


@router.get("/{agent_id}/connector/mcp")
def get_system_agent_mcp(agent_id: str, base_url: str = "http://localhost:8000") -> dict:
    """MCP connector config for a system agent — exposes each intent as an AI tool."""
    agents = loader.load_system_agents()
    agent = next((a for a in agents if a["_id"] == agent_id), None)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"System agent '{agent_id}' not found")

    skills = agent.get("skills", [])
    tools = []
    for s in skills:
        intent = s.get("intent", "")
        if not intent:
            continue
        inputs_schema: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
        for inp in s.get("inputs", []):
            inputs_schema["properties"][inp["name"]] = {
                "type": inp.get("type", "string"),
                "description": inp.get("description", ""),
            }
            if inp.get("required"):
                inputs_schema["required"].append(inp["name"])

        tools.append(
            {
                "name": intent.replace(".", "_"),
                "description": s.get("description", s.get("name", intent)),
                "input_schema": inputs_schema,
                "http": {
                    "method": "POST",
                    "url": f"{base_url}/api/system-agents/{agent_id}/invoke",
                    "headers": {"Content-Type": "application/json"},
                    "body_template": f'{{"intent": "{intent}", "parameters": {{{{...}}}}}}',
                },
            }
        )

    return {
        "mcpServers": {
            f"it-agents-{agent_id}": {
                "command": "uvx",
                "args": ["mcp-server-fetch", "--base-url", base_url, "--agent-id", agent_id],
            }
        },
        "http_connector": {
            "type": "http",
            "name": agent.get("name", agent_id),
            "description": agent.get("description", ""),
            "base_url": base_url,
            "invoke_endpoint": f"POST {base_url}/api/system-agents/{agent_id}/invoke",
            "tools": tools,
        },
    }
