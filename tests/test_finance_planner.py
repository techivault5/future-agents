"""Scenario planner: the arithmetic, the ordering, and the honesty of the output."""

from __future__ import annotations

import pytest
from finance_advisor.planner import (
    Debt,
    Employment,
    Goal,
    Scenario,
    Strategy,
    TaxRegime,
    build_plan,
    catalog,
    compare_all,
    protection_gap,
    run_variant,
    simulate,
)
from finance_advisor.planner.engine import inr
from finance_advisor.planner.models import RETURN_BANDS


def scenario(**over) -> Scenario:
    base = dict(
        monthly_income=180_000,
        monthly_expenses=90_000,
        cash_savings=200_000,
        annual_increment_pct=0,  # off by default so tests assert clean arithmetic
        inflation_pct=0,
        timeline_months=120,
    )
    return Scenario(**{**base, **over})


CARD = Debt(name="Card", balance=180_000, annual_rate_pct=42, min_payment=9_000)
HOME = Debt(name="Home loan", balance=3_500_000, annual_rate_pct=8.6, min_payment=30_596)


# ── the maths ────────────────────────────────────────────────────────────────


def test_surplus_is_income_less_expenses_and_minimums():
    s = scenario(debts=[CARD, HOME])
    assert s.total_min_payments == pytest.approx(39_596)
    assert s.monthly_surplus == pytest.approx(50_404)


def test_emergency_target_covers_debt_service_not_just_living_costs():
    """A month off still costs you the EMIs — a fund that ignores them is short."""
    s = scenario(debts=[HOME], emergency_fund_months=6)
    assert s.emergency_target == pytest.approx((90_000 + 30_596) * 6)


def test_self_employed_gets_a_longer_buffer_by_default():
    assert scenario(employment=Employment.SALARIED).emergency_fund_months == 6
    assert scenario(employment=Employment.SELF_EMPLOYED).emergency_fund_months == 12


def test_goals_are_inflated_to_their_due_date():
    goal = Goal(name="Deposit", amount_today=1_000_000, years=10)
    assert goal.future_amount(0) == pytest.approx(1_000_000)
    assert goal.future_amount(6) == pytest.approx(1_790_847, rel=1e-4)


def test_retirement_corpus_uses_the_four_percent_convention():
    s = scenario(age=34, retirement_age=60)
    goal = s.retirement_goal()
    assert goal is not None
    assert goal.amount_today == pytest.approx(90_000 * 12 / 0.04)
    assert goal.years == 26


def test_no_retirement_goal_without_an_age():
    assert scenario().retirement_goal() is None


def test_debt_free_month_matches_a_hand_check():
    """₹1.8L card at 42% with ₹59,404/month against it clears inside 4 months."""
    s = scenario(debts=[CARD], cash_savings=1_000_000)
    projection = simulate(s, 12)
    assert projection.debt_free_month in (3, 4)


def test_a_debt_free_scenario_reports_month_zero():
    assert simulate(scenario(), 12).debt_free_month == 0


def test_income_growth_and_inflation_both_move_the_result():
    flat = simulate(scenario(), 12).final_net_worth
    raises = simulate(scenario(annual_increment_pct=8), 12).final_net_worth
    costs = simulate(scenario(inflation_pct=8), 12).final_net_worth
    assert raises > flat > costs


def test_the_bonus_lands_once_a_year_not_monthly():
    with_bonus = simulate(scenario(annual_bonus=120_000), 12).final_net_worth
    without = simulate(scenario(), 12).final_net_worth
    # 10 bonuses, compounded — far short of adding ₹10k every month
    monthly_equivalent = simulate(scenario(monthly_income=190_000), 12).final_net_worth
    assert without < with_bonus < monthly_equivalent


# ── ordering and steps ───────────────────────────────────────────────────────


def test_expensive_debt_is_paid_before_investing():
    plan = build_plan(scenario(debts=[CARD], cash_savings=1_000_000))
    titles = [s.title for s in plan.steps]
    debt_at = next(i for i, t in enumerate(titles) if "Clear debt" in t)
    invest_at = next(i for i, t in enumerate(titles) if "Automate investing" in t)
    assert debt_at < invest_at


def test_insurance_gap_comes_before_everything_else():
    plan = build_plan(scenario(dependants=2, term_cover=0, health_cover=0))
    assert "insurance gap" in plan.steps[0].title.lower()


def test_a_negative_surplus_produces_one_step_and_nothing_else():
    """No plan is honest when outgoings exceed income — say that and stop."""
    plan = build_plan(scenario(monthly_income=50_000, monthly_expenses=80_000))
    assert plan.feasible is False
    assert len(plan.steps) == 1
    assert "gap" in plan.steps[0].title.lower()
    assert any("exceed" in w for w in plan.warnings)


def test_cheap_debt_is_not_ordered_paid_off_early():
    """A sub-hurdle home loan should be presented as a comparison, not a command."""
    plan = build_plan(scenario(debts=[HOME]))
    titles = " ".join(s.title for s in plan.steps)
    assert "Leave the cheap debt running" in titles
    assert "Clear debt above" not in titles


def test_tax_step_only_appears_on_the_old_regime():
    old = build_plan(scenario(tax_regime=TaxRegime.OLD, existing_80c=50_000))
    new = build_plan(scenario(tax_regime=TaxRegime.NEW))
    assert any("deduction headroom" in s.title for s in old.steps)
    assert not any("deduction headroom" in s.title for s in new.steps)


