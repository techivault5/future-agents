"""Personalised savings levers, priced by what they compound into.

Generic tips ("cancel subscriptions", "cook at home") are worthless because
they do not know the reader. Every lever here is *detected* from the user's own
numbers, produces an amount derived from those numbers, and shows its
arithmetic so the figure can be checked rather than believed.

The second half is the point people miss: a saving is not worth its monthly
amount, it is worth what that amount becomes. ₹2,000/month sounds trivial and
is ₹4.44 lakh over ten years at 12%. Every lever carries that number, and the
list is ranked by it — not by how big the monthly figure looks.

(12% is the effective annual rate, so the monthly rate is 1.12^(1/12)-1 =
0.9488%. Quoting 12/12 = 1% is the usual error and overstates that figure by
about ₹16,000.)
"""

from __future__ import annotations

from collections.abc import Callable

from finance_advisor.planner.models import (
    RETURN_BANDS,
    SAFE_WITHDRAWAL_RATE,
    STAGE_ORDER,
    Effort,
    FIStage,
    FreedomSnapshot,
    SavingCategory,
    SavingLever,
    Scenario,
    TaxRegime,
)

# A savings-account rate against a liquid fund or sweep FD. The gap is small per
# month and enormous per decade, which is exactly why it goes unnoticed.
SAVINGS_ACCOUNT_RATE = 3.0
LIQUID_FUND_RATE = 6.5

# Regular mutual-fund plans pay the distributor out of your returns; direct
# plans of the same scheme do not. The gap is roughly this, every year, forever.
REGULAR_PLAN_DRAG_PCT = 1.0

# Average personal-loan APR — the realistic floor for consolidating card debt.
CONSOLIDATION_RATE_PCT = 11.4

# Marginal rate assumed when pricing a deduction. Deliberately not the top slab.
ASSUMED_MARGINAL_TAX_PCT = 30.0

# A discretionary audit reliably finds something, but how much is a guess — so
# it is small, explicitly low-confidence, and never leads the list.
DISCRETIONARY_AUDIT_PCT = 4.0
HIGH_FIXED_COST_RATIO = 0.6


def future_value(monthly: float, years: float, annual_return_pct: float) -> float:
    """What a monthly amount becomes if invested — the whole argument."""
    if monthly <= 0 or years <= 0:
        return 0.0
    rate = (1 + annual_return_pct / 100) ** (1 / 12) - 1
    months = years * 12
    if rate == 0:
        return monthly * months
    return monthly * (((1 + rate) ** months - 1) / rate)


# ── detectors ────────────────────────────────────────────────────────────────
# Each returns (monthly_saving, basis) or None when the lever does not apply.

Detector = Callable[[Scenario], "tuple[float, str] | None"]


def _card_interest(s: Scenario) -> tuple[float, str] | None:
    worst = [d for d in s.debts if d.annual_rate_pct >= 24]
    if not worst:
        return None
    monthly = sum(d.balance * d.annual_rate_pct / 100 / 12 for d in worst)
    names = ", ".join(d.name for d in worst)
    return monthly, (
        f"{names}: interest accruing right now, at the stated rates on the stated "
        f"balances. Clearing them stops this outflow permanently."
    )


def _consolidation(s: Scenario) -> tuple[float, str] | None:
    dear = [d for d in s.debts if d.annual_rate_pct > CONSOLIDATION_RATE_PCT + 2]
    if not dear:
        return None
    monthly = sum(d.balance * (d.annual_rate_pct - CONSOLIDATION_RATE_PCT) / 100 / 12 for d in dear)
    return monthly, (
        f"Rate difference between what you pay now and ~{CONSOLIDATION_RATE_PCT}% "
        f"(average personal-loan APR), on {len(dear)} balance(s). Refinancing does "
        "not reduce what you owe — only what it costs to owe it."
    )


def _idle_cash(s: Scenario) -> tuple[float, str] | None:
    excess = s.cash_savings - s.emergency_target
    if excess <= 50_000:
        return None
    monthly = excess * (LIQUID_FUND_RATE - SAVINGS_ACCOUNT_RATE) / 100 / 12
    return monthly, (
        f"{excess:,.0f} sits above your emergency target. A savings account pays "
        f"~{SAVINGS_ACCOUNT_RATE}%; a liquid fund or sweep FD pays ~{LIQUID_FUND_RATE}% "
        "at similar access. Same money, same availability, different rate."
    )


def _direct_plans(s: Scenario) -> tuple[float, str] | None:
    if s.existing_investments < 100_000:
        return None
    monthly = s.existing_investments * REGULAR_PLAN_DRAG_PCT / 100 / 12
    return monthly, (
        f"~{REGULAR_PLAN_DRAG_PCT}% a year on {s.existing_investments:,.0f} — the "
        "commission built into regular plans. If your holdings are already direct, "
        "this lever is already taken; if you invest through a bank or agent, it "
        "almost certainly is not."
    )


