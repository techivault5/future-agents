#!/usr/bin/env python3
"""Finance Advisor dashboard — FastAPI app.

Run:  pip install -e ".[api]"
      uvicorn finance_advisor.app:app --port 8600
Then open http://localhost:8600
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR.parent.parent))

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
except ImportError as err:  # pragma: no cover
    raise ImportError("FastAPI required: pip install -e '.[api]'") from err

from finance_advisor.alerts import (  # noqa: E402
    CONDITIONS,
    AlertRule,
    evaluate_all,
    load_alerts,
    save_alerts,
)
from finance_advisor.gather import load_knowledge  # noqa: E402
from finance_advisor.market_data import (  # noqa: E402
    WATCHED_ASSETS,
    fetch_all_quotes,
    fetch_fund_navs,
    fetch_fx,
)
from finance_advisor.memory import FinanceMemorySDK  # noqa: E402

app = FastAPI(title="Finance Advisor", version="1.0.0")

# ES modules refuse to load over file://, so the browser SDK demo is served
# here over http instead.
app.mount(
    "/sdk",
    StaticFiles(directory=PROJECT_DIR / "memory" / "sdk", html=True),
    name="sdk",
)

PROPERTY_FILE = PROJECT_DIR / "data" / "property_watch.json"
STATIC_DIR = PROJECT_DIR / "static"

_store = None
_memory_sdk: FinanceMemorySDK | None = None


def memory_sdk() -> FinanceMemorySDK:
    """Process-wide SDK bound to a durable local sqlite store."""
    global _memory_sdk
    if _memory_sdk is None:
        _memory_sdk = FinanceMemorySDK(store="sqlite", path=PROJECT_DIR / "data" / "memory.db")
    return _memory_sdk


def knowledge_store():
    global _store
    if _store is None:
        _store = load_knowledge()
    return _store


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/overview")
def overview():
    return {
        "quotes": fetch_all_quotes(),
        "fx": fetch_fx(),
        "disclaimer": "Educational signals, not licensed financial advice.",
    }


@app.get("/api/funds")
def funds():
    return {"funds": fetch_fund_navs()}


@app.get("/api/property")
def property_watch():
    return json.loads(PROPERTY_FILE.read_text())


@app.get("/api/tips")
def tips(topic: str = "saving"):
    domain_map = {
        "saving": "finance.saving",
        "debt": "finance.debt",
        "budgeting": "finance.budgeting",
        "india": "finance.india",
        "trends": "finance.trends",
    }
    store = knowledge_store()
    entries = store.by_domain(domain_map.get(topic, "finance.saving"))
    return {
        "topic": topic,
        "tips": [{"title": e.title, "content": e.content, "tags": e.tags} for e in entries],
    }


@app.get("/api/search")
def search(q: str):
    store = knowledge_store()
    results = store.search(q)[:10]
    return {
        "query": q,
        "results": [{"title": e.title, "domain": e.domain, "content": e.content} for e in results],
    }


@app.get("/api/alerts")
def list_alerts():
    return {
        "alerts": [r.model_dump() for r in load_alerts()],
        "assets": {k: v[1] for k, v in WATCHED_ASSETS.items()},
        "conditions": CONDITIONS,
    }


@app.post("/api/alerts")
def create_alert(rule: dict):
    if rule.get("asset") not in WATCHED_ASSETS:
        raise HTTPException(400, f"Unknown asset. Use one of: {list(WATCHED_ASSETS)}")
    if rule.get("condition") not in CONDITIONS:
        raise HTTPException(400, f"Unknown condition. Use one of: {list(CONDITIONS)}")
    new = AlertRule(
        asset=rule["asset"],
        condition=rule["condition"],
        threshold=float(rule.get("threshold", 0)),
        note=rule.get("note", ""),
        email=rule.get("email", ""),
    )
    rules = load_alerts()
    rules.append(new)
    save_alerts(rules)
    return new.model_dump()


@app.delete("/api/alerts/{alert_id}")
def delete_alert(alert_id: str):
    rules = load_alerts()
    remaining = [r for r in rules if r.id != alert_id]
    if len(remaining) == len(rules):
        raise HTTPException(404, "Alert not found")
    save_alerts(remaining)
    return {"deleted": alert_id}


@app.post("/api/alerts/preview")
def preview_alerts():
    """Evaluate all rules against live data WITHOUT emailing (UI 'test now')."""
    rules = load_alerts()
    quotes = fetch_all_quotes()
    triggered = evaluate_all(rules, quotes)
    return {
        "checked": len([r for r in rules if r.active]),
        "triggered": [{"id": r.id, "message": m} for r, m in triggered],
    }


# ── memory framework + skill SDK ─────────────────────────────────────────────


@app.get("/api/memory/stats")
def memory_stats():
    """Store composition, embedder and backend in use."""
    return memory_sdk().stats()


@app.get("/api/memory/recall")
def memory_recall(q: str, limit: int = 5, type: str | None = None):
    """Ranked, redacted recall with score components."""
    return {"query": q, "hits": memory_sdk().recall(q, limit=limit, type=type)}


@app.post("/api/memory/remember")
def memory_remember(item: dict):
    """Write one memory: {content, type?, tags?, importance?, sensitive?}."""
    content = str(item.get("content", "")).strip()
    if not content:
        raise HTTPException(400, "content is required")
    try:
        return memory_sdk().remember(
            content,
            type=item.get("type", "semantic"),
            tags=item.get("tags") or (["profile"] if "=" in content else []),
            importance=float(item.get("importance", 0.5)),
            sensitive=bool(item.get("sensitive", False)),
        )
    except ValueError as err:
        raise HTTPException(400, str(err)) from err


@app.get("/api/memory/profile")
def memory_profile():
    """Durable profile facts learned so far."""
    return memory_sdk().profile()


@app.post("/api/memory/consolidate")
def memory_consolidate():
    """Promote recurring episodes into semantic facts."""
    return {"created": memory_sdk().consolidate()}


@app.get("/api/memory/export")
def memory_export():
    """Redacted portable dump, importable by the JavaScript SDK."""
    return {"records": memory_sdk().export()}


@app.get("/api/skills")
def list_skills():
    """Catalog of finance skills and what each covers."""
    return {"skills": FinanceMemorySDK.skills()}


@app.post("/api/skills/{name}")
def run_skill(name: str, args: dict | None = None):
    """Run a finance skill: loans | mutual_funds | crypto | capital_gains | taxes."""
    try:
        return memory_sdk().advise(name, **(args or {}))
    except KeyError as err:
        raise HTTPException(404, str(err)) from err
    except (ValueError, TypeError) as err:
        raise HTTPException(400, str(err)) from err


@app.get("/api/runtimes")
def local_runtimes():
    """Local-inference comparison matrix plus this machine's capabilities."""
    return {
        "capabilities": FinanceMemorySDK.capabilities().to_dict(),
        "matrix": FinanceMemorySDK.runtimes(),
    }
