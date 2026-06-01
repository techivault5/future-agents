"""Project templates — expose scaffold templates so devs can bootstrap projects.

Each IT agent definition has a `folder_structure_template` field pointing
to one of these templates.  Developers can browse them and use them to
scaffold new projects that match their chosen agent's stack.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from future_agents.api import loader

router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.get("")
def list_templates() -> list[dict]:
    """List all project-structure scaffold templates."""
    templates = loader.load_templates()
    if not templates:
        return []
    # Return lightweight summary (no file listing)
    return [
        {
            "name": t["name"],
            "file_count": t["file_count"],
            "description": _template_description(t["name"]),
            "use_cases": _template_use_cases(t["name"]),
        }
        for t in templates
    ]


@router.get("/{template_name}")
def get_template(template_name: str) -> dict:
    """Get full file tree for a scaffold template."""
    templates = loader.load_templates()
    match = next((t for t in templates if t["name"] == template_name), None)
    if match is None:
        available = [t["name"] for t in templates]
        raise HTTPException(
            status_code=404,
            detail=f"Template '{template_name}' not found. Available: {available}",
        )
    return {
        **match,
        "description": _template_description(template_name),
        "use_cases": _template_use_cases(template_name),
        "guardrails_rule": "Follow the folder structure shown. Deviations require team approval.",
    }


@router.get("/for-agent/{agent_id}")
def get_template_for_agent(agent_id: str) -> dict:
    """Return the scaffold template that matches an agent's primary stack."""
    agent = loader.load_agent_yaml(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    template_ref = agent.get("folder_structure_template", "")
    # Extract the template name from the path, e.g. "templates/project-structures/python-service"
    template_name = template_ref.split("/")[-1] if template_ref else None

    templates = loader.load_templates()
    match = next((t for t in templates if t["name"] == template_name), None)

    return {
        "agent_id": agent_id,
        "agent_name": agent.get("name", agent_id),
        "primary_stack": agent.get("primary_stack", ""),
        "template_ref": template_ref,
        "template_name": template_name,
        "template": {
            **match,
            "description": _template_description(template_name or ""),
            "use_cases": _template_use_cases(template_name or ""),
        } if match else None,
        "scaffold_command": (
            f"python guardrails/guardrails_engine.py . --mode fix "
            f"--project-type {template_name or 'python-service'} "
            f"--project-name my-project"
        ) if match else None,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

_DESCRIPTIONS = {
    "python-service": "Python microservice with FastAPI/Flask — src/, tests/, pyproject.toml, Dockerfile",
    "node-service": "Node/TypeScript service — src/routes, controllers, services, models, tests/",
    "ml-project": "Machine learning project — src/features, models, evaluation, serving, notebooks/",
    "data-pipeline": "Data pipeline / dbt project — dags/, models/staging|marts|intermediate, docs/",
    "fullstack-app": "Full-stack application — frontend + backend with shared types and Docker Compose",
    "sqlserver-service": "SQL Server–backed service with migration scripts, stored procedures, and ORM layer",
}

_USE_CASES = {
    "python-service": ["Backend APIs", "Guardrails scanner", "Automation scripts", "CLI tools"],
    "node-service": ["REST APIs", "GraphQL services", "BFF layers", "Webhooks"],
    "ml-project": ["Model training", "RAG pipelines", "Feature engineering", "Model serving"],
    "data-pipeline": ["ETL pipelines", "Data warehousing", "Analytics", "dbt projects"],
    "fullstack-app": ["SaaS apps", "Internal tools", "Developer portals", "Admin UIs"],
    "sqlserver-service": ["Enterprise apps", "ERP integrations", "Reporting services", "OLTP systems"],
}


def _template_description(name: str) -> str:
    return _DESCRIPTIONS.get(name, f"Project scaffold template: {name}")


def _template_use_cases(name: str) -> list[str]:
    return _USE_CASES.get(name, [])
