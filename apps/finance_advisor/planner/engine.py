"""Month-by-month simulation of a scenario, and the plan that falls out of it.

No forecasting model and no LLM: every number is arithmetic on the user's own
inputs under assumptions stated on the result. That is deliberate — a plan you
can recompute by hand is one you can argue with.

Ordering follows the sequence that survives contact with reality: protection
first (an uninsured hospital bill ends every other plan), then a starter cash
buffer, then debt costing more than markets plausibly return, then a full
emergency fund, then tax-efficient investing, then everything else.
"""

from __future__ import annotations

from finance_advisor.planner.models import (
    NPS_80CCD1B_CAP,
    RETURN_BANDS,
    SECTION_80C_CAP,
    TERM_COVER_INCOME_MULTIPLE,
    Debt,
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
from finance_advisor.planner.savings import countable, freedom_snapshot, personalise

STARTER_BUFFER_MONTHS = 1
# A family floater below this is nominal cover in Indian metros, where a single
# cardiac or oncology admission clears several lakh.
HEALTH_COVER_BASE = 500_000
HEALTH_COVER_PER_DEPENDANT = 250_000


def inr(amount: float) -> str:
    """₹ with Indian digit grouping — 12,34,567, not 1,234,567.

    Python's `,` format gives Western grouping, which reads as a typo to the
    audience this app is for, and the browser already renders `en-IN`.
    """
    negative = amount < 0
    digits = f"{abs(amount):,.0f}".replace(",", "")
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        pairs = []
        while len(head) > 2:
            pairs.insert(0, head[-2:])
            head = head[:-2]
        if head:
            pairs.insert(0, head)
        digits = ",".join([*pairs, tail])
    return ("-₹" if negative else "₹") + digits


def _monthly_growth(annual_pct: float) -> float:
    return (1 + annual_pct / 100) ** (1 / 12) - 1


def _order_debts(debts: list[Debt], strategy: Strategy) -> list[Debt]:
    if strategy is Strategy.SNOWBALL:
        return sorted(debts, key=lambda d: d.balance)
    return sorted(debts, key=lambda d: -d.annual_rate_pct)


def _months(value: int | None) -> str:
    if value is None:
        return "not within your timeline"
    if value <= 0:
        return "already there"
    years, rem = divmod(int(value), 12)
    if not years:
        return f"{rem} month{'s' if rem != 1 else ''}"
    if not rem:
        return f"{years} year{'s' if years != 1 else ''}"
    return f"{years}y {rem}m"


def simulate(
    scenario: Scenario,
    annual_return_pct: float,
    band: str = "base",
    extra_monthly: float = 0.0,
    lump_sum: float = 0.0,
    income_drop_pct: float = 0.0,
    income_drop_months: int = 0,
) -> Projection:
    """Run the scenario forward one month at a time.

    Income rises with the annual increment, expenses rise with inflation, and
    the bonus lands once a year — all three change the answer materially over a
    long horizon, so none of them is assumed away.

    The overrides exist so what-if variants share exactly this code path: a
    comparison is only honest if both sides were computed the same way.
    """
    debts = [d.model_copy() for d in scenario.debts]
    cash = scenario.cash_savings + lump_sum
    investments = scenario.existing_investments
    growth = _monthly_growth(annual_return_pct)
    income = scenario.monthly_income
    expenses = scenario.monthly_expenses
    starter = scenario.monthly_burn * STARTER_BUFFER_MONTHS

    interest_paid = 0.0
    debt_free_month: int | None = 0 if not debts else None
    net_worth_by_year: list[float] = []

    for month in range(1, scenario.timeline_months + 1):
        if month > 1 and month % 12 == 1:  # anniversary: raise and repricing
            income *= 1 + scenario.annual_increment_pct / 100
            expenses *= 1 + scenario.inflation_pct / 100

        this_month = income
        if income_drop_months and month <= income_drop_months:
            this_month *= 1 - income_drop_pct / 100
        if month % 12 == 0:
            this_month += scenario.annual_bonus

        available = this_month - expenses + extra_monthly

        for debt in debts:
            if debt.balance <= 0:
                continue
            accrued = debt.balance * debt.monthly_rate
            debt.balance += accrued
            interest_paid += accrued
            payment = min(debt.min_payment, debt.balance, max(available, 0.0))
            debt.balance -= payment
            available -= payment

        # A shortfall is real: it comes out of cash, and if cash runs out the
        # simulation records the hole rather than quietly borrowing more.
        if available < 0:
            cash += available
            available = 0.0

        surplus = max(available, 0.0)
        live = [d for d in debts if d.balance > 0.01]
        expensive = [d for d in live if d.annual_rate_pct >= scenario.hurdle_rate_pct]

        if cash < starter:
            cash += surplus
        elif expensive:
            target = _order_debts(expensive, scenario.strategy)[0]
            paid = min(surplus, target.balance)
            target.balance -= paid
            cash += surplus - paid
        elif cash < scenario.emergency_target:
            cash += surplus
        else:
            investments += surplus

        investments *= 1 + growth

        if debt_free_month is None and all(d.balance <= 0.01 for d in debts):
            debt_free_month = month
        if month % 12 == 0:
            net_worth_by_year.append(
                round(cash + investments - sum(max(d.balance, 0) for d in debts), 2)
            )

    remaining = sum(max(d.balance, 0) for d in debts)
    return Projection(
        band=band,
        annual_return_pct=annual_return_pct,
        months=scenario.timeline_months,
        debt_free_month=debt_free_month,
        final_investments=round(investments, 2),
        final_cash=round(cash, 2),
        final_net_worth=round(cash + investments - remaining, 2),
        total_interest_paid=round(interest_paid, 2),
        net_worth_by_year=net_worth_by_year,
    )


def protection_gap(scenario: Scenario) -> ProtectionGap:
    """Cover needed against cover held.

    Term need is the standard construction: replace income, clear the debts,
    credit what is already invested. Health is a floor by household size, not a
    calculation — the tail risk is what matters and it is not smooth.
    """
    annual_income = scenario.monthly_income * 12
    needed = (
        annual_income * TERM_COVER_INCOME_MULTIPLE
        + scenario.total_debt
        - scenario.existing_investments
    )
    needed = max(needed, 0.0)
    term_gap = max(needed - scenario.term_cover, 0.0)

    health_needed = HEALTH_COVER_BASE + HEALTH_COVER_PER_DEPENDANT * scenario.dependants
    health_gap = max(health_needed - scenario.health_cover, 0.0)

    if scenario.dependants == 0 and term_gap > 0:
        note = (
            "With no dependants, term cover matters mainly for your debts — "
            f"{inr(scenario.total_debt)} would otherwise fall to your estate or "
            "co-borrowers. Health cover still matters as much as for anyone."
        )
    elif term_gap or health_gap:
        note = (
            "Cover this gap before optimising anything below it. Term and health "
            "premiums are small relative to income, and one uninsured event "
            "undoes years of the plan — this is the cheapest risk you can retire."
        )
    else:
        note = "Cover looks adequate against both tests. Revisit when income or dependants change."

    return ProtectionGap(
        term_cover_needed=round(needed, 2),
        term_cover_gap=round(term_gap, 2),
        health_cover_suggested=round(health_needed, 2),
        health_cover_gap=round(health_gap, 2),
        note=note,
    )


def _goal_outlooks(scenario: Scenario, annual_return_pct: float) -> list[GoalOutlook]:
    """What each goal costs when due, and the monthly SIP that gets there."""
    rate = _monthly_growth(annual_return_pct)
    surplus = max(scenario.monthly_surplus, 0.0)
    out: list[GoalOutlook] = []

    for goal in sorted(scenario.all_goals(), key=lambda g: (g.priority, g.years)):
        months = max(int(round(goal.years * 12)), 1)
        due = goal.future_amount(scenario.inflation_pct)
        # Future value of an ordinary annuity, solved for the payment.
        needed = due * rate / ((1 + rate) ** months - 1) if rate else due / months
        share = surplus / max(len(scenario.all_goals()), 1)
        on_track = needed <= share
        note = f"{inr(needed)}/month at {annual_return_pct:.0f}% gets there. " + (
            "That fits inside your surplus."
            if on_track
            else f"That exceeds the {inr(share)}/month this goal would get if you "
            "split the surplus evenly — extend the horizon, raise income, or "
            "lower the target."
        )
        out.append(
            GoalOutlook(
                name=goal.name,
                amount_today=round(goal.amount_today, 2),
                amount_at_due=round(due, 2),
                due_month=months,
                monthly_needed=round(needed, 2),
                on_track=on_track,
                note=note,
            )
        )
    return out


def _tax_headroom(scenario: Scenario) -> tuple[float, float]:
    if scenario.tax_regime is not TaxRegime.OLD:
        return 0.0, 0.0
    return (
        max(SECTION_80C_CAP - scenario.existing_80c, 0.0),
        max(NPS_80CCD1B_CAP - scenario.nps_contribution, 0.0),
    )


def _steps(scenario: Scenario, base: Projection, gap: ProtectionGap) -> list[Step]:
    """The ordered actions. Only steps that apply to this scenario appear."""
    steps: list[Step] = []
    surplus = scenario.monthly_surplus
    starter = scenario.monthly_burn * STARTER_BUFFER_MONTHS
    expensive = [d for d in scenario.debts if d.annual_rate_pct >= scenario.hurdle_rate_pct]
    cheap = [d for d in scenario.debts if d.annual_rate_pct < scenario.hurdle_rate_pct]
    c80, cnps = _tax_headroom(scenario)

    def add(title: str, why: str, action: str, amount: float | None = None) -> None:
        steps.append(
            Step(order=len(steps) + 1, title=title, why=why, action=action, amount_monthly=amount)
        )

    if surplus <= 0:
        add(
            "Close the monthly gap before anything else",
            "You are spending at least as much as you earn, so nothing below can "
            "start. This is the only step that matters until it is fixed.",
            f"You need at least {inr(abs(surplus))}/month to break even. Look at the "
            "largest committed outgoings first — rent, EMIs, subscriptions — because "
            "small discretionary cuts rarely close a structural gap.",
        )
        return steps

    if gap.term_cover_gap or gap.health_cover_gap:
        parts = []
        if gap.term_cover_gap:
            parts.append(f"term cover short by {inr(gap.term_cover_gap)}")
        if gap.health_cover_gap:
            parts.append(f"health cover short by {inr(gap.health_cover_gap)}")
        add(
            "Close the insurance gap first",
            "Every step below assumes nothing catastrophic happens. Insurance is "
            "what makes that assumption safe, and it is the cheapest risk you can "
            "retire — premiums are a rounding error against the loss they cover.",
            f"You are {' and '.join(parts)}. Buy plain term cover (not ULIP, not "
            "endowment) and a family floater. Both are annual decisions, not "
            "investments — do not let anyone sell you a policy that mixes the two.",
        )

    if scenario.cash_savings < starter:
        add(
            "Build a one-month starter buffer",
            "Without a buffer the next unexpected bill goes on a card at 20%+, "
            "which undoes months of repayment. One month of costs stops that loop.",
            f"Hold {inr(starter)} in a savings account you can reach the same day — "
            f"about {_months(int(starter / surplus) + 1)} at your current surplus.",
            surplus,
        )

    if expensive:
        order = _order_debts(expensive, scenario.strategy)
        method = (
            "smallest balance first, because visible wins keep people going"
            if scenario.strategy is Strategy.SNOWBALL
            else "highest rate first, which pays the least total interest"
        )
        add(
            f"Clear debt above {scenario.hurdle_rate_pct:.0f}%",
            f"Paying {order[0].annual_rate_pct:.1f}% debt is a guaranteed, tax-free "
            "return at that rate. Nothing you can invest in offers a guaranteed "
            "return anywhere near it, so this comes before investing.",
            f"Keep every minimum paid, then aim the whole surplus at one debt at a "
            f"time ({method}): {' → '.join(d.name for d in order)}. "
            + (
                f"Projected debt-free in {_months(base.debt_free_month)}."
                if base.debt_free_month is not None
                else "Some of this debt outlives your chosen horizon — extend the "
                "timeline to see when it clears."
            ),
            surplus,
        )

    if scenario.emergency_fund_months:
        why_months = (
            "Self-employed income arrives in gaps you do not control, so the "
            "buffer has to cover a longer one."
            if scenario.employment.value != "salaried"
            else "Enough to absorb a notice period and a job search without "
            "selling anything at a bad moment."
        )
        add(
            f"Top the emergency fund to {scenario.emergency_fund_months} months",
            why_months,
            f"Target {inr(scenario.emergency_target)} — {scenario.emergency_fund_months} "
            "months of expenses plus debt service — in a liquid fund or sweep account, "
            "not in equity.",
            surplus,
        )

    if c80 or cnps:
        bits = []
        if c80:
            bits.append(f"{inr(c80)} of 80C headroom")
        if cnps:
            bits.append(f"{inr(cnps)} of NPS 80CCD(1B)")
        add(
            "Use the deduction headroom you are paying for",
            "You are on the old regime, where these deductions are the return. "
            "Unused headroom is tax paid for nothing.",
            f"You have {' and '.join(bits)} left this year. ELSS covers 80C while "
            "staying invested in equity; NPS is worth it only if you accept the "
            "lock-in to 60. Check the new regime too — if your deductions are small, "
            "it may simply be cheaper.",
        )

    add(
        "Automate investing with what remains",
        "Automation is the whole mechanism: it moves the decision out of the "
        "moment, so investing does not have to win an argument with an impulse.",
        f"Start a SIP of about {inr(surplus)}/month dated just after payday, and "
        "raise it with every increment before the raise reaches your spending.",
        surplus,
    )

    if cheap:
        names = ", ".join(f"{d.name} at {d.annual_rate_pct:.1f}%" for d in cheap)
        add(
            "Leave the cheap debt running — but check the comparison",
            f"{names} sits below your {scenario.hurdle_rate_pct:.0f}% hurdle, so "
            "prepaying competes with investing rather than obviously beating it. "
            "The honest answer depends on returns nobody knows in advance.",
            "Run the 'prepay instead of invest' what-if. If the two are close, take "
            "the certain one — a guaranteed rate has no variance, and being "
            "debt-free early is worth something the arithmetic does not show.",
        )
    return steps


def _milestones(scenario: Scenario, base: Projection) -> list[Milestone]:
    surplus = max(scenario.monthly_surplus, 0.01)
    starter = scenario.monthly_burn * STARTER_BUFFER_MONTHS
    to_starter = max(starter - scenario.cash_savings, 0)
    reached_fund = base.final_cash >= scenario.emergency_target

    out = [
        Milestone(
            name="Starter buffer",
            month=0 if to_starter <= 0 else int(to_starter / surplus) + 1,
            detail=f"{inr(starter)} — one month of costs held within reach",
        ),
        Milestone(
            name="Debt-free",
            month=base.debt_free_month,
            detail="Every balance cleared, including any below the hurdle rate",
        ),
        Milestone(
            name=f"{scenario.emergency_fund_months}-month emergency fund",
            month=base.debt_free_month if reached_fund else None,
            detail=f"{inr(scenario.emergency_target)} held liquid"
            + ("" if reached_fund else " — not reached inside this horizon"),
        ),
    ]
    if scenario.years_to_retirement:
        out.append(
            Milestone(
                name="Retirement",
                month=int(scenario.years_to_retirement * 12),
                detail=f"Age {scenario.retirement_age}, {scenario.years_to_retirement:.0f} "
                "years out — see the retirement corpus goal for what it needs",
            )
        )
    return out


def build_plan(scenario: Scenario) -> Plan:
    """Simulate across return bands and turn the result into ordered steps."""
    projections = [
        simulate(scenario, rate, band=band) for band, rate in sorted(RETURN_BANDS.items())
    ]
    base = next(p for p in projections if p.band == "base")
    gap = protection_gap(scenario)
    steps = _steps(scenario, base, gap)
    goals = _goal_outlooks(scenario, RETURN_BANDS["base"])
    levers = personalise(scenario)
    freedom = freedom_snapshot(scenario)
    surplus = scenario.monthly_surplus
    feasible = surplus > 0

    warnings: list[str] = []
    if not feasible:
        warnings.append(
            f"Monthly outgoings exceed income by {inr(abs(surplus))}. Every "
            "projection below assumes that gap is closed first."
        )
    if base.final_cash < 0:
        warnings.append(
            "Cash goes negative during the simulation — minimum payments alone do "
            "not fit inside income. Treat this as a diagnosis, not a plan."
        )
    if any(d.annual_rate_pct >= 24 for d in scenario.debts):
        warnings.append(
            "A debt at 24%+ compounds faster than almost anything can outrun. "
            "Price a consolidation loan or balance transfer before anything else."
        )
    if gap.term_cover_gap and scenario.dependants:
        warnings.append(
            f"{scenario.dependants} dependant(s) and a {inr(gap.term_cover_gap)} term "
            "cover gap. That is the largest single risk in this plan."
        )
    behind = [g for g in goals if not g.on_track]
    if behind:
        warnings.append(
            f"{len(behind)} goal(s) need more than an even split of your surplus: "
            + ", ".join(g.name for g in behind)
            + ". Goals compete — funding one fully usually means delaying another."
        )
    if scenario.timeline_months >= 240:
        warnings.append(
            "Beyond about 20 years, compounding makes small assumption changes "
            "enormous. Read the band spread, not the middle number."
        )

    spread = max(p.final_net_worth for p in projections) - min(
        p.final_net_worth for p in projections
    )
    if feasible:
        horizon = _months(scenario.timeline_months)
        debt_phrase = (
            f"debt-free in {_months(base.debt_free_month)}"
            if base.debt_free_month is not None
            else f"still carrying debt at the {horizon} mark — the long loan outlives "
            "this horizon, which is normal and not a failure"
        )
        headline = (
            f"With {inr(surplus)}/month spare: {debt_phrase}, and a projected net "
            f"worth of {inr(base.final_net_worth)} after {horizon}. The band spans "
            f"{inr(spread)} — that gap is the honest measure of how little any "
            "single number here is worth."
        )
    else:
        headline = (
            f"Income does not cover outgoings — the gap is {inr(abs(surplus))}/month. "
            "Nothing else in this plan works until that closes."
        )

    return Plan(
        scenario=scenario,
        feasible=feasible,
        headline=headline,
        steps=steps,
        milestones=_milestones(scenario, base),
        projections=projections,
        goals=goals,
        protection=gap,
        savings=levers,
        savings_total_monthly=round(sum(x.monthly_saving for x in countable(levers)), 2),
        savings_total_compounded=round(sum(x.compounded_value for x in countable(levers)), 2),
        freedom=freedom,
        warnings=warnings,
    )


__all__ = ["build_plan", "protection_gap", "simulate", "Goal"]