def test_fully_used_80c_produces_no_tax_step():
    plan = build_plan(
        scenario(tax_regime=TaxRegime.OLD, existing_80c=150_000, nps_contribution=50_000)
    )
    assert not any("deduction headroom" in s.title for s in plan.steps)


# ── protection ───────────────────────────────────────────────────────────────


def test_term_cover_need_is_income_multiple_plus_debt_less_assets():
    gap = protection_gap(scenario(debts=[HOME], existing_investments=500_000, term_cover=0))
    assert gap.term_cover_needed == pytest.approx(180_000 * 12 * 10 + 3_500_000 - 500_000)


def test_adequate_cover_reports_no_gap():
    gap = protection_gap(scenario(term_cover=50_000_000, health_cover=5_000_000))
    assert gap.term_cover_gap == 0
    assert gap.health_cover_gap == 0
    assert "adequate" in gap.note


def test_health_cover_floor_rises_with_dependants():
    assert (
        protection_gap(scenario(dependants=0)).health_cover_suggested
        < protection_gap(scenario(dependants=3)).health_cover_suggested
    )


# ── projections stay a range, never a promise ────────────────────────────────


def test_three_bands_are_returned_and_ordered_by_return():
    plan = build_plan(scenario())
    assert {p.band for p in plan.projections} == set(RETURN_BANDS)
    by_rate = sorted(plan.projections, key=lambda p: p.annual_return_pct)
    assert [p.final_net_worth for p in by_rate] == sorted(p.final_net_worth for p in by_rate)


def test_the_headline_quotes_the_spread_not_just_the_middle():
    plan = build_plan(scenario())
    assert "band spans" in plan.headline


def test_disclaimer_refuses_the_word_prediction():
    plan = build_plan(scenario())
    assert "not predictions" in plan.disclaimer
    assert "not licensed financial advice" in plan.disclaimer


def test_long_horizons_warn_about_assumption_sensitivity():
    plan = build_plan(scenario(timeline_months=360))
    assert any("compounding" in w for w in plan.warnings)


def test_a_usurious_rate_is_called_out():
    plan = build_plan(scenario(debts=[CARD]))
    assert any("24%" in w for w in plan.warnings)


# ── what-ifs ─────────────────────────────────────────────────────────────────


def test_catalog_lists_every_variant_with_a_question():
    entries = catalog()
    assert len(entries) >= 8
    assert all(e["question"].endswith("?") for e in entries)


def test_extra_monthly_leaves_the_user_better_off():
    r = run_variant(scenario(debts=[CARD]), "extra_monthly", {"amount": 5_000})
    assert r["delta"]["net_worth"] > 0


def test_job_loss_leaves_the_user_worse_off():
    r = run_variant(scenario(debts=[CARD]), "job_loss", {"months": 3, "drop_pct": 100})
    assert r["delta"]["net_worth"] < 0


def test_rate_shock_raises_interest_when_the_strategy_is_unchanged():
    r = run_variant(scenario(debts=[CARD]), "rate_shock", {"delta_pct": 2})
    assert r["delta"]["interest_paid"] > 0
    assert "note" not in r  # nothing crossed the hurdle


def test_a_rate_rise_that_crosses_the_hurdle_explains_itself():
    """8.6% -> 10.6% flips the home loan above the hurdle, so the plan starts
    prepaying it and total interest *falls*. That reads backwards unless the
    result says the strategy changed — so it must say so."""
    r = run_variant(scenario(debts=[HOME]), "rate_shock", {"delta_pct": 2})
    assert r["delta"]["interest_paid"] < 0
    assert "note" in r
    assert "crossed your 10% hurdle" in r["note"]
    assert "Home loan" in r["note"]


def test_avalanche_never_pays_more_interest_than_snowball():
    """The whole claim behind recommending avalanche — assert it, don't assume it."""
    s = scenario(
        debts=[
            Debt(name="Small cheap", balance=40_000, annual_rate_pct=11, min_payment=2_000),
            Debt(name="Big expensive", balance=300_000, annual_rate_pct=36, min_payment=9_000),
        ],
        strategy=Strategy.AVALANCHE,
    )
    avalanche = simulate(s, 12)
    snowball = simulate(s.model_copy(update={"strategy": Strategy.SNOWBALL}), 12)
    assert avalanche.total_interest_paid <= snowball.total_interest_paid


def test_a_variant_that_changes_nothing_says_so_plainly():
    """One debt above the hurdle means ordering cannot matter — don't print zeroes."""
    r = run_variant(scenario(debts=[CARD]), "snowball")
    assert "No measurable difference" in r["summary"]


def test_baseline_and_variant_come_from_the_same_code_path():
    r = run_variant(scenario(debts=[CARD]), "extra_monthly", {"amount": 0})
    assert r["baseline"]["final_net_worth"] == r["variant"]["final_net_worth"]


def test_unknown_variant_is_rejected():
    with pytest.raises(KeyError):
        run_variant(scenario(), "become_rich_immediately")


def test_compare_all_runs_every_variant():
    results = compare_all(scenario(debts=[CARD]))
    assert len(results) == len(catalog())
    assert all("summary" in r for r in results)


# ── presentation ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (0, "₹0"),
        (999, "₹999"),
        (1_000, "₹1,000"),
        (81_000, "₹81,000"),
        (11_15_936, "₹11,15,936"),
        (2_20_41_335, "₹2,20,41,335"),
        (-50_404, "-₹50,404"),
    ],
)
def test_amounts_use_indian_digit_grouping(amount, expected):
    """Western grouping reads as a typo to this app's audience."""
    assert inr(amount) == expected
