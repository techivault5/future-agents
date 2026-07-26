"""Finance skills — deterministic, memory-aware, educational only.

Each skill is a small pure calculator plus guidance drawn from the knowledge
base, wrapped so that:

  * inputs it learns (income, EMI, risk appetite) are written to memory,
  * prior memories are recalled to fill gaps the caller did not supply,
  * every result carries its own maths so a user can check it by hand,
  * every result carries the educational disclaimer.

Nothing here recommends a specific security, promises a return, or files a tax
return for anyone. The numbers are illustrations of published rules; rates and
slabs change, so treat the constants as inputs, not gospel.
"""

from __future__ import annotations

from projects.finance_advisor.memory.manager import MemoryManager
from projects.finance_advisor.memory.types import MemoryType

DISCLAIMER = "Educational content, not licensed financial advice."

# India tax constants as of FY 2025-26 (verify before relying on them).
EQUITY_LTCG_RATE = 0.125
EQUITY_LTCG_EXEMPTION = 125_000
EQUITY_STCG_RATE = 0.20
EQUITY_LTCG_HOLDING_MONTHS = 12
VDA_TAX_RATE = 0.30
VDA_TDS_RATE = 0.01
SECTION_80C_CAP = 150_000
NPS_80CCD1B_CAP = 50_000


class FinanceSkill:
    """Base class: gives every skill memory read/write and a result envelope."""

    name = "skill"
    covers = ""

    def __init__(self, memory: MemoryManager | None = None) -> None:
        self.memory = memory or MemoryManager()

    def _remember_input(self, key: str, value: object, sensitive: bool = False) -> None:
        """Persist a caller-supplied fact as a durable profile memory."""
        self.memory.remember(
            f"{key}={value}",
            type=MemoryType.SEMANTIC,
            tags=["profile", self.name],
            importance=0.7,
            sensitive=sensitive,
        )

    def _log_episode(self, summary: str) -> None:
        """Record that this skill ran, for consolidation and audit."""
        self.memory.remember(
            summary,
            type=MemoryType.EPISODIC,
            tags=[self.name],
            importance=0.4,
            source="agent",
        )

    def _envelope(self, **payload: object) -> dict:
        """Standard result shape: skill name, payload, memory context, disclaimer."""
        return {"skill": self.name, **payload, "disclaimer": DISCLAIMER}