def _tax_80c(s: Scenario) -> tuple[float, str] | None:
    if s.tax_regime is not TaxRegime.OLD:
        return None
    from finance_advisor.planner.models import NPS_80CCD1B_CAP, SECTION_80C_CAP

    unused = max(SECTION_80C_CAP - s.existing_80c, 0) + max(NPS_80CCD1B_CAP - s.nps_contribution, 0)
    if unused <= 0:
        return None
    monthly = unused * ASSUMED_MARGINAL_TAX_PCT / 100 / 12
    return monthly, (
        f"{unused:,.0f} of unused 80C + 80CCD(1B) headroom at an assumed "
        f"{ASSUMED_MARGINAL_TAX_PCT}% marginal rate. This is tax you are paying "
        "that the law does not require — and ELSS keeps the money invested."
    )


def _fixed_costs(s: Scenario) -> tuple[float, str] | None:
    ratio = s.monthly_expenses / s.monthly_income if s.monthly_income else 0
    if ratio < HIGH_FIXED_COST_RATIO:
        return None
    target = s.monthly_income * HIGH_FIXED_COST_RATIO
    monthly = (s.monthly_expenses - target) * 0.5  # half the excess is a fair first pass
    return monthly, (
        f"Your living costs are {ratio * 100:.0f}% of take-home. Above ~"
        f"{HIGH_FIXED_COST_RATIO * 100:.0f}% the binding constraint is usually one or "
        "two large commitments — rent, car, school fees — not daily spending. This "
        "assumes you close half the gap; the lever is real but the amount is yours "
        "to set."
    )


def _discretionary(s: Scenario) -> tuple[float, str] | None:
    monthly = s.monthly_expenses * DISCRETIONARY_AUDIT_PCT / 100
    if monthly < 500:
        return None
    return monthly, (
        f"{DISCRETIONARY_AUDIT_PCT}% of stated expenses — a placeholder for the "
        "subscriptions, auto-renewals and duplicate services an audit typically "
        "finds. Low confidence by design: it is a prompt to look, not a measurement."
    )


def _step_up(s: Scenario) -> tuple[float, str] | None:
    if s.annual_increment_pct <= 0 or s.monthly_surplus <= 0:
        return None
    monthly = s.monthly_income * s.annual_increment_pct / 100
    return monthly, (
        f"Your next {s.annual_increment_pct:.0f}% increment is worth {monthly:,.0f}/month. "
        "Directing it to the SIP before it reaches your spending costs nothing in "
        "felt terms — you never had it. Doing this once a year is the single "
        "highest-leverage habit available to a salaried earner."
    )


