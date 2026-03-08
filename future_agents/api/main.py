"""IT Agents Marketplace — FastAPI application.

Start with:
    uvicorn future_agents.api.main:app --reload --host 0.0.0.0 --port 8000

Then open http://localhost:8000 in a browser.

API surface:
    /api/agents            — browse/search 10,000 role agents
    /api/agents/{id}/test  — test an agent with a prompt
    /api/agents/recommend  — recommend agents by task description
    /api/agents/{id}/connector/{openapi|mcp|curl}
    /api/system-agents     — 6 live orchestration agents (callable intents)
    /api/guardrails        — guardrails profiles and enforcement skills
    /api/templates         — project scaffold templates
    /api/stats             — marketplace statistics
    /api/categories        — role categories

Workflow automation (n8n-like):
    /api/workflows         — CRUD for workflow definitions
    /api/workflows/templates       — built-in workflow templates
    /api/workflows/node-types      — node type reference + expression syntax
    /api/workflows/{id}/execute    — run a workflow manually
    /api/workflows/{id}/executions — execution history
    /api/executions/{id}           — full execution detail with per-node results
    /api/webhooks/{workflow_id}    — HTTP webhook trigger

    /docs                  — Swagger UI
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from future_agents.api import loader
from future_agents.api.routes.agents import router as agents_router
from future_agents.api.routes.connectors import router as connectors_router
from future_agents.api.routes.guardrails_api import router as guardrails_router
from future_agents.api.routes.marketplace import router as marketplace_router
from future_agents.api.routes.system_agents import router as system_agents_router
from future_agents.api.routes.templates import router as templates_router
from future_agents.api.routes.workflows import router as workflows_router

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent.parent.parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start background tasks on launch."""
    # Build rich in-memory index from 10,000 YAML files in a background thread.
    # Filters for industry/cloud/stack/profile/skills become available once done.
    loader.start_rich_index_build()
    logger.info("Rich index build started in background")
    yield


app = FastAPI(
    title="IT Agents Marketplace",
    description=(
        "Browse, search, and test 10,000 IT agent role definitions. "
        "Generate OpenAPI connectors, MCP configs, and cURL snippets to integrate "
        "any agent into your AI toolchain.\n\n"
        "**Also exposes:** 6 live orchestration agents, guardrails profiles/skills, "
        "project scaffold templates, and **n8n-like workflow automation** with "
        "triggers, agent nodes, HTTP requests, branching, loops, and execution history."
    ),
    version="1.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API routes ────────────────────────────────────────────────────────────────
app.include_router(marketplace_router)
app.include_router(agents_router)
app.include_router(connectors_router)
app.include_router(system_agents_router)
app.include_router(guardrails_router)
app.include_router(templates_router)
app.include_router(workflows_router)


# ── Static files (marketplace UI) ────────────────────────────────────────────
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/marketplace")


@app.get("/marketplace", include_in_schema=False)
def marketplace_ui() -> FileResponse:
    """Serve the browser marketplace UI."""
    html_file = _STATIC_DIR / "index.html"
    if not html_file.exists():
        from fastapi.responses import HTMLResponse
        return HTMLResponse(
            "<h1>Marketplace UI not found</h1><p>Run with the static/ directory present.</p>",
            status_code=200,
        )
    return FileResponse(str(html_file))