class LoanAdvisorSkill(FinanceSkill):
    """EMI maths, affordability limits, and payoff-vs-invest comparisons."""

    name = "loans"
    covers = "EMI, affordability, prepayment vs investing, avalanche vs snowball"

    @staticmethod
    def emi(principal: float, annual_rate_pct: float, months: int) -> float:
        """Standard reducing-balance EMI: P·r·(1+r)^n / ((1+r)^n − 1)."""
        if months <= 0:
            raise ValueError("months must be positive")
        r = annual_rate_pct / 12 / 100
        if r == 0:
            return principal / months
        factor = (1 + r) ** months
        return principal * r * factor / (factor - 1)

    def affordability(self, monthly_take_home: float, existing_emi: float = 0.0) -> dict:
        """Headroom for new EMI under the conventional 40%-of-take-home ceiling."""
        ceiling = 0.40 * monthly_take_home
        housing_ceiling = 0.30 * monthly_take_home
        return {
            "total_emi_ceiling": round(ceiling, 2),
            "housing_emi_ceiling": round(housing_ceiling, 2),
            "existing_emi": round(existing_emi, 2),
            "headroom": round(max(ceiling - existing_emi, 0.0), 2),
            "rule": "Total EMIs ≤40% of take-home; housing alone ≤30%. Lenders may "
            "allow more — that is their risk appetite, not your safety margin.",
        }

    def payoff_order(self, debts: list[dict], extra_monthly: float = 0.0) -> dict:
        """Compare avalanche (highest APR) and snowball (smallest balance) orders."""
        if not debts:
            return {"skill": self.name, "error": "no debts supplied", "disclaimer": DISCLAIMER}
        avalanche = sorted(debts, key=lambda d: -float(d.get("apr", 0)))
        snowball = sorted(debts, key=lambda d: float(d.get("balance", 0)))
        blended = sum(float(d.get("balance", 0)) * float(d.get("apr", 0)) for d in debts) / max(
            sum(float(d.get("balance", 0)) for d in debts), 1e-9
        )
        spread = max(float(d.get("apr", 0)) for d in debts) - min(
            float(d.get("apr", 0)) for d in debts
        )
        recommendation = (
            "avalanche" if spread >= 4 else "snowball (APRs are close; take the motivation)"
        )
        self._remember_debts(debts)
        return {
            "skill": self.name,
            "avalanche_order": [d.get("name", "?") for d in avalanche],
            "snowball_order": [d.get("name", "?") for d in snowball],
            "blended_apr_pct": round(blended, 2),
            "apr_spread_pct": round(spread, 2),
            "extra_monthly": extra_monthly,
            "recommended": recommendation,
            "why": "Avalanche minimises interest; snowball maximises completion odds. "
            "With an APR spread under ~4 points the cost difference is small.",
            "disclaimer": DISCLAIMER,
        }

    def _remember_debts(self, debts: list[dict]) -> None:
        for debt in debts:
            self.memory.remember(
                f"debt {debt.get('name', '?')}: balance={debt.get('balance')} "
                f"apr={debt.get('apr')}",
                type=MemoryType.SEMANTIC,
                tags=["profile", "loans", "debt"],
                importance=0.75,
                sensitive=True,
            )

    def prepay_vs_invest(self, loan_apr_pct: float, expected_return_pct: float = 10.0) -> dict:
        """Which rupee wins: loan prepayment (guaranteed) or investing (expected)."""
        gap = expected_return_pct - loan_apr_pct
        if loan_apr_pct >= 10:
            verdict = "prepay — a guaranteed saving at this APR beats an uncertain return"
        elif loan_apr_pct <= 5:
            verdict = "invest — the spread favours the market over a decade-plus horizon"
        else:
            verdict = "either is defensible; split the surplus if you cannot decide"
        return {
            "skill": self.name,
            "loan_apr_pct": loan_apr_pct,
            "expected_return_pct": expected_return_pct,
            "spread_pct": round(gap, 2),
            "verdict": verdict,
            "always_first": "Capture any employer retirement match before either — "
            "that is an instant return no loan rate beats.",
            "disclaimer": DISCLAIMER,
        }

    def advise(self, **kwargs: object) -> dict:
        """Entry point used by the SDK: routes on the arguments supplied."""
        if "debts" in kwargs:
            return self.payoff_order(
                list(kwargs["debts"]), float(kwargs.get("extra_monthly", 0) or 0)
            )
        if "monthly_take_home" in kwargs:
            result = self.affordability(
                float(kwargs["monthly_take_home"]), float(kwargs.get("existing_emi", 0) or 0)
            )
            self.memory.remember(
                f"monthly_take_home={kwargs['monthly_take_home']}",
                type=MemoryType.SEMANTIC,
                tags=["profile", "loans"],
                importance=0.8,
                sensitive=True,
            )
            return {"skill": self.name, **result, "disclaimer": DISCLAIMER}
        if "principal" in kwargs:
            months = int(kwargs.get("months", 240))
            rate = float(kwargs.get("annual_rate_pct", 9.0))
            principal = float(kwargs["principal"])
            payment = self.emi(principal, rate, months)
            total = payment * months
            return {
                "skill": self.name,
                "principal": principal,
                "annual_rate_pct": rate,
                "months": months,
                "emi": round(payment, 2),
                "total_paid": round(total, 2),
                "total_interest": round(total - principal, 2),
                "disclaimer": DISCLAIMER,
            }
        if "loan_apr_pct" in kwargs:
            return self.prepay_vs_invest(
                float(kwargs["loan_apr_pct"]), float(kwargs.get("expected_return_pct", 10.0))
            )
        return {
            "skill": self.name,
            "usage": "pass principal+annual_rate_pct+months, or monthly_take_home, "
            "or debts=[{name,balance,apr}], or loan_apr_pct",
            "disclaimer": DISCLAIMER,
        }


