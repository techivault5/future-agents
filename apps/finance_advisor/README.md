# Finance Advisor

Personal-finance advisor agent + curated knowledge base (debt, saving, budgeting, credit, investing basics) gathered from financial sources and the top YouTube finance educators.

## Layout

```
apps/finance_advisor/
  agent.json               # AgentDefinition (loadable via DefinitionLoader)
  gather.py                # Load knowledge/ into KnowledgeStore; optional YouTube refresh
  knowledge/
    debt.json              # Payoff strategies, consolidation, collections
    saving.json            # Emergency funds, HYSA, automation
    budgeting.json         # 50/30/20, zero-based, envelope, pay-yourself-first
    credit.json            # Scores, utilization, reports
    investing.json         # Index funds, retirement accounts, compound growth
    asset_classes.json     # Full asset map, allocation, stocks vs funds, REITs, intl
    india_investing.json   # SIP/mutual funds, ELSS/80C, PPF/EPF/NPS, FDs, tax, SEBI
    crypto.json            # Bitcoin/VDA risk, India 30%+1% TDS, custody, scams
    gold_silver.json       # 2025 rally + 2026 outlook, gold ETFs, SGB status, silver
    market_voices.json     # Guru principles, Indian voices, 2026 trends, wealth playbook
    frameworks.json        # Ramsey Baby Steps, Money Guy FOO, Ramit CSP, FIRE
    youtube_channels.json  # US + India channel catalog + finfluencer evaluation
  SOURCES.md               # Research sources
```

## Memory framework + pluggable SDKs

`memory/` adds agent memory (working / episodic / semantic / procedural / graph),
swappable backends (in-memory, sqlite+FTS5, graph with Cypher export), swappable
embedders (zero-dep hashing → sentence-transformers / Ollama / ONNX-NPU), a
local-inference comparison matrix (CPU / GPU / NPU / Metal / browser), and five
finance skills (loans, Indian mutual funds, crypto, capital gains, taxes).

Same API in Python, the browser and VS Code — embeddings are byte-identical
across runtimes, so memories are portable. See `memory/README.md`.

```python
from finance_advisor.memory import FinanceMemorySDK

sdk = FinanceMemorySDK(store="sqlite", path="data/memory.db")
sdk.remember("take_home=180000", tags=["profile"], sensitive=True)
sdk.advise("loans", principal=3_500_000, annual_rate_pct=8.6, months=240)
```

Browser demo: `http://localhost:8600/sdk/js/demo.html` ·
VS Code: `code --extensionDevelopmentPath=apps/finance_advisor/memory/sdk/vscode`

## Dashboard + alerts

```bash
pip install -e ".[api]"
uvicorn finance_advisor.app:app --port 8600
# open http://localhost:8600
```

- **Markets & signals**: gold/silver ETFs (INR), Nifty 50/Sensex/NIFTYBEES, Bitcoin — live via Yahoo Finance/CoinGecko, with rule-based dip-watch / neutral / extended zones (52-week-high gap + 50-day trend) and curated analyst-outlook notes.
- **Indian mutual funds**: SIP watchlist NAVs from AMFI (Parag Parikh/HDFC Flexi, Nippon/ICICI large cap, UTI/HDFC Nifty index, quant ELSS, Mirae L&M).
- **Property watch**: NHB RESIDEX (India) + CSO RPPI (Ireland), curated quarterly data.
- **Guidance**: saving/budgeting/debt/India/trends tips from the knowledge base.
- **Alerts → email**: create rules in the UI (price above/below, % drop from 52-week high, sharp daily moves, dip-watch signal). The scheduled worker (`.github/workflows/finance-alerts.yml`, 3×/day) evaluates rules and emails via SMTP. Configure repo secrets: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` (Gmail app password), `ALERT_EMAIL` (default recipient). Test locally: `python -m finance_advisor.alerts --dry-run`.

## Plan my money — scenario planner with what-ifs

Describe your situation; get an ordered plan, a projection band, and levers you
can pull to see what each one is worth.

```
planner/
  models.py    Scenario · Debt · Goal → Plan · Step · Projection · ProtectionGap
  engine.py    month-by-month simulation, ordered steps, insurance + goal checks
  savings.py   personalised levers + the financial-freedom stage ladder
  whatif.py    ten variants, each re-run against the baseline through one code path
```

**Deterministic, not predictive.** No forecasting model and no LLM touches the
numbers — every figure is arithmetic on your own inputs under assumptions
printed on the result. A plan you can recompute by hand is one you can argue
with. Results come as a **band** (8% / 12% / 15%), never a single figure,
because one number reads as a promise.

**The ordering** is the opinionated part, and each step says why it sits where
it does: insurance gap → starter buffer → debt above your hurdle rate →
emergency fund → unused tax deductions → automated investing. Debt *below* the
hurdle is presented as a comparison to run, not an instruction, because the
honest answer depends on returns nobody knows in advance.

**Fields that change the answer**, and no others: income, expenses, bonus and
increment; cash, investments and debts; age, dependants and employment type
(which sets the buffer at 6 or 12 months); term and health cover; tax regime
and 80C/NPS usage; inflation, timeline, strategy and goals. Goals are entered in
today's rupees and inflated to their due date. A retirement corpus is derived
from age and spending on the 4% convention.

```python
from finance_advisor.planner import Scenario, Debt, Goal, build_plan, run_variant

