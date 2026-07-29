"""Scenario planner: describe your situation, get an ordered plan and what-ifs.

    from finance_advisor.planner import Scenario, Debt, Goal, build_plan, run_variant

    plan = build_plan(Scenario(
        monthly_income=180_000, monthly_expenses=90_000, cash_savings=200_000,
        debts=[Debt(name="Credit card", balance=180_000,
                    annual_rate_pct=42, min_payment=9_000)],
        goals=[Goal(name="House deposit", amount_today=2_000_000, years=5)],
        age=34, dependants=2, timeline_months=120,
    ))
    run_variant(plan.scenario, "extra_monthly", {"amount": 5000})

Deterministic throughout — every figure is arithmetic on the user's own inputs
under assumptions printed on the result. Projections come as a band, never a
single number, because a single number reads as a promise.
"""

from finance_advisor.planner.engine import build_plan, protection_gap, simulate
from finance_advisor.planner.models import (
    DEFAULT_HURDLE_RATE_PCT,
    DEFAULT_INFLATION_PCT,
    RETURN_BANDS,
    Debt,
    Employment,
    Goal,
    GoalOutlook,
    Milestone,
    Plan,
    Projection,
    ProtectionGap,
    Scenario,
    Step,
    Strategy,
    TaxRegime,
)
from finance_advisor.planner.whatif import VARIANTS, catalog, compare_all, run_variant

__all__ = [
    "DEFAULT_HURDLE_RATE_PCT",
    "DEFAULT_INFLATION_PCT",
    "RETURN_BANDS",
    "VARIANTS",
    "Debt",
    "Employment",
    "Goal",
    "GoalOutlook",
    "Milestone",
    "Plan",
    "Projection",
    "ProtectionGap",
    "Scenario",
    "Step",
    "Strategy",
    "TaxRegime",
    "build_plan",
    "catalog",
    "compare_all",
    "protection_gap",
    "run_variant",
    "simulate",
]