class MutualFundSkill(FinanceSkill):
    """Indian SIP maths: future value, step-up, and goal-required contributions."""

    name = "mutual_funds"
    covers = "SIP future value, step-up SIP, goal planning, direct-vs-regular cost drag"

    @staticmethod
    def sip_future_value(monthly: float, annual_return_pct: float, years: int) -> float:
        """FV of a monthly SIP: M·((1+i)^n − 1)/i·(1+i), i = monthly rate."""
        i = annual_return_pct / 12 / 100
        n = years * 12
        if i == 0:
            return monthly * n
        return monthly * (((1 + i) ** n - 1) / i) * (1 + i)

    @staticmethod
    def step_up_sip_future_value(
        monthly: float, annual_return_pct: float, years: int, step_up_pct: float = 10.0
    ) -> float:
        """FV when the SIP amount is raised by `step_up_pct` every year."""
        i = annual_return_pct / 12 / 100
        total = 0.0
        amount = monthly
        for year in range(years):
            months_remaining = (years - year) * 12
            for _ in range(12):
                months_remaining -= 1
                total += amount * ((1 + i) ** (months_remaining + 1))
            amount *= 1 + step_up_pct / 100
        return total

    @staticmethod
    def required_sip(target: float, annual_return_pct: float, years: int) -> float:
        """Monthly SIP needed to reach `target` — the goal-planning inverse."""
        i = annual_return_pct / 12 / 100
        n = years * 12
        if i == 0:
            return target / n
        return target / ((((1 + i) ** n - 1) / i) * (1 + i))

    @staticmethod
    def cost_drag(
        monthly: float, years: int, gross_return_pct: float, expense_gap_pct: float
    ) -> dict:
        """Wealth lost to a higher expense ratio (regular vs direct plans)."""
        cheap = MutualFundSkill.sip_future_value(monthly, gross_return_pct, years)
        dear = MutualFundSkill.sip_future_value(monthly, gross_return_pct - expense_gap_pct, years)
        return {
            "direct_plan_value": round(cheap, 2),
            "regular_plan_value": round(dear, 2),
            "lost_to_commission": round(cheap - dear, 2),
            "expense_gap_pct": expense_gap_pct,
        }

    def advise(self, **kwargs: object) -> dict:
        """Route on arguments: goal target, or a monthly SIP projection."""
        years = int(kwargs.get("years", 15))
        expected = float(kwargs.get("annual_return_pct", 12.0))
        if "target" in kwargs:
            target = float(kwargs["target"])
            monthly = self.required_sip(target, expected, years)
            self.memory.remember(
                f"goal={target} in {years}y",
                type=MemoryType.SEMANTIC,
                tags=["profile", "mutual_funds", "goal"],
                importance=0.8,
            )
            return {
                "skill": self.name,
                "target": target,
                "years": years,
                "assumed_return_pct": expected,
                "required_monthly_sip": round(monthly, 2),
                "note": "Assumed returns are not promises. Step up the SIP ~10%/yr so a "
                "weaker market does not sink the goal.",
                "disclaimer": DISCLAIMER,
            }
        monthly = float(kwargs.get("monthly", 10_000))
        step_up = float(kwargs.get("step_up_pct", 0) or 0)
        flat = self.sip_future_value(monthly, expected, years)
        invested = monthly * years * 12
        result = {
            "skill": self.name,
            "monthly": monthly,
            "years": years,
            "assumed_return_pct": expected,
            "invested": round(invested, 2),
            "future_value": round(flat, 2),
            "gain": round(flat - invested, 2),
            "cost_drag_vs_regular_plan": self.cost_drag(monthly, years, expected, 1.0),
            "category_guidance": "Core 70-80% in flexi/large-cap or a broad index fund; "
            "satellite 20-30% in mid/small-cap or international. Always DIRECT plans, "
            "growth option.",
            "disclaimer": DISCLAIMER,
        }
        if step_up:
            stepped = self.step_up_sip_future_value(monthly, expected, years, step_up)
            result["step_up_pct"] = step_up
            result["step_up_future_value"] = round(stepped, 2)
            result["step_up_advantage"] = round(stepped - flat, 2)
        self.memory.remember(
            f"sip_monthly={monthly}",
            type=MemoryType.SEMANTIC,
            tags=["profile", "mutual_funds"],
            importance=0.7,
        )
        return result