plan = build_plan(
    Scenario(
        monthly_income=180_000,
        monthly_expenses=90_000,
        cash_savings=200_000,
        debts=[Debt(name="Card", balance=180_000, annual_rate_pct=42, min_payment=9_000)],
        goals=[Goal(name="House deposit", amount_today=2_000_000, years=5)],
        age=34,
        dependants=2,
        timeline_months=120,
    )
)
run_variant(plan.scenario, "extra_monthly", {"amount": 5_000})
```

### Savings levers, priced by what they compound into

Generic tips ("cancel subscriptions") are worthless because they don't know the
reader. Every lever is **detected from the user's own numbers**, produces an
amount derived from those numbers, and shows its arithmetic in a `basis` field
so the figure can be checked rather than believed.

The ranking is the point: levers are ordered by **what the saving becomes**, not
by how big the monthly figure looks — those two orderings differ, and only one
of them matters. ₹2,000/month is ₹4.44 lakh over ten years at 12%.

Categories: `plug_leaks` · `return_efficiency` · `tax_efficiency` ·
`cut_fixed_costs` · `behaviour` · `earn_more`. Each lever carries an effort
rating and a confidence score; low-confidence ones (the discretionary audit)
are labelled as prompts to look, not measurements, and never lead the list.

**Overlapping levers are flagged, not summed.** Clearing a card and refinancing
it target the same rupees — adding both would invent money. The dominated lever
is still shown, marked `alternative_to`, and excluded from the total.

### Financial-freedom stage

Seven rungs — underwater → buffered → solvent → secure → investing → **Coast FI**
→ financially free — with exactly one thing that matters on the rung you're on.
Plus savings rate, FI number (4% convention), progress, years to FI, and the
Coast FI number: the amount that compounds to your FI target by retirement with
no further contributions.

`years_to_fi` demonstrates the result people find counter-intuitive and a test
asserts it: **doubling income while doubling spending changes the timeline not
at all.** Savings rate dominates return.

What-ifs: `extra_monthly`, `lump_sum`, `job_loss`, `rate_shock`, `cut_expenses`,
`snowball`, `avalanche`, `prepay_all`, `invest_instead`, `high_inflation`. When
a variant pushes a debt across your hurdle rate the strategy itself changes —
which can send total interest the way you least expect — so the result says so
rather than letting it look like a bug.

Endpoints: `POST /api/plan`, `POST /api/plan/savings`, `GET /api/plan/whatifs`,
`POST /api/plan/whatif`.
The scenario is used for the request and **not stored**; nothing about your
balance sheet is persisted unless you explicitly save a memory. The chat agent
reaches the same engine through the `build_scenario_plan`, `savings_opportunities`
and `what_if` tools.

## Ask the advisor — agentic chat, bring your own key

The dashboard's chat panel runs a real tool-calling agent over the same data the
rest of the page shows. It picks its own tools: recall what you have told it,
pull live prices, run the Indian tax and SIP maths, search the knowledge base.

```
agent/
  providers.py   Anthropic (official SDK, claude-opus-5, adaptive thinking),
                 any OpenAI-compatible endpoint, Ollama (local, no key)
  tools.py       recall_memory · remember_fact · user_profile · market_snapshot
                 fund_navs · run_skill · knowledge_search · property_watch
  loop.py        the agentic loop, streamed to the UI as SSE events
```

**Where your key lives.** You type it into the browser; it is held in
`sessionStorage` (that tab only, gone when the tab closes), sent to the app for
one request, used for that request's provider calls, and dropped. It is never
written to disk, never logged, and never returned by any endpoint — `/api/agent/
providers` reports only *whether* a server-side key exists, never its value. If
you prefer, set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` on the server and leave
the box empty. Choosing Ollama sends nothing off the machine.

**What the agent can and cannot do.** Every tool is local or read-only public
market data. Nothing can place an order, move money, or send mail. Memories you
marked `sensitive` are redacted *before* recall returns them, so an exact salary
or balance never reaches a third-party model. Conversation transcripts stay in
the app process, capped and never persisted.

```python
from finance_advisor.agent import build_toolset, run_agent
from finance_advisor.memory import FinanceMemorySDK

tools = build_toolset(FinanceMemorySDK(store="sqlite", path="data/memory.db"))
for event in run_agent(
    message="can I service a ₹35L home loan?", tools=tools, provider_name="ollama", model="llama3.1"
):
    print(event)  # tool_call | tool_result | text | usage | error | done
```

Anthropic needs `pip install -e ".[ai]"`; the other two providers need nothing
beyond the standard library.

## Usage

```python
from finance_advisor.gather import load_knowledge, build_advisor

store = load_knowledge()  # KnowledgeStore with all entries
store.search("avalanche", domain="finance.debt")
store.by_tag("emergency-fund")

defn = build_advisor()  # AgentDefinition for the advisor
```

CLI:

```bash
python apps/finance_advisor/gather.py            # load + print stats
python apps/finance_advisor/gather.py --search "snowball"
python apps/finance_advisor/gather.py --youtube  # refresh channel uploads (needs YOUTUBE_API_KEY)
```

`--youtube` requires `YOUTUBE_API_KEY` (YouTube Data API v3) — see `.env.example`. Without it, the static curated catalog is used.

## Disclaimer

Educational content only — not licensed financial advice. The advisor agent's constraints enforce this in every response.
