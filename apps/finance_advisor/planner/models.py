"""What a user describes, and what the planner gives back.

Every field here changes an output. A planner that collects a number and then
ignores it is worse than one that never asked — it implies a precision the
answer does not have. If you add a field, make the engine use it.

Plain Pydantic models, so the same shapes serve the HTTP API, the agent tool and
the tests with no translation layer.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator

# Above this rate, clearing debt beats any realistic after-tax market return, so
# the plan pays it before it invests. Below it the comparison is genuinely open,
# and the planner shows both sides instead of asserting one.
DEFAULT_HURDLE_RATE_PCT = 10.0

# Return bands used to project a range. The point of carrying three is that a
# single number reads as a promise.
RETURN_BANDS = {"pessimistic": 8.0, "base": 12.0, "optimistic": 15.0}

DEFAULT_INFLATION_PCT = 6.0  # long-run Indian CPI is nearer 5-6% than the 2% of Western planners
SAFE_WITHDRAWAL_RATE = 0.04  # the 4% rule — a planning convention, not a law
SECTION_80C_CAP = 150_000
NPS_80CCD1B_CAP = 50_000
TERM_COVER_INCOME_MULTIPLE = 10  # cover ≈ 10x annual income, plus debts, less assets
MAX_HORIZON_MONTHS = 720


class Strategy(str, Enum):
    AVALANCHE = "avalanche"  # highest rate first — least interest paid
    SNOWBALL = "snowball"  # smallest balance first — fastest visible wins


class Employment(str, Enum):
    SALARIED = "salaried"
    SELF_EMPLOYED = "self_employed"
    BUSINESS = "business"


class TaxRegime(str, Enum):
    NEW = "new"  # no 80C; lower slabs
    OLD = "old"  # 80C/80CCD deductions available


# Income volatility is the whole argument for a bigger buffer: a salaried gap is
# usually one notice period, a freelance gap is however long the next project
# takes.
EMERGENCY_MONTHS_BY_EMPLOYMENT = {
    Employment.SALARIED: 6,
    Employment.SELF_EMPLOYED: 12,
    Employment.BUSINESS: 12,
}


class Debt(BaseModel):
    name: str
    balance: float = Field(gt=0)
    annual_rate_pct: float = Field(ge=0, le=100)
    min_payment: float = Field(ge=0, description="EMI or minimum due each month")

    @property
    def monthly_rate(self) -> float:
        return self.annual_rate_pct / 100 / 12


class Goal(BaseModel):
    """A target in *today's* rupees. The engine inflates it to its due date."""

    name: str
    amount_today: float = Field(gt=0)
    years: float = Field(gt=0, le=60)
    priority: int = Field(default=2, ge=1, le=3, description="1 = must fund, 3 = nice to have")

    def future_amount(self, inflation_pct: float) -> float:
        """What this costs when it actually falls due."""
        return self.amount_today * (1 + inflation_pct / 100) ** self.years


