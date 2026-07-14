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
    assert store.size >= 40
    domains = store.stats()["domains"]
    for expected in (
        "finance.debt",
        "finance.saving",
        "finance.budgeting",
        "finance.credit",
        "finance.investing",
        "finance.frameworks",
        "finance.youtube",
    ):
        assert expected in domains


def test_search_and_tags():
    store = load_knowledge()
    assert store.search("avalanche", domain="finance.debt")
    assert store.search("emergency fund")
    assert store.by_tag("youtube")
    assert store.by_tag("emergency-fund")


def test_advisor_definition_is_valid():
    defn = build_advisor()
    assert defn.type == "finance_advisor"
    assert len(defn.skills) == 5
    assert "finance.debt_plan" in defn.intents
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
