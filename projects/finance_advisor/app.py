#!/usr/bin/env python3
"""Finance Advisor dashboard — FastAPI app.

Run:  pip install -e ".[api]"
      uvicorn projects.finance_advisor.app:app --port 8600
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
except ImportError as err:  # pragma: no cover
    raise ImportError("FastAPI required: pip install -e '.[api]'") from err

from projects.finance_advisor.alerts import (  # noqa: E402
    CONDITIONS,
    AlertRule,
    evaluate_all,
    load_alerts,
    save_alerts,
)
from projects.finance_advisor.gather import load_knowledge  # noqa: E402
from projects.finance_advisor.market_data import (  # noqa: E402
    WATCHED_ASSETS,
    fetch_all_quotes,
    fetch_fund_navs,
    fetch_fx,
)

app = FastAPI(title="Finance Advisor", version="1.0.0")

PROPERTY_FILE = PROJECT_DIR / "data" / "property_watch.json"
STATIC_DIR = PROJECT_DIR / "static"

_store = None


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