class Scenario(BaseModel):
    """The user's situation, in the fewest numbers that make a plan possible."""

    # ── cash flow ────────────────────────────────────────────────────────────
    monthly_income: float = Field(gt=0, description="Take-home, after tax")
    monthly_expenses: float = Field(ge=0, description="Living costs, excluding debt payments")
    annual_bonus: float = Field(default=0, ge=0, description="Variable pay, credited yearly")
    annual_increment_pct: float = Field(default=5.0, ge=0, le=100)

    # ── balance sheet ────────────────────────────────────────────────────────
    cash_savings: float = Field(default=0, ge=0)
    existing_investments: float = Field(default=0, ge=0)
    debts: list[Debt] = Field(default_factory=list)

    # ── who this is for ──────────────────────────────────────────────────────
    age: int | None = Field(default=None, ge=15, le=100)
    retirement_age: int = Field(default=60, ge=35, le=85)
    dependants: int = Field(default=0, ge=0, le=15)
    employment: Employment = Employment.SALARIED

    # ── protection (India's most common gap) ─────────────────────────────────
    term_cover: float = Field(default=0, ge=0, description="Existing life cover, sum assured")
    health_cover: float = Field(
        default=0, ge=0, description="Existing health cover, family floater"
    )

    # ── tax ──────────────────────────────────────────────────────────────────
    tax_regime: TaxRegime = TaxRegime.NEW
    existing_80c: float = Field(default=0, ge=0, description="80C already used this year")
    nps_contribution: float = Field(default=0, ge=0, description="80CCD(1B) used this year")

    # ── planning choices ─────────────────────────────────────────────────────
    timeline_months: int = Field(default=120, gt=0, le=MAX_HORIZON_MONTHS)
    emergency_fund_months: int | None = Field(
        default=None, ge=0, le=24, description="Defaults from employment type if unset"
    )
    strategy: Strategy = Strategy.AVALANCHE
    hurdle_rate_pct: float = Field(default=DEFAULT_HURDLE_RATE_PCT, ge=0, le=100)
    inflation_pct: float = Field(default=DEFAULT_INFLATION_PCT, ge=0, le=50)
    goals: list[Goal] = Field(default_factory=list)
    plan_for_retirement: bool = Field(
        default=True, description="Derive a retirement corpus goal from age and expenses"
    )

    @model_validator(mode="after")
    def _apply_defaults(self) -> Scenario:
        if self.emergency_fund_months is None:
            self.emergency_fund_months = EMERGENCY_MONTHS_BY_EMPLOYMENT[self.employment]
        return self

    @property
    def total_min_payments(self) -> float:
        return sum(d.min_payment for d in self.debts)

    @property
    def monthly_surplus(self) -> float:
        """What is left each month once life and minimum debt payments are paid."""
        return self.monthly_income - self.monthly_expenses - self.total_min_payments

    @property
    def monthly_burn(self) -> float:
        """What a month actually costs — living plus debt service."""
        return self.monthly_expenses + self.total_min_payments

    @property
    def emergency_target(self) -> float:
        return self.monthly_burn * (self.emergency_fund_months or 0)

    @property
    def total_debt(self) -> float:
        return sum(d.balance for d in self.debts)

    @property
    def years_to_retirement(self) -> float | None:
        if self.age is None:
            return None
        return max(self.retirement_age - self.age, 0)

    def retirement_goal(self) -> Goal | None:
        """Corpus needed to fund today's spending for life, in future rupees.

        Uses the 4% convention on inflation-adjusted annual expenses. It is a
        planning anchor, not a guarantee — sequence-of-returns risk is real and
        this single number cannot express it.
        """
        years = self.years_to_retirement
        if not self.plan_for_retirement or years is None or years <= 0:
            return None
        annual_now = self.monthly_expenses * 12
        return Goal(
            name="Retirement corpus",
            amount_today=annual_now / SAFE_WITHDRAWAL_RATE,
            years=years,
            priority=1,
        )

    def all_goals(self) -> list[Goal]:
        retirement = self.retirement_goal()
        return [*self.goals, *([retirement] if retirement else [])]


class Milestone(BaseModel):
    name: str
    month: int | None = Field(description="Months from now; None if not reached in the horizon")
    detail: str


class Step(BaseModel):
    order: int
    title: str
    why: str
    action: str
    amount_monthly: float | None = None


class GoalOutlook(BaseModel):
    name: str
    amount_today: float
    amount_at_due: float
    due_month: int
    monthly_needed: float
    on_track: bool
    note: str


class ProtectionGap(BaseModel):
    """Insurance shortfall. Cheap to fix, and it invalidates the plan if ignored."""

    term_cover_needed: float
    term_cover_gap: float
    health_cover_suggested: float
    health_cover_gap: float
    note: str


class Projection(BaseModel):
    """One simulated path. `band` names the return assumption behind it."""

    band: str
    annual_return_pct: float
    months: int
    debt_free_month: int | None
    final_investments: float
    final_cash: float
    final_net_worth: float
    total_interest_paid: float
    net_worth_by_year: list[float] = Field(default_factory=list)


class Plan(BaseModel):
    scenario: Scenario
    feasible: bool
    headline: str
    steps: list[Step]
    milestones: list[Milestone]
    projections: list[Projection]
    goals: list[GoalOutlook] = Field(default_factory=list)
    protection: ProtectionGap | None = None
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "Projections are arithmetic under stated assumptions, not predictions. "
        "Markets do not deliver a steady return, and the range shown is not a "
        "worst case. Educational content, not licensed financial advice."
    )
