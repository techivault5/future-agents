# Finance Advisor

Personal-finance advisor agent + curated knowledge base (debt, saving, budgeting, credit, investing basics) gathered from financial sources and the top YouTube finance educators.

## Layout

```
projects/finance_advisor/
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

## Usage

```python
from projects.finance_advisor.gather import load_knowledge, build_advisor

store = load_knowledge()                 # KnowledgeStore with all entries
store.search("avalanche", domain="finance.debt")
store.by_tag("emergency-fund")

defn = build_advisor()                   # AgentDefinition for the advisor
```

CLI:

```bash
python projects/finance_advisor/gather.py            # load + print stats
python projects/finance_advisor/gather.py --search "snowball"
python projects/finance_advisor/gather.py --youtube  # refresh channel uploads (needs YOUTUBE_API_KEY)
```

`--youtube` requires `YOUTUBE_API_KEY` (YouTube Data API v3) — see `.env.example`. Without it, the static curated catalog is used.

## Disclaimer

Educational content only — not licensed financial advice. The advisor agent's constraints enforce this in every response.
