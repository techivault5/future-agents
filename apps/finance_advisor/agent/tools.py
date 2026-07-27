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
        return {"quotes": fetch_all_quotes(), "fx": fetch_fx()}

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