class CryptoSkill(FinanceSkill):
    """Position sizing and India's VDA tax reality — deliberately unexciting."""

    name = "crypto"
    covers = "allocation caps, 30% VDA tax + 1% TDS after-tax maths, custody, scam checks"

    @staticmethod
    def position_cap(portfolio_value: float, risk_tolerance: str = "moderate") -> dict:
        """Allocation ceiling by risk tolerance; 5% default, 10% absolute maximum."""
        caps = {"conservative": 0.0, "moderate": 0.05, "aggressive": 0.10}
        pct = caps.get(risk_tolerance, 0.05)
        return {
            "risk_tolerance": risk_tolerance,
            "cap_pct": pct * 100,
            "cap_amount": round(portfolio_value * pct, 2),
            "rule": "Fund it only after emergency fund, insurance and core equity are "
            "in place, with money you could lose entirely.",
        }

    @staticmethod
    def after_tax_gain(buy_value: float, sell_value: float) -> dict:
        """India VDA maths: flat 30% on gains, 1% TDS on the sale, no loss offset."""
        gain = sell_value - buy_value
        tax = max(gain, 0.0) * VDA_TAX_RATE
        tds = sell_value * VDA_TDS_RATE
        return {
            "buy_value": buy_value,
            "sell_value": sell_value,
            "gross_gain": round(gain, 2),
            "vda_tax_30pct": round(tax, 2),
            "tds_1pct_on_sale": round(tds, 2),
            "net_gain_after_tax": round(gain - tax, 2),
            "note": "TDS is adjustable against final liability, not an extra tax. "
            "Losses cannot be set off against other income or other VDA trades — "
            "which makes frequent trading brutally inefficient in India.",
        }

    def advise(self, **kwargs: object) -> dict:
        """Route on arguments: sizing, or after-tax outcome of a trade."""
        if "sell_value" in kwargs:
            return {
                "skill": self.name,
                **self.after_tax_gain(
                    float(kwargs.get("buy_value", 0)), float(kwargs["sell_value"])
                ),
                "disclaimer": DISCLAIMER,
            }
        portfolio = float(kwargs.get("portfolio_value", 0))
        tolerance = str(kwargs.get("risk_tolerance", "moderate"))
        self.memory.remember(
            f"risk_tolerance={tolerance}",
            type=MemoryType.SEMANTIC,
            tags=["profile", "crypto"],
            importance=0.6,
        )
        return {
            "skill": self.name,
            **self.position_cap(portfolio, tolerance),
            "custody": "Hardware wallet for meaningful holdings; seed phrase on paper or "
            "steel, never photographed or cloud-stored. Use FIU-registered exchanges "
            "for on/off ramps.",
            "scam_tests": [
                "Guaranteed or fixed returns = scam",
                "Urgency or pressure = scam",
                "Cannot withdraw until you pay a fee/tax = scam",
                "Recovery services promising to retrieve lost funds = scam",
            ],
            "disclaimer": DISCLAIMER,
        }


