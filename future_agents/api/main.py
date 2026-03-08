"""IT Agents Marketplace — FastAPI application.

Start with:
    uvicorn future_agents.api.main:app --reload --host 0.0.0.0 --port 8000

Then open http://localhost:8000 in a browser.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from future_agents.api.routes.agents import router as agents_router
from future_agents.api.routes.connectors import router as connectors_router
from future_agents.api.routes.marketplace import router as marketplace_router

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent.parent.parent / "static"

app = FastAPI(
    title="IT Agents Marketplace",
    description=(
        "Browse, search, and test 10,000 IT agent role definitions. "
        "Generate OpenAPI connectors, MCP configs, and cURL snippets to integrate "
        "any agent into your AI toolchain."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
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
