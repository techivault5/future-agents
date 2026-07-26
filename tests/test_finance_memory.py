"""Tests for the finance memory framework, skills and cross-runtime SDK parity."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from projects.finance_advisor.memory import (
    RUNTIME_MATRIX,
    ComputeTarget,
    FinanceMemorySDK,
    GraphBackend,
    HashingEmbedder,
    InMemoryBackend,
    MemoryManager,
    MemoryType,
    SqliteBackend,
    detect_available,
    skill_catalog,
)
from projects.finance_advisor.memory.aliases import expand
from projects.finance_advisor.memory.embeddings import cosine
from projects.finance_advisor.memory.skills import (
    CapitalGainsSkill,
    CryptoSkill,
    LoanAdvisorSkill,
    MutualFundSkill,
    TaxGuidanceSkill,
)

JS_SDK = Path(__file__).parent.parent / "projects/finance_advisor/memory/sdk/js/finance-memory.mjs"


# ── memory types and manager ─────────────────────────────────────────────────


def test_all_five_memory_types_round_trip():
    manager = MemoryManager()
    for mem_type in MemoryType:
        manager.remember(f"a {mem_type.value} memory", type=mem_type)
    stats = manager.stats()
    assert stats["total"] == 5
    assert set(stats["by_type"]) == {t.value for t in MemoryType}


def test_working_memory_gets_default_ttl_and_expires():
    manager = MemoryManager()
    record = manager.remember("scratch", type=MemoryType.WORKING)
    assert record.ttl_seconds == 3600
    record.ttl_seconds = 0
    manager.backend.put(record)
    assert record.is_expired()
    assert manager.recall("scratch") == []
    assert manager.recall("scratch", include_expired=True)


def test_sensitive_records_are_redacted_in_recall_and_export():
    sdk = FinanceMemorySDK()
    sdk.remember("take_home=180000", tags=["profile"], sensitive=True)
    assert sdk.recall("income")[0]["content"] == "[redacted:sensitive]"
    assert all("180000" not in json.dumps(item) for item in sdk.export())
    # the raw value is still usable internally for skills
    assert sdk.profile()["take_home"] == "180000"


def test_recall_ranks_relevant_memory_first_with_alias_expansion():
    sdk = FinanceMemorySDK()
    sdk.remember("take_home=180000", tags=["profile"])
    sdk.remember("asked about gold dip buying", type=MemoryType.EPISODIC)
    sdk.remember("silver is volatile", type=MemoryType.EPISODIC)
    assert sdk.recall("what is my income", limit=1)[0]["content"] == "take_home=180000"
    assert "gold" in sdk.recall("is gold a buy", limit=1)[0]["content"]


def test_alias_expansion_is_additive_and_deduped():
    expanded = expand(["income", "income"])
    assert expanded[:2] == ["income", "income"]
    assert "take_home" in expanded
    assert len(expanded) == len(set(expanded)) + 1  # only the duplicate input repeats


def test_consolidation_promotes_recurring_episodes():
    manager = MemoryManager()
    for text in ("gold dip question", "gold etf question", "gold allocation question"):
        manager.remember(text, type=MemoryType.EPISODIC)
    created = manager.consolidate(min_occurrences=3)
    assert any("gold" in r.content for r in created)
    assert all("consolidated" in r.tags for r in created)
    # idempotent: running again creates nothing new
    assert manager.consolidate(min_occurrences=3) == []


def test_forget_removes_expired_and_worthless_records():
    manager = MemoryManager()
    keeper = manager.remember("important fact", importance=0.9)
    manager.remember("noise", importance=0.05)
    assert manager.forget() == 1
    assert manager.backend.get(keeper.id) is not None


def test_context_block_is_prompt_ready_and_redacted():
    sdk = FinanceMemorySDK()
    sdk.remember("take_home=180000", tags=["profile"], sensitive=True)
    block = sdk.context("income")
    assert block.startswith("- [semantic]")
    assert "180000" not in block


def test_export_import_round_trip_across_stores():
    source = FinanceMemorySDK()
    source.remember("risk_tolerance=moderate", tags=["profile"])
    source.remember("asked about SIP", type=MemoryType.EPISODIC)
    target = FinanceMemorySDK(store="sqlite", path=":memory:")
    assert target.import_records(source.export()) == 2
    assert target.profile()["risk_tolerance"] == "moderate"


# ── backends ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("store", ["memory", "sqlite", "graph"])
def test_every_store_supports_the_same_operations(store, tmp_path):
    path = str(tmp_path / "m.db") if store == "sqlite" else None
    sdk = FinanceMemorySDK(store=store, path=path)
    sdk.remember("goal=house in 5 years", tags=["profile", "goal"])
    assert sdk.stats()["total"] == 1
    assert sdk.recall("house")[0]["content"].startswith("goal=")


def test_sqlite_backend_persists_across_connections(tmp_path):
    db = tmp_path / "memory.db"
    first = SqliteBackend(db)
    manager = MemoryManager(backend=first)
    manager.remember("epf balance grows tax free")
    first.close()

    reopened = MemoryManager(backend=SqliteBackend(db))
    assert reopened.stats()["total"] == 1
    assert reopened.recall("epf")[0].record.content.startswith("epf")


def test_sqlite_keyword_search_finds_content(tmp_path):
    backend = SqliteBackend(tmp_path / "kw.db")
    MemoryManager(backend=backend).remember("ELSS has a three year lock-in")
    assert backend.keyword_search("ELSS")


def test_graph_backend_links_neighbours_and_exports_cypher():
    backend = GraphBackend(InMemoryBackend())
    manager = MemoryManager(backend=backend)
    record = manager.remember("holds GOLDBEES ETF", type=MemoryType.GRAPH)
    assert manager.link(record.id, "holds", "GOLDBEES")
    assert backend.neighbors(record.id, predicate="holds") == [("holds", "GOLDBEES")]
    cypher = backend.to_cypher()
    assert any("MERGE (m:Memory" in stmt for stmt in cypher)
    assert any("HOLDS" in stmt for stmt in cypher)


# ── embeddings ───────────────────────────────────────────────────────────────


def test_hashing_embedder_is_deterministic_and_normalised():
    embedder = HashingEmbedder()
    first = embedder.embed("SIP ₹25000 flexi cap")
    assert first == embedder.embed("SIP ₹25000 flexi cap")
    assert abs(sum(v * v for v in first) - 1.0) < 1e-9
    assert embedder.embed("") == [0.0] * embedder.dim


def test_cosine_similarity_bounds():
    embedder = HashingEmbedder()
    same = embedder.embed("gold etf")
    assert cosine(same, same) == pytest.approx(1.0)
    assert cosine(same, embedder.embed("")) == 0.0
    assert 0.0 <= cosine(same, embedder.embed("silver futures")) < 1.0


# ── runtimes ─────────────────────────────────────────────────────────────────


def test_runtime_matrix_covers_all_five_compute_targets():
    targets = {profile.target for profile in RUNTIME_MATRIX}
    assert targets == set(ComputeTarget)
    assert all(profile.offline for profile in RUNTIME_MATRIX)


def test_capabilities_detection_always_recommends_something():
    caps = detect_available()
    assert caps.recommended
    assert caps.system and caps.python_version
    assert isinstance(caps.to_dict(), dict)


# ── skills ───────────────────────────────────────────────────────────────────


def test_skill_catalog_lists_all_five_skills():
    names = {entry["name"] for entry in skill_catalog()}
    assert names == {"loans", "mutual_funds", "crypto", "capital_gains", "taxes"}
    assert all(entry["covers"] for entry in skill_catalog())


def test_loan_emi_matches_closed_form():
    # ₹35L at 8.6% over 240 months: standard reducing-balance EMI
    assert LoanAdvisorSkill.emi(3_500_000, 8.6, 240) == pytest.approx(30_595.70, abs=0.5)
    assert LoanAdvisorSkill.emi(120_000, 0, 12) == pytest.approx(10_000)
    with pytest.raises(ValueError):
        LoanAdvisorSkill.emi(100, 10, 0)


def test_loan_affordability_and_payoff_order():
    skill = LoanAdvisorSkill()
    afford = skill.affordability(100_000, existing_emi=10_000)
    assert afford["total_emi_ceiling"] == 40_000
    assert afford["housing_emi_ceiling"] == 30_000
    assert afford["headroom"] == 30_000

    wide = skill.payoff_order(
        [
            {"name": "card", "balance": 80_000, "apr": 22},
            {"name": "car", "balance": 300_000, "apr": 9},
        ]
    )
    assert wide["avalanche_order"][0] == "card"
    assert wide["snowball_order"][0] == "card"
    assert wide["recommended"] == "avalanche"

    narrow = skill.payoff_order(
        [
            {"name": "a", "balance": 50_000, "apr": 10},
            {"name": "b", "balance": 20_000, "apr": 11},
        ]
    )
    assert narrow["recommended"].startswith("snowball")


def test_prepay_vs_invest_thresholds():
    skill = LoanAdvisorSkill()
    assert skill.prepay_vs_invest(22)["verdict"].startswith("prepay")
    assert skill.prepay_vs_invest(4)["verdict"].startswith("invest")
    assert "defensible" in skill.prepay_vs_invest(7)["verdict"]


def test_sip_maths_step_up_beats_flat_and_goal_inverts():
    flat = MutualFundSkill.sip_future_value(10_000, 12, 10)
    assert flat > 10_000 * 120  # compounding beats contributions
    stepped = MutualFundSkill.step_up_sip_future_value(10_000, 12, 10, 10)
    assert stepped > flat
    required = MutualFundSkill.required_sip(flat, 12, 10)
    assert required == pytest.approx(10_000, rel=0.01)  # inverse of future value
    assert MutualFundSkill.sip_future_value(1_000, 0, 1) == 12_000


def test_cost_drag_penalises_higher_expense_ratio():
    drag = MutualFundSkill.cost_drag(10_000, 15, 12, 1.0)
    assert drag["direct_plan_value"] > drag["regular_plan_value"]
    assert drag["lost_to_commission"] > 0


def test_crypto_caps_and_india_vda_tax():
    assert CryptoSkill.position_cap(1_000_000, "conservative")["cap_amount"] == 0
    assert CryptoSkill.position_cap(1_000_000, "moderate")["cap_amount"] == 50_000
    assert CryptoSkill.position_cap(1_000_000, "aggressive")["cap_amount"] == 100_000

    taxed = CryptoSkill.after_tax_gain(100_000, 200_000)
    assert taxed["vda_tax_30pct"] == 30_000  # flat 30% on the ₹1L gain
    assert taxed["tds_1pct_on_sale"] == 2_000  # 1% of the sale value
    assert taxed["net_gain_after_tax"] == 70_000
    assert CryptoSkill.after_tax_gain(200_000, 100_000)["vda_tax_30pct"] == 0


def test_capital_gains_exemption_and_classification():
    long_term = CapitalGainsSkill.equity_gain_tax(500_000, 800_000, 18)
    assert long_term["classification"] == "long-term"
    assert long_term["exemption_applied"] == 125_000
    assert long_term["tax"] == pytest.approx(21_875)  # (300k − 125k) × 12.5%

    short_term = CapitalGainsSkill.equity_gain_tax(500_000, 800_000, 6)
    assert short_term["classification"] == "short-term"
    assert short_term["tax"] == pytest.approx(60_000)  # 300k × 20%

    used_up = CapitalGainsSkill.equity_gain_tax(0, 100_000, 24, prior_ltcg_used=125_000)
    assert used_up["taxable_gain"] == 100_000

    loss = CapitalGainsSkill.equity_gain_tax(800_000, 500_000, 18)
    assert loss["tax"] == 0
    assert "carried forward" in loss["note"]


def test_harvest_plan_respects_annual_exemption():
    plan = CapitalGainsSkill.harvest_plan(500_000, prior_ltcg_used=25_000)
    assert plan["exemption_room"] == 100_000
    assert plan["harvestable_now"] == 100_000


def test_tax_regime_guidance_differs_by_regime():
    new = TaxGuidanceSkill.deduction_capacity(regime="new")
    assert new["section_80c_room"] == 0
    old = TaxGuidanceSkill.deduction_capacity(existing_80c=50_000, regime="old")
    assert old["section_80c_room"] == 100_000
    assert old["nps_80ccd1b_room"] == 50_000
    assets = TaxGuidanceSkill.asset_treatment()
    assert any("Crypto" in row["asset"] for row in assets)


def test_every_skill_result_carries_the_disclaimer_and_writes_memory():
    sdk = FinanceMemorySDK()
    calls = {
        "loans": {"principal": 1_000_000, "annual_rate_pct": 9, "months": 120},
        "mutual_funds": {"monthly": 5_000, "years": 10},
        "crypto": {"portfolio_value": 500_000},
        "capital_gains": {"buy_value": 100_000, "sell_value": 150_000, "holding_months": 18},
        "taxes": {"regime": "old"},
    }
    for name, kwargs in calls.items():
        result = sdk.advise(name, **kwargs)
        assert result["disclaimer"] == "Educational content, not licensed financial advice."
        assert result["skill"] == name
        assert "memory_context" in result
    assert sdk.stats()["total"] > 0


def test_unknown_skill_raises():
    with pytest.raises(KeyError):
        FinanceMemorySDK().skill("day_trading")


# ── cross-runtime parity (the claim that makes the SDKs interchangeable) ─────


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_js_and_python_embeddings_are_identical():
    """The JS SDK must hash to the same vectors, or memories are not portable."""
    texts = ["take_home=180000", "gold dip buy window", "LTCG ₹1.25L harvesting", ""]
    embedder = HashingEmbedder()
    expected = {t: embedder.embed(t) for t in texts}

    script = f"""
    import {{ HashingEmbedder }} from '{JS_SDK.as_posix()}';
    const e = new HashingEmbedder();
    const out = {{}};
    for (const t of {json.dumps(texts)}) out[t] = e.embed(t);
    console.log(JSON.stringify(out));
    """
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    actual = json.loads(proc.stdout)
    for text, py_vec in expected.items():
        js_vec = actual[text]
        assert len(js_vec) == len(py_vec)
        assert max(abs(a - b) for a, b in zip(py_vec, js_vec)) < 1e-9, f"drift on {text!r}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_js_skills_agree_with_python_skills():
    """Same inputs must give the same numbers in both runtimes."""
    script = f"""
    import {{ FinanceMemorySDK }} from '{JS_SDK.as_posix()}';
    const sdk = new FinanceMemorySDK();
    console.log(JSON.stringify({{
      emi: sdk.advise('loans', {{principal: 3500000, annualRatePct: 8.6, months: 240}}).emi,
      sip: sdk.advise('mutual_funds',
        {{monthly: 25000, years: 15, annualReturnPct: 12}}).future_value,
      cg: sdk.advise('capital_gains',
        {{buyValue: 500000, sellValue: 800000, holdingMonths: 18}}).tax,
      crypto: sdk.advise('crypto', {{portfolioValue: 2000000}}).cap_amount,
      tax: sdk.advise('taxes', {{regime: 'old', existing80c: 50000}}).section_80c_room,
    }}));
    """
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    js = json.loads(proc.stdout)
    sdk = FinanceMemorySDK()
    assert js["emi"] == pytest.approx(
        sdk.advise("loans", principal=3_500_000, annual_rate_pct=8.6, months=240)["emi"]
    )
    assert js["sip"] == pytest.approx(
        sdk.advise("mutual_funds", monthly=25_000, years=15, annual_return_pct=12)["future_value"]
    )
    assert js["cg"] == pytest.approx(
        sdk.advise("capital_gains", buy_value=500_000, sell_value=800_000, holding_months=18)["tax"]
    )
    assert js["crypto"] == pytest.approx(
        sdk.advise("crypto", portfolio_value=2_000_000)["cap_amount"]
    )
    assert js["tax"] == pytest.approx(
        sdk.advise("taxes", regime="old", existing_80c=50_000)["section_80c_room"]
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_vscode_extension_and_js_sdk_parse():
    ext = JS_SDK.parent.parent / "vscode" / "extension.js"
    for target in (ext,):
        subprocess.run(["node", "--check", str(target)], check=True, timeout=60)
    manifest = json.loads((ext.parent / "package.json").read_text())
    commands = {c["command"] for c in manifest["contributes"]["commands"]}
    assert "financeMemory.runSkill" in commands
    assert manifest["main"] == "./extension.js"