LEVERS: list[tuple[str, SavingCategory, str, str, str, Effort, float, Detector]] = [
    (
        "card_interest",
        SavingCategory.LEAKS,
        "Stop the credit-card interest",
        "This is money leaving every month and buying nothing. No investment "
        "returns what a 40% card costs you, so nothing outranks it.",
        "Aim every spare rupee at the highest-rate balance while paying minimums "
        "on the rest. Stop using the card until it is cleared — a card you are "
        "still spending on cannot be paid off.",
        Effort.MEDIUM,
        0.95,
        _card_interest,
    ),
    (
        "consolidate",
        SavingCategory.LEAKS,
        "Refinance the expensive debt",
        "The same debt at a lower rate costs less to carry. This is arithmetic, "
        "not discipline — it does not require you to change any behaviour.",
        "Price a personal loan or a 0% balance-transfer card against your current "
        "rates. Check the processing fee and the post-promo rate before switching, "
        "and never extend the tenure just to shrink the EMI.",
        Effort.MEDIUM,
        0.75,
        _consolidation,
    ),
    (
        "idle_cash",
        SavingCategory.RETURNS,
        "Move idle cash out of the savings account",
        "Cash beyond your emergency fund is not safe, it is idle. Inflation is "
        "taking a real cut from it every year it sits at 3%.",
        "Keep the emergency fund liquid, then move the excess to a liquid fund or "
        "sweep FD. Both are same-day or next-day access — you lose no real "
        "flexibility, only the low rate.",
        Effort.EASY,
        0.9,
        _idle_cash,
    ),
    (
        "direct_plans",
        SavingCategory.RETURNS,
        "Switch regular mutual-fund plans to direct",
        "Identical scheme, identical manager, identical portfolio — the direct "
        "plan simply does not pay a distributor out of your returns. Over decades "
        "this single change moves lakhs.",
        "Check whether your folios say Regular or Direct. Switching is a redemption "
        "and repurchase, so check exit load and capital-gains impact first; for "
        "future SIPs, just start the direct plan instead.",
        Effort.EASY,
        0.6,
        _direct_plans,
    ),
    (
        "tax_headroom",
        SavingCategory.TAX,
        "Use the deduction headroom you already qualify for",
        "On the old regime these deductions are a guaranteed return at your "
        "marginal rate. Unused headroom is tax paid voluntarily.",
        "Fill 80C with ELSS if you want the money to stay in equity, or PPF/EPF if "
        "you want certainty. NPS adds ₹50,000 under 80CCD(1B) but locks to 60. "
        "Also compare the new regime — if your deductions are thin, it may be cheaper.",
        Effort.EASY,
        0.7,
        _tax_80c,
    ),
    (
        "fixed_costs",
        SavingCategory.FIXED,
        "Renegotiate the two or three biggest commitments",
        "Large recurring costs dominate the arithmetic. One rent or insurance "
        "decision outweighs a year of small economies, and it only has to be made "
        "once.",
        "List every outgoing above 5% of income and question each one annually. "
        "Rent, vehicle, insurance premiums and telecom are where the money is — "
        "and all four are negotiable or switchable.",
        Effort.HARD,
        0.5,
        _fixed_costs,
    ),
    (
        "discretionary",
        SavingCategory.LEAKS,
        "Audit the recurring charges",
        "Subscriptions are designed to be forgotten. The saving is modest but the "
        "effort is one evening and it never has to be repeated.",
        "Read the last three months of statements line by line and cancel anything "
        "you did not deliberately choose this quarter. Turn off auto-renewal on "
        "what survives so the decision comes back to you.",
        Effort.EASY,
        0.35,
        _discretionary,
    ),
    (
        "step_up_sip",
        SavingCategory.BEHAVIOUR,
        "Direct every increment to the SIP before you feel it",
        "Lifestyle creep is what converts a rising salary into an unchanged "
        "savings rate. Money you never adjusted to is the cheapest money to save.",
        "The week your increment lands, raise the SIP by the same amount. Set a "
        "calendar reminder for appraisal month so it is not left to memory.",
        Effort.EASY,
        0.8,
        _step_up,
    ),
]


def personalise(scenario: Scenario, annual_return_pct: float | None = None) -> list[SavingLever]:
    """Levers that apply to *this* scenario, ranked by what they compound into."""
    rate = annual_return_pct or RETURN_BANDS["base"]
    years = scenario.timeline_months / 12
    out: list[SavingLever] = []

    for lever_id, category, title, why, action, effort, confidence, detect in LEVERS:
        found = detect(scenario)
        if not found:
            continue
        monthly, basis = found
        if monthly < 100:
            continue
        out.append(
            SavingLever(
                id=lever_id,
                category=category,
                title=title,
                why=why,
                action=action,
                monthly_saving=round(monthly, 2),
                effort=effort,
                confidence=confidence,
                compounded_value=round(future_value(monthly, years, rate), 2),
                basis=basis,
            )
        )
    # Ranked by what it becomes, not by how big the monthly figure looks — those
    # orderings differ, and the compounded one is the one that matters.
    ranked = sorted(out, key=lambda x: -x.compounded_value)
    _mark_alternatives(ranked)
    return ranked


# Levers that target the same rupees. Clearing a card and refinancing it are
# alternatives, not additions — summing both would invent money.
OVERLAPS = {"consolidate": "card_interest"}


def _mark_alternatives(levers: list[SavingLever]) -> None:
    """Flag any lever whose money is already claimed by a higher-ranked one."""
    present = {x.id: x for x in levers}
    for lever in levers:
        dominant = OVERLAPS.get(lever.id)
        if dominant and dominant in present:
            lever.alternative_to = present[dominant].title


def countable(levers: list[SavingLever]) -> list[SavingLever]:
    """The subset safe to add up — alternatives excluded."""
    return [x for x in levers if x.alternative_to is None]