class CapitalGainsSkill(FinanceSkill):
    """Indian equity capital-gains maths, exemption harvesting, holding periods."""

    name = "capital_gains"
    covers = "LTCG 12.5% above ₹1.25L, STCG 20%, holding period, exemption harvesting"

    @staticmethod
    def equity_gain_tax(
        buy_value: float, sell_value: float, holding_months: int, prior_ltcg_used: float = 0.0
    ) -> dict:
        """Tax on one equity/equity-fund sale, applying the annual LTCG exemption."""
        gain = sell_value - buy_value
        long_term = holding_months >= EQUITY_LTCG_HOLDING_MONTHS
        if gain <= 0:
            return {
                "gain": round(gain, 2),
                "classification": "long-term" if long_term else "short-term",
                "tax": 0.0,
                "note": "Capital losses can be carried forward eight years if you file "
                "the return on time — worth doing even in a loss year.",
            }
        if long_term:
            exemption_left = max(EQUITY_LTCG_EXEMPTION - prior_ltcg_used, 0.0)
            taxable = max(gain - exemption_left, 0.0)
            tax = taxable * EQUITY_LTCG_RATE
            return {
                "gain": round(gain, 2),
                "classification": "long-term",
                "exemption_applied": round(min(gain, exemption_left), 2),
                "taxable_gain": round(taxable, 2),
                "rate_pct": EQUITY_LTCG_RATE * 100,
                "tax": round(tax, 2),
                "note": f"₹{EQUITY_LTCG_EXEMPTION:,} of equity LTCG is exempt each year. "
                "Harvest it deliberately rather than letting it lapse.",
            }
        return {
            "gain": round(gain, 2),
            "classification": "short-term",
            "taxable_gain": round(gain, 2),
            "rate_pct": EQUITY_STCG_RATE * 100,
            "tax": round(gain * EQUITY_STCG_RATE, 2),
            "note": f"Holding {EQUITY_LTCG_HOLDING_MONTHS}+ months would move this to the "
            f"{EQUITY_LTCG_RATE * 100:.1f}% long-term rate with an annual exemption. "
            "Check the date before you sell.",
        }

    @staticmethod
    def harvest_plan(unrealised_ltcg: float, prior_ltcg_used: float = 0.0) -> dict:
        """How much long-term gain can be realised tax-free this year."""
        room = max(EQUITY_LTCG_EXEMPTION - prior_ltcg_used, 0.0)
        return {
            "exemption_room": round(room, 2),
            "harvestable_now": round(min(unrealised_ltcg, room), 2),
            "method": "Sell up to the exemption, then rebuy if you still want the "
            "position — it resets your cost base higher at zero tax cost.",
            "watch": "Rebuying immediately keeps market exposure but restarts the "
            "12-month clock on the new lot.",
        }

    def advise(self, **kwargs: object) -> dict:
        """Route on arguments: a specific sale, or annual harvesting room."""
        if "sell_value" in kwargs:
            result = self.equity_gain_tax(
                float(kwargs.get("buy_value", 0)),
                float(kwargs["sell_value"]),
                int(kwargs.get("holding_months", 0)),
                float(kwargs.get("prior_ltcg_used", 0) or 0),
            )
            self._log(result)
            return {"skill": self.name, **result, "disclaimer": DISCLAIMER}
        return {
            "skill": self.name,
            **self.harvest_plan(
                float(kwargs.get("unrealised_ltcg", 0)),
                float(kwargs.get("prior_ltcg_used", 0) or 0),
            ),
            "disclaimer": DISCLAIMER,
        }

    def _log(self, result: dict) -> None:
        self.memory.remember(
            f"capital gains computed: {result.get('classification')} "
            f"gain={result.get('gain')} tax={result.get('tax')}",
            type=MemoryType.EPISODIC,
            tags=["capital_gains"],
            importance=0.5,
            source="agent",
            sensitive=True,
        )


