"""The tools the agent may call.

All of them are local or read-only public market data. Nothing here can move
money, place an order, or send mail. Memory recall goes through the SDK, so
records flagged `sensitive` are redacted *before* they can reach an LLM.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from finance_advisor.gather import load_knowledge
from finance_advisor.market_data import fetch_all_quotes, fetch_fund_navs, fetch_fx
from finance_advisor.memory import FinanceMemorySDK
from finance_advisor.memory.skills import SKILLS

MAX_RESULT_CHARS = 6000


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    run: Callable[..., object]

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": props,
        "required": required or [],
        "additionalProperties": False,
    }


_STR = {"type": "string"}
_INT = {"type": "integer"}
_NUM = {"type": "number"}
_BOOL = {"type": "boolean"}

# Fields that exist for the dashboard's charts and have no value in a prompt.
# `sparkline` alone is 30 floats per asset — it pushed the raw snapshot past
# MAX_RESULT_CHARS, so the model received truncated, unparseable JSON.
_CHART_ONLY = ("sparkline", "key")


def _compact_quote(quote: dict) -> dict:
    """Drop chart-only fields and round; the model reads numbers, not pixels."""
    return {
        k: round(v, 2) if isinstance(v, float) else v
        for k, v in quote.items()
        if k not in _CHART_ONLY and v not in (None, "")
    }


def build_toolset(sdk: FinanceMemorySDK, property_file=None) -> dict[str, Tool]:
    """Bind every tool to one memory SDK instance."""
    _knowledge: list = []

    def knowledge():
        if not _knowledge:
            _knowledge.append(load_knowledge())
        return _knowledge[0]

    def recall_memory(query: str, limit: int = 5) -> dict:
        return {"hits": sdk.recall(query, limit=min(int(limit), 10))}

    def remember_fact(
        content: str,
        tags: list[str] | None = None,
        importance: float = 0.6,
        sensitive: bool = False,
    ) -> dict:
        return sdk.remember(
            content,
            type="semantic",
            tags=tags or ["profile"],
            importance=float(importance),
            sensitive=bool(sensitive),
        )

    def user_profile() -> dict:
        return {"profile": sdk.profile()}

    def market_snapshot() -> dict:
        return {"quotes": [_compact_quote(q) for q in fetch_all_quotes()], "fx": fetch_fx()}

    def fund_navs() -> dict:
        return {"funds": fetch_fund_navs()}

    def run_skill(skill: str, args: dict | None = None) -> dict:
        if skill not in SKILLS:
            return {"error": f"unknown skill {skill!r}", "available": sorted(SKILLS)}
        try:
            return sdk.advise(skill, **(args or {}))
        except (ValueError, TypeError) as err:
            return {"error": str(err)}

    def knowledge_search(query: str, limit: int = 5) -> dict:
        hits = knowledge().search(query)[: min(int(limit), 8)]
        return {
            "results": [{"title": e.title, "domain": e.domain, "content": e.content} for e in hits]
        }

    def property_watch() -> dict:
        import json

        if property_file is None or not property_file.exists():
            return {"error": "property data unavailable"}
        return json.loads(property_file.read_text())

    def build_scenario_plan(scenario: dict) -> dict:
        from finance_advisor.planner import Scenario, build_plan

        try:
            plan = build_plan(Scenario(**scenario))
        except ValueError as err:
            return {"error": f"invalid scenario: {err}"}
        # Trim what the prompt cannot use: the year-by-year series is for the
        # chart, and echoing the scenario back costs tokens to tell the model
        # what it just sent.
        return plan.model_dump(
            exclude={"scenario": True, "projections": {"__all__": {"net_worth_by_year"}}}
        )

    def what_if(scenario: dict, key: str, params: dict | None = None) -> dict:
        from finance_advisor.planner import Scenario, run_variant

        try:
            return run_variant(Scenario(**scenario), key, params or {})
        except ValueError as err:
            return {"error": f"invalid scenario: {err}"}
        except KeyError as err:
            return {"error": str(err)}

    tools = [
        Tool(
            "recall_memory",
            "Search what the user has told you before (income, goals, holdings, "
            "risk appetite). Call this FIRST on any personalised question. "
            "Records marked sensitive come back redacted by design.",
            _obj({"query": _STR, "limit": _INT}, ["query"]),
            recall_memory,
        ),
        Tool(
            "remember_fact",
            "Store a durable fact the user has just stated about themselves, as "
            "'key=value' where possible (e.g. 'take_home=180000'). Set sensitive "
            "when it is an exact salary, balance or account detail.",
            _obj(
                {
                    "content": _STR,
                    "tags": {"type": "array", "items": _STR},
                    "importance": _NUM,
                    "sensitive": _BOOL,
                },
                ["content"],
            ),
            remember_fact,
        ),
        Tool(
            "user_profile",
            "All durable profile facts learned so far, as a key/value map.",
            _obj({}),
            user_profile,
        ),
        Tool(
            "market_snapshot",
            "Live prices for the watched assets (gold, silver, Bitcoin, Nifty, "
            "S&P 500 and friends) with 1d/30d moves, distance from the 52-week "
            "high, and the rule-based dip-watch / extended / neutral signal. "
            "Also returns USD/INR and USD/EUR.",
            _obj({}),
            market_snapshot,
        ),
        Tool(
            "fund_navs",
            "Latest AMFI NAVs for the Indian direct-growth SIP watchlist.",
            _obj({}),
            fund_navs,
        ),
        Tool(
            "run_skill",
            "Run a finance calculation. skill is one of: loans (EMI, "
            "affordability, prepay-vs-invest, avalanche/snowball), mutual_funds "
            "(SIP future value, step-up, goal planning), crypto (allocation cap, "
            "30% VDA tax + 1% TDS), capital_gains (LTCG 12.5% above ₹1.25L, STCG "
            "20%), taxes (80C/80CCD room, regime pointers, asset-wise treatment). "
            "Pass the numbers in args.",
            _obj(
                {
                    "skill": {"type": "string", "enum": sorted(SKILLS)},
                    "args": {"type": "object", "additionalProperties": True},
                },
                ["skill"],
            ),
            run_skill,
        ),
        Tool(
            "knowledge_search",
            "Search the curated saving / debt / budgeting / India / trends "
            "knowledge base gathered from financial educators.",
            _obj({"query": _STR, "limit": _INT}, ["query"]),
            knowledge_search,
        ),
        Tool(
            "build_scenario_plan",
            "Turn the user's whole situation into an ordered, step-by-step plan "
            "with milestones, per-goal monthly requirements, an insurance gap "
            "check and a projection band. Use this whenever they describe income, "
            "expenses, debts or goals together and want to know where to start. "
            "scenario keys: monthly_income, monthly_expenses, cash_savings, "
            "existing_investments, annual_bonus, annual_increment_pct, age, "
            "dependants, employment (salaried|self_employed|business), term_cover, "
            "health_cover, tax_regime (new|old), existing_80c, timeline_months, "
            "inflation_pct, strategy (avalanche|snowball), debts:[{name, balance, "
            "annual_rate_pct, min_payment}], goals:[{name, amount_today, years}]. "
            "Only monthly_income and monthly_expenses are required.",
            _obj({"scenario": {"type": "object", "additionalProperties": True}}, ["scenario"]),
            build_scenario_plan,
        ),
        Tool(
            "what_if",
            "Re-run a scenario under one changed assumption and report the "
            "difference against the baseline. keys: extra_monthly, lump_sum, "
            "job_loss, rate_shock, cut_expenses, snowball, avalanche, prepay_all, "
            "invest_instead, high_inflation. Optional params, e.g. "
            "{'amount': 5000} or {'months': 3, 'drop_pct': 100}.",
            _obj(
                {
                    "scenario": {"type": "object", "additionalProperties": True},
                    "key": _STR,
                    "params": {"type": "object", "additionalProperties": True},
                },
                ["scenario", "key"],
            ),
            what_if,
        ),
        Tool(
            "property_watch",
            "Residential property price indices for India (NHB RESIDEX) and "
            "Ireland (CSO RPPI) — periodic official data, not a live feed.",
            _obj({}),
            property_watch,
        ),
    ]
    return {t.name: t for t in tools}


def execute(tools: dict[str, Tool], name: str, arguments: dict) -> object:
    """Run one tool, converting any failure into a result the model can read."""
    tool = tools.get(name)
    if tool is None:
        return {"error": f"unknown tool {name!r}", "available": sorted(tools)}
    try:
        return tool.run(**arguments)
    except TypeError as err:
        return {"error": f"bad arguments for {name}: {err}"}
    except Exception as err:  # a tool failure must not kill the conversation
        return {"error": f"{name} failed: {type(err).__name__}: {err}"}
