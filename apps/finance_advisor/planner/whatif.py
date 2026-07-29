"""What-if variants: the same scenario under a different assumption.

Every variant runs through `simulate()` with the baseline, so a comparison is
never between two differently-built numbers. The deltas are what the user
actually wants — "what does this change buy me" — not two absolute figures they
have to difference themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from finance_advisor.planner.engine import _months, inr, simulate
from finance_advisor.planner.models import (
    RETURN_BANDS,
    Projection,
    Scenario,
    Strategy,
)


@dataclass
class Variant:
    key: str
    label: str
    question: str
    apply: Callable[[Scenario, dict], tuple[Scenario, dict]]


def _extra(scenario: Scenario, params: dict) -> tuple[Scenario, dict]:
    return scenario, {"extra_monthly": float(params.get("amount", 5000))}


def _lump(scenario: Scenario, params: dict) -> tuple[Scenario, dict]:
    return scenario, {"lump_sum": float(params.get("amount", 100000))}


def _job_loss(scenario: Scenario, params: dict) -> tuple[Scenario, dict]:
    return scenario, {
        "income_drop_pct": float(params.get("drop_pct", 100)),
        "income_drop_months": int(params.get("months", 3)),
    }


def _rate_shock(scenario: Scenario, params: dict) -> tuple[Scenario, dict]:
    delta = float(params.get("delta_pct", 2.0))
    shocked = scenario.model_copy(deep=True)
    for debt in shocked.debts:
        debt.annual_rate_pct = min(debt.annual_rate_pct + delta, 100.0)
    return shocked, {}


def _snowball(scenario: Scenario, params: dict) -> tuple[Scenario, dict]:
    return scenario.model_copy(update={"strategy": Strategy.SNOWBALL}), {}


def _avalanche(scenario: Scenario, params: dict) -> tuple[Scenario, dict]:
    return scenario.model_copy(update={"strategy": Strategy.AVALANCHE}), {}


def _prepay_everything(scenario: Scenario, params: dict) -> tuple[Scenario, dict]:
    """Drop the hurdle to zero: clear every debt before investing a rupee."""
    return scenario.model_copy(update={"hurdle_rate_pct": 0.0}), {}


def _invest_instead(scenario: Scenario, params: dict) -> tuple[Scenario, dict]:
    """Raise the hurdle above every rate: pay only minimums, invest the rest."""
    return scenario.model_copy(update={"hurdle_rate_pct": 100.0}), {}


def _lean_expenses(scenario: Scenario, params: dict) -> tuple[Scenario, dict]:
    cut = float(params.get("cut_pct", 10))
    return scenario.model_copy(
        update={"monthly_expenses": scenario.monthly_expenses * (1 - cut / 100)}
    ), {}


def _high_inflation(scenario: Scenario, params: dict) -> tuple[Scenario, dict]:
    return scenario.model_copy(update={"inflation_pct": float(params.get("inflation_pct", 9))}), {}


VARIANTS: dict[str, Variant] = {
    v.key: v
    for v in [
        Variant(
            "extra_monthly",
            "Invest ₹X more each month",
            "What does an extra ₹5,000 a month actually buy me?",
            _extra,
        ),
        Variant(
            "lump_sum",
            "Put a windfall in today",
            "A bonus or maturity lands today — where does it leave me?",
            _lump,
        ),
        Variant(
            "job_loss",
            "Lose income for a few months",
            "Could I survive three months with no income?",
            _job_loss,
        ),
        Variant(
            "rate_shock",
            "Loan rates rise",
            "What if every rate on my debt goes up 2 points?",
            _rate_shock,
        ),
        Variant(
            "cut_expenses",
            "Spend less each month",
            "What is a 10% spending cut worth over the whole horizon?",
            _lean_expenses,
        ),
        Variant(
            "snowball",
            "Smallest balance first",
            "Does snowball cost me much versus avalanche?",
            _snowball,
        ),
        Variant(
            "avalanche",
            "Highest rate first",
            "How much does avalanche save versus snowball?",
            _avalanche,
        ),
        Variant(
            "prepay_all",
            "Clear every debt before investing",
            "What if I refuse to invest while I owe anything?",
            _prepay_everything,
        ),
        Variant(
            "invest_instead",
            "Pay minimums, invest the rest",
            "What if I invest instead of prepaying?",
            _invest_instead,
        ),
        Variant(
            "high_inflation",
            "Inflation runs hotter",
            "What does 9% inflation do to this plan?",
            _high_inflation,
        ),
    ]
}


def catalog() -> list[dict]:
    """The what-ifs on offer, for a UI or an agent to choose from."""
    return [{"key": v.key, "label": v.label, "question": v.question} for v in VARIANTS.values()]


def run_variant(scenario: Scenario, key: str, params: dict | None = None) -> dict:
    """Run one variant against the baseline and return both plus the deltas."""
    if key not in VARIANTS:
        raise KeyError(f"unknown what-if {key!r}; available: {sorted(VARIANTS)}")
    variant = VARIANTS[key]
    rate = RETURN_BANDS["base"]

    baseline = simulate(scenario, rate)
    changed_scenario, overrides = variant.apply(scenario, params or {})
    changed = simulate(changed_scenario, rate, **overrides)

    result = {
        "key": key,
        "label": variant.label,
        "question": variant.question,
        "baseline": baseline.model_dump(),
        "variant": changed.model_dump(),
        "delta": _delta(baseline, changed),
        "summary": _summarise(variant, baseline, changed),
    }
    crossed = _hurdle_crossings(scenario, changed_scenario)
    if crossed:
        result["note"] = (
            f"The plan itself changed: {crossed} crossed your "
            f"{scenario.hurdle_rate_pct:.0f}% hurdle, so the surplus now goes at that "
            "debt instead of into investments. That is why the interest figure can "
            "move in a direction that looks backwards — you are comparing two "
            "different strategies, not just two rates."
        )
    return result


def _hurdle_crossings(before: Scenario, after: Scenario) -> str:
    """Debts that moved across the hurdle, which silently changes the strategy."""
    was = {d.name: d.annual_rate_pct >= before.hurdle_rate_pct for d in before.debts}
    now = {d.name: d.annual_rate_pct >= after.hurdle_rate_pct for d in after.debts}
    moved = [name for name, flag in now.items() if was.get(name) is not None and was[name] != flag]
    if not moved:
        return ""
    return f"{', '.join(moved)} " + ("has" if len(moved) == 1 else "have")


def compare_all(scenario: Scenario, keys: list[str] | None = None) -> list[dict]:
    """Run several what-ifs so their effects can be ranked against each other."""
    return [run_variant(scenario, key) for key in (keys or list(VARIANTS))]


def _delta(baseline: Projection, changed: Projection) -> dict:
    def months_delta() -> int | None:
        if baseline.debt_free_month is None or changed.debt_free_month is None:
            return None
        return changed.debt_free_month - baseline.debt_free_month

    return {
        "net_worth": round(changed.final_net_worth - baseline.final_net_worth, 2),
        "interest_paid": round(changed.total_interest_paid - baseline.total_interest_paid, 2),
        "debt_free_months": months_delta(),
        "final_cash": round(changed.final_cash - baseline.final_cash, 2),
    }


def _summarise(variant: Variant, baseline: Projection, changed: Projection) -> str:
    """One plain sentence, in the direction a human reads it."""
    net = changed.final_net_worth - baseline.final_net_worth
    interest = changed.total_interest_paid - baseline.total_interest_paid

    # "No change" is a real answer and deserves saying so, rather than a row of
    # zeroes the reader has to interpret as a null result.
    if abs(net) < 1 and abs(interest) < 1:
        return (
            "No measurable difference in this scenario. That usually means the "
            "lever does not apply here — for example, debt ordering cannot matter "
            "when only one debt is above the hurdle rate."
        )

    parts = [
        f"Net worth {'up' if net >= 0 else 'down'} {inr(abs(net))} over {_months(baseline.months)}"
    ]
    if abs(interest) >= 1:
        parts.append(f"interest {'up' if interest > 0 else 'down'} {inr(abs(interest))}")
    if baseline.debt_free_month is not None and changed.debt_free_month is not None:
        shift = changed.debt_free_month - baseline.debt_free_month
        if shift:
            parts.append(
                f"debt-free {abs(shift)} month{'s' if abs(shift) != 1 else ''} "
                f"{'later' if shift > 0 else 'earlier'}"
            )
        else:
            parts.append("debt-free at the same time")
    if changed.final_cash < 0 <= baseline.final_cash:
        parts.append("cash runs out — this scenario does not survive")
    return "; ".join(parts) + "."