def _stage(scenario: Scenario, savings_rate: float) -> tuple[FIStage, str, str]:
    """Which rung, and the one thing that matters on it."""
    starter = scenario.monthly_burn
    expensive = [d for d in scenario.debts if d.annual_rate_pct >= scenario.hurdle_rate_pct]
    fi_number = fi_target(scenario)
    covered = scenario.term_cover > 0 or scenario.dependants == 0

    if scenario.monthly_surplus <= 0:
        return (
            FIStage.UNDERWATER,
            "Underwater",
            "Close the monthly gap. Nothing else is available until income exceeds "
            "outgoings — this is the only rung where the answer is not about money "
            "management but about the size of the numbers themselves.",
        )
    if scenario.cash_savings < starter:
        return (
            FIStage.BUFFERED,
            "Building the buffer",
            f"Get one month of costs ({starter:,.0f}) into reach. Until then every "
            "surprise becomes debt, and you restart from behind.",
        )
    if expensive:
        return (
            FIStage.SOLVENT,
            "Clearing expensive debt",
            "Kill the balances above your hurdle rate. You are currently paying a "
            "guaranteed negative return; no investment competes with removing it.",
        )
    if scenario.cash_savings < scenario.emergency_target or not covered:
        return (
            FIStage.SECURE,
            "Getting secure",
            "Full emergency fund and adequate cover. This rung is what stops a bad "
            "month from unwinding years of progress — it is insurance in both the "
            "literal and the general sense.",
        )
    if scenario.existing_investments >= fi_number:
        return (
            FIStage.FREE,
            "Financially free",
            "Your invested assets can fund your spending at a 4% withdrawal rate. "
            "Work is now a choice. Focus shifts from accumulation to sequence risk "
            "and tax on withdrawals.",
        )
    coast = coast_fi_target(scenario)
    if coast is not None and scenario.existing_investments >= coast:
        return (
            FIStage.COAST,
            "Coast FI",
            "What you have already invested will compound to your FI number by "
            "retirement with no further contributions. You still need income for "
            "today's costs, but the retirement problem is solved — which buys you "
            "the option of lower-paid work you prefer.",
        )
    return (
        FIStage.INVESTING,
        "Compounding",
        f"You are saving {savings_rate:.0f}% of income with the foundations in "
        "place. The lever now is the savings rate itself — it decides the timeline "
        "far more than the return does.",
    )


def fi_target(scenario: Scenario) -> float:
    """Corpus that funds today's spending indefinitely, at the 4% convention."""
    return scenario.monthly_expenses * 12 / SAFE_WITHDRAWAL_RATE


def coast_fi_target(scenario: Scenario) -> float | None:
    """Invested today that compounds to the FI number by retirement, unaided."""
    years = scenario.years_to_retirement
    if not years:
        return None
    growth = (1 + RETURN_BANDS["base"] / 100) ** years
    return fi_target(scenario) / growth


def years_to_fi(scenario: Scenario, annual_return_pct: float | None = None) -> float | None:
    """How long until invested assets cover spending, at the current savings rate.

    The classic result: the savings *rate* dominates. Doubling income while
    doubling spending moves this number not at all.
    """
    rate_pct = annual_return_pct or RETURN_BANDS["base"]
    monthly_saving = scenario.monthly_surplus
    if monthly_saving <= 0:
        return None
    target = fi_target(scenario)
    rate = (1 + rate_pct / 100) ** (1 / 12) - 1
    balance = scenario.existing_investments
    for month in range(1, 100 * 12 + 1):
        balance = balance * (1 + rate) + monthly_saving
        if balance >= target:
            return round(month / 12, 1)
    return None


def freedom_snapshot(scenario: Scenario) -> FreedomSnapshot:
    """Savings rate, FI number, the rung, and the one thing that matters next."""
    rate = (
        scenario.monthly_surplus / scenario.monthly_income * 100 if scenario.monthly_income else 0
    )
    target = fi_target(scenario)
    stage, label, action = _stage(scenario, rate)
    progress = scenario.existing_investments / target * 100 if target else 0
    coast = coast_fi_target(scenario)

    if rate <= 0:
        note = "A negative savings rate has no timeline — the gap has to close first."
    elif rate < 15:
        note = (
            f"At {rate:.0f}% the timeline is measured in decades. Savings rate moves "
            "this far more than investment return does: going from 15% to 30% roughly "
            "halves the wait, while an extra 2% of return barely dents it."
        )
    elif rate < 40:
        note = (
            f"{rate:.0f}% is a strong rate — the difference between comfortable and "
            "free is now mostly time, not decisions. Protect it from lifestyle creep "
            "as income rises."
        )
    else:
        note = (
            f"{rate:.0f}% is an aggressive rate. Check it is sustainable: a plan you "
            "abandon in year three loses to a smaller one you keep for twenty."
        )

    return FreedomSnapshot(
        savings_rate_pct=round(rate, 1),
        fi_number=round(target, 2),
        invested_now=round(scenario.existing_investments, 2),
        progress_pct=round(min(progress, 100), 1),
        years_to_fi=years_to_fi(scenario),
        coast_fi_number=round(coast, 2) if coast else None,
        stage=stage,
        stage_label=label,
        next_action=action,
        note=note,
    )


def stage_ladder() -> list[dict]:
    """The whole ladder, so a UI can show where the user sits within it."""
    return [{"stage": s.value, "index": i} for i, s in enumerate(STAGE_ORDER)]
