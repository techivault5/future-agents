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
