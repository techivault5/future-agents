"""Connector generation — export agents as OpenAPI specs, MCP configs, and cURL snippets.

Developers can use these connectors to integrate any IT agent into:
- REST clients (Postman, Insomnia) via OpenAPI 3.0
- Claude Desktop / any MCP-compatible AI tool via MCP config
- Scripts and pipelines via cURL
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

from future_agents.api import loader

router = APIRouter(prefix="/api/agents", tags=["connectors"])


@router.get("/{agent_id}/connector")
def get_connector_index(agent_id: str, base_url: str = "http://localhost:8000") -> dict:
    """List all available connector formats for an agent."""
    data = loader.load_agent_yaml(agent_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    return {
        "agent_id": agent_id,
        "agent_name": data.get("name", agent_id),
        "connectors": {
            "openapi": f"{base_url}/api/agents/{agent_id}/connector/openapi",
            "mcp": f"{base_url}/api/agents/{agent_id}/connector/mcp",
            "curl": f"{base_url}/api/agents/{agent_id}/connector/curl",
        },
        "instructions": {
            "openapi": "Import this URL into Postman, Insomnia, or any OpenAPI client.",
            "mcp": "Add the returned JSON block to your Claude Desktop claude_desktop_config.json.",
            "curl": "Copy-paste these commands into a terminal to test immediately.",
        },
    }


@router.get("/{agent_id}/connector/openapi")
def get_openapi_connector(agent_id: str, base_url: str = "http://localhost:8000") -> JSONResponse:
    """Generate an OpenAPI 3.0 spec for this agent so it can be imported into any REST client."""
    data = loader.load_agent_yaml(agent_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    name = data.get("name", agent_id)
    role = data.get("role", "")
    skills = data.get("skills", [])
    description = data.get("description", f"IT agent specialised in {role}")

    spec = {
        "openapi": "3.0.3",
        "info": {
            "title": name,
            "description": (
                f"{description}\n\n"
                f"**Role:** {role}  \n"
                f"**Seniority:** {data.get('seniority', 'N/A')}  \n"
                f"**Stack:** {data.get('primary_stack', 'N/A')}  \n"
                f"**Skills:** {', '.join(skills[:8])}"
            ),
            "version": data.get("version", "1.0.0"),
            "x-agent-id": agent_id,
            "x-guardrails-profile": data.get("guardrails_profile", "standard"),
        },
        "servers": [{"url": base_url, "description": "IT Agents Marketplace"}],
        "paths": {
            f"/api/agents/{agent_id}": {
                "get": {
                    "summary": f"Get {name} definition",
                    "operationId": f"get_{agent_id.replace('-', '_')}",
                    "tags": [role],
                    "responses": {
                        "200": {
                            "description": "Agent definition",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/AgentDetail"}}},
                        }
                    },
                }
            },
            f"/api/agents/{agent_id}/test": {
                "post": {
                    "summary": f"Test {name} with a prompt",
                    "operationId": f"test_{agent_id.replace('-', '_')}",
                    "tags": [role],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/TestRequest"},
                                "example": {"prompt": f"How would you approach a {role} challenge?"},
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Agent response",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/TestResponse"}}},
                        }
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "TestRequest": {
                    "type": "object",
                    "required": ["prompt"],
                    "properties": {
                        "prompt": {"type": "string", "description": "Your question or task for the agent"},
                        "context": {"type": "object", "description": "Optional key-value context"},
                    },
                },
                "TestResponse": {
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string"},
                        "agent_name": {"type": "string"},
                        "role": {"type": "string"},
                        "response": {"type": "string"},
                        "relevant_skills": {"type": "array", "items": {"type": "string"}},
                        "recommended_tools": {"type": "array", "items": {"type": "string"}},
                        "guardrails_profile": {"type": "string"},
                        "human_escalation_required": {"type": "boolean"},
                    },
                },
                "AgentDetail": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "role": {"type": "string"},
                        "type": {"type": "string"},
                        "seniority": {"type": "string"},
                        "description": {"type": "string"},
                        "skills": {"type": "array", "items": {"type": "string"}},
                        "tools": {"type": "array", "items": {"type": "string"}},
                        "certifications": {"type": "array", "items": {"type": "string"}},
                        "guardrails_profile": {"type": "string"},
                        "human_input_required": {"type": "boolean"},
                    },
                },
            }
        },
        "tags": [{"name": role, "description": f"Endpoints for the {name} agent"}],
    }

    return JSONResponse(content=spec, media_type="application/json")


@router.get("/{agent_id}/connector/mcp")
def get_mcp_connector(agent_id: str, base_url: str = "http://localhost:8000") -> JSONResponse:
    """Generate an MCP server config block for Claude Desktop / any MCP-compatible AI tool.

    Paste the returned JSON into ~/.config/claude/claude_desktop_config.json
    under the `mcpServers` key to use this agent as an AI tool.
    """
    data = loader.load_agent_yaml(agent_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    name = data.get("name", agent_id)
    skills = data.get("skills", [])
    tools = data.get("tools", [])

    mcp_config = {
        "mcpServers": {
            agent_id: {
                "command": "uvx",
                "args": [
                    "mcp-server-fetch",
                    "--base-url", base_url,
                    "--agent-id", agent_id,
                ],
                "env": {},
            }
        },
        "_comment": (
            f"Add the 'mcpServers.{agent_id}' block to your claude_desktop_config.json. "
            f"Alternatively, use the HTTP connector below."
        ),
        "http_connector": {
            "type": "http",
            "name": name,
            "description": f"IT Agent: {data.get('description', name)}",
            "base_url": base_url,
            "endpoints": {
                "get_agent": f"GET {base_url}/api/agents/{agent_id}",
                "test_agent": f"POST {base_url}/api/agents/{agent_id}/test",
            },
            "tools": [
                {
                    "name": f"ask_{agent_id.replace('-', '_')}",
                    "description": (
                        f"Ask the {name} agent. "
                        f"Specialises in: {', '.join(skills[:5])}. "
                        f"Uses: {', '.join(tools[:3])}."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "prompt": {
                                "type": "string",
                                "description": "Your question or task for the agent",
                            }
                        },
                        "required": ["prompt"],
                    },
                    "http": {
                        "method": "POST",
                        "url": f"{base_url}/api/agents/{agent_id}/test",
                        "headers": {"Content-Type": "application/json"},
                        "body_template": '{"prompt": "{{prompt}}"}',
                    },
                }
            ],
        },
        "agent_metadata": {
            "id": agent_id,
            "name": name,
            "role": data.get("role", ""),
            "seniority": data.get("seniority", ""),
            "primary_stack": data.get("primary_stack", ""),
            "guardrails_profile": data.get("guardrails_profile", "standard"),
            "skills": skills,
            "certifications": data.get("certifications", []),
        },
    }

    return JSONResponse(content=mcp_config, media_type="application/json")


@router.get("/{agent_id}/connector/curl", response_class=PlainTextResponse)
def get_curl_connector(agent_id: str, base_url: str = "http://localhost:8000") -> str:
    """Get ready-to-run cURL commands to test this agent from the terminal."""
    data = loader.load_agent_yaml(agent_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    name = data.get("name", agent_id)
    role = data.get("role", "")
    example_prompt = json.dumps({"prompt": f"How would you approach a {role} challenge?"})

    return f"""#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# IT Agents Marketplace — cURL Connector
# Agent : {name}
# ID    : {agent_id}
# Role  : {role}
# Base  : {base_url}
# ─────────────────────────────────────────────────────────────

# 1. Get agent definition
curl -s "{base_url}/api/agents/{agent_id}" | python3 -m json.tool

# 2. Test the agent with a prompt
curl -s -X POST "{base_url}/api/agents/{agent_id}/test" \\
  -H "Content-Type: application/json" \\
  -d '{example_prompt}' | python3 -m json.tool

# 3. Download OpenAPI spec
curl -s "{base_url}/api/agents/{agent_id}/connector/openapi" > {agent_id}-openapi.json
echo "OpenAPI spec saved to {agent_id}-openapi.json"

# 4. Get MCP connector config
curl -s "{base_url}/api/agents/{agent_id}/connector/mcp" > {agent_id}-mcp.json
echo "MCP config saved to {agent_id}-mcp.json"

# 5. Search for similar agents
curl -s "{base_url}/api/agents?role={role}&page_size=5" | python3 -m json.tool
"""
