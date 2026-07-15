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

## Dashboard + alerts

```bash
pip install -e ".[api]"
uvicorn projects.finance_advisor.app:app --port 8600
# open http://localhost:8600
```

- **Markets & signals**: gold/silver ETFs (INR), Nifty 50/Sensex/NIFTYBEES, Bitcoin — live via Yahoo Finance/CoinGecko, with rule-based dip-watch / neutral / extended zones (52-week-high gap + 50-day trend) and curated analyst-outlook notes.
- **Indian mutual funds**: SIP watchlist NAVs from AMFI (Parag Parikh/HDFC Flexi, Nippon/ICICI large cap, UTI/HDFC Nifty index, quant ELSS, Mirae L&M).
- **Property watch**: NHB RESIDEX (India) + CSO RPPI (Ireland), curated quarterly data.
- **Guidance**: saving/budgeting/debt/India/trends tips from the knowledge base.
- **Alerts → email**: create rules in the UI (price above/below, % drop from 52-week high, sharp daily moves, dip-watch signal). The scheduled worker (`.github/workflows/finance-alerts.yml`, 3×/day) evaluates rules and emails via SMTP. Configure repo secrets: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` (Gmail app password), `ALERT_EMAIL` (default recipient). Test locally: `python -m projects.finance_advisor.alerts --dry-run`.

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