class TaxGuidanceSkill(FinanceSkill):
    """Regime pointers, 80C capacity, and what each asset class attracts."""

    name = "taxes"
    covers = "old vs new regime pointers, 80C/80CCD capacity, asset-wise treatment"

    @staticmethod
    def deduction_capacity(
        existing_80c: float = 0.0, has_nps: bool = False, regime: str = "new"
    ) -> dict:
        """Remaining 80C/80CCD(1B) room — meaningful only under the old regime."""
        if regime == "new":
            return {
                "regime": "new",
                "section_80c_room": 0.0,
                "note": "The new regime (default since FY 2023-24) forgoes 80C/80CCD(1B). "
                "Under it, choose ELSS or NPS on investment merit alone, not for the "
                "deduction. Employer NPS contribution under 80CCD(2) can still apply.",
            }
        room = max(SECTION_80C_CAP - existing_80c, 0.0)
        return {
            "regime": "old",
            "section_80c_cap": SECTION_80C_CAP,
            "section_80c_used": round(existing_80c, 2),
            "section_80c_room": round(room, 2),
            "nps_80ccd1b_room": 0.0 if has_nps else NPS_80CCD1B_CAP,
            "priority": "ELSS (3-yr lock-in, equity) > NPS > PPF > tax-saver FD. "
            "Never buy endowment or ULIP policies for the deduction.",
        }

    @staticmethod
    def asset_treatment() -> list[dict]:
        """How each asset class is taxed in India — the cheat sheet."""
        return [
            {
                "asset": "Equity shares / equity mutual funds",
                "long_term": f"{EQUITY_LTCG_RATE * 100:.1f}% above "
                f"₹{EQUITY_LTCG_EXEMPTION:,}/yr, after 12 months",
                "short_term": f"{EQUITY_STCG_RATE * 100:.0f}%",
            },
            {
                "asset": "Debt funds / FDs / RDs",
                "long_term": "Slab rate",
                "short_term": "Slab rate",
            },
            {
                "asset": "Gold ETFs / gold funds",
                "long_term": "Per prevailing non-equity rules; check the year of sale",
                "short_term": "Slab rate",
            },
            {
                "asset": "Crypto / VDAs",
                "long_term": f"Flat {VDA_TAX_RATE * 100:.0f}% regardless of holding period",
                "short_term": f"Flat {VDA_TAX_RATE * 100:.0f}% + "
                f"{VDA_TDS_RATE * 100:.0f}% TDS, no loss set-off",
            },
            {
                "asset": "EPF / PPF",
                "long_term": "Exempt-Exempt-Exempt within statutory limits",
                "short_term": "n/a",
            },
        ]

    def advise(self, **kwargs: object) -> dict:
        """Deduction room plus the asset-wise treatment table."""
        regime = str(kwargs.get("regime", "new"))
        capacity = self.deduction_capacity(
            float(kwargs.get("existing_80c", 0) or 0),
            bool(kwargs.get("has_nps", False)),
            regime,
        )
        self.memory.remember(
            f"tax_regime={regime}",
            type=MemoryType.SEMANTIC,
            tags=["profile", "taxes"],
            importance=0.7,
        )
        return {
            "skill": self.name,
            **capacity,
            "asset_treatment": self.asset_treatment(),
            "escalate": "Large sums, capital-gains on property, ESOPs, foreign assets or "
            "residency changes need a chartered accountant — not an agent.",
            "disclaimer": DISCLAIMER,
        }


SKILLS: dict[str, type] = {
    LoanAdvisorSkill.name: LoanAdvisorSkill,
    MutualFundSkill.name: MutualFundSkill,
    CryptoSkill.name: CryptoSkill,
    CapitalGainsSkill.name: CapitalGainsSkill,
    TaxGuidanceSkill.name: TaxGuidanceSkill,
}


def skill_catalog() -> list[dict]:
    """Name + coverage for every registered skill, for docs and the dashboard."""
    return [{"name": cls.name, "covers": cls.covers} for cls in SKILLS.values()]
