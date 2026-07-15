"""Tests for the Finance Advisor project (projects/finance_advisor)."""

import json
from pathlib import Path

from future_agents.definitions.loader import DefinitionLoader
from projects.finance_advisor.gather import (
    KNOWLEDGE_DIR,
    build_advisor,
    load_knowledge,
    refresh_youtube,
)

PROJECT_DIR = Path(__file__).resolve().parent.parent / "projects" / "finance_advisor"


def test_knowledge_files_are_valid_json():
    files = sorted(KNOWLEDGE_DIR.glob("*.json"))
    assert len(files) >= 7
    for path in files:
        data = json.loads(path.read_text())
        assert data["domain"].startswith("finance.")
        assert data["entries"], f"{path.name} has no entries"
        for entry in data["entries"]:
            assert entry["title"] and entry["content"]
            assert 0.0 <= entry.get("confidence", 0.8) <= 1.0


def test_load_knowledge_populates_store():
    store = load_knowledge()
    assert store.size >= 75
    domains = store.stats()["domains"]
    for expected in (
        "finance.debt",
        "finance.saving",
        "finance.budgeting",
        "finance.credit",
        "finance.investing",
        "finance.assets",
        "finance.india",
        "finance.crypto",
        "finance.gold_silver",
        "finance.trends",
        "finance.frameworks",
        "finance.youtube",
    ):
        assert expected in domains


def test_search_and_tags():
    store = load_knowledge()
    assert store.search("avalanche", domain="finance.debt")
    assert store.search("emergency fund")
    assert store.search("SIP", domain="finance.india")
    assert store.search("30%", domain="finance.crypto")
    assert store.search("SGB", domain="finance.gold_silver")
    assert store.by_tag("youtube")
    assert store.by_tag("emergency-fund")
    assert store.by_tag("asset-allocation")
    assert store.by_tag("india")


def test_advisor_definition_is_valid():
    defn = build_advisor()
    assert defn.type == "finance_advisor"
    assert len(defn.skills) == 6
    assert "finance.debt_plan" in defn.intents
    assert "finance.allocate" in defn.intents
    assert defn.get_prompt("system") is not None
    warnings = DefinitionLoader().validate(defn)
    assert warnings == []
    constraint_names = {c.name for c in defn.constraints}
    assert "not_licensed_advice" in constraint_names


def test_youtube_refresh_skips_without_key(monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    store = load_knowledge()
    before = store.size
    assert refresh_youtube(store) == 0
    assert store.size == before


def test_alert_rule_evaluation_offline():
    from projects.finance_advisor.alerts import AlertRule, evaluate_all, evaluate_rule

    quote = {
        "key": "gold",
        "name": "Gold ETF",
        "price": 110.0,
        "pct_from_52w_high": -21.4,
        "change_1d_pct": -3.2,
        "signal": "dip-watch",
        "signal_reason": "21.4% below 52-week high",
    }
    assert evaluate_rule(AlertRule(asset="gold", condition="price_below", threshold=115), quote)
    assert not evaluate_rule(AlertRule(asset="gold", condition="price_below", threshold=100), quote)
    assert evaluate_rule(
        AlertRule(asset="gold", condition="drop_from_52w_high_pct", threshold=10), quote
    )
    assert evaluate_rule(
        AlertRule(asset="gold", condition="day_change_below_pct", threshold=2), quote
    )
    assert evaluate_rule(AlertRule(asset="gold", condition="signal_dip_watch"), quote)

    rules = [
        AlertRule(asset="gold", condition="price_above", threshold=100),
        AlertRule(asset="gold", condition="price_above", threshold=100, active=False),
        AlertRule(asset="bitcoin", condition="price_below", threshold=1),
    ]
    triggered = evaluate_all(rules, [quote])
    assert len(triggered) == 1


def test_signal_zones():
    from projects.finance_advisor.market_data import AssetQuote, compute_signal

    dip = AssetQuote(key="x", name="x", kind="metal", pct_from_52w_high=-18, vs_sma50_pct=-4)
    assert compute_signal(dip)[0] == "dip-watch"
    hot = AssetQuote(key="x", name="x", kind="metal", pct_from_52w_high=-1, vs_sma50_pct=14)
    assert compute_signal(hot)[0] == "extended"
    mid = AssetQuote(key="x", name="x", kind="metal", pct_from_52w_high=-5, vs_sma50_pct=2)
    assert compute_signal(mid)[0] == "neutral"


def test_property_watch_data():
    data = json.loads((PROJECT_DIR / "data" / "property_watch.json").read_text())
    assert data["india"]["cities"] and data["ireland"]["regions"]
    for row in data["india"]["cities"]:
        assert isinstance(row["yoy_pct"], (int, float))


def test_email_skipped_without_smtp_config(monkeypatch):
    from projects.finance_advisor.alerts import send_email

    for var in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    assert send_email("s", "b", "x@example.com") is False
