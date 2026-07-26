"""Market data fetchers + rule-based signals for the Finance Advisor dashboard.

Free, keyless sources: CoinGecko (crypto), Yahoo Finance chart API (Indian
ETFs/indices), AMFI NAVAll.txt (Indian mutual fund NAVs), Frankfurter (FX).
All signals are educational heuristics, not financial advice.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

UA = {"User-Agent": "Mozilla/5.0 (finance-advisor-dashboard)"}
CACHE_TTL_SECONDS = 300

# Watched assets: key → (yahoo symbol, display name, kind)
WATCHED_ASSETS = {
    "gold": ("GOLDBEES.NS", "Gold (GOLDBEES ETF, INR)", "metal"),
    "silver": ("SILVERBEES.NS", "Silver (SILVERBEES ETF, INR)", "metal"),
    "nifty50": ("^NSEI", "Nifty 50", "index"),
    "sensex": ("^BSESN", "Sensex", "index"),
    "niftybees": ("NIFTYBEES.NS", "Nifty 50 ETF (NIFTYBEES)", "index"),
    "bitcoin": ("BTC-USD", "Bitcoin (USD)", "crypto"),
}

# Indian mutual fund watchlist: AMFI scheme code → short name
# Direct-Growth plans of consistently cited category leaders.
AMFI_WATCHLIST = {
    "122639": "Parag Parikh Flexi Cap (Direct-G)",
    "118955": "HDFC Flexi Cap (Direct-G)",
    "118632": "Nippon India Large Cap (Direct-G)",
    "120586": "ICICI Pru Large Cap / Bluechip (Direct-G)",
    "120716": "UTI Nifty 50 Index (Direct-G)",
    "119063": "HDFC Nifty 50 Index (Direct-G)",
    "120847": "quant ELSS Tax Saver (Direct-G)",
    "118834": "Mirae Asset Large & Midcap (Direct-G)",
}

# Curated analyst-outlook notes shown next to live signals (from SOURCES.md
# research, July 2026). Refresh periodically; these are opinions, not facts.
MARKET_OUTLOOK_NOTES = {
    "gold": (
        "After 2025's ~73% rally, analysts expect consolidation but a "
        "'higher-for-longer' regime; some see ₹1.5L/10g and $5,000/oz in 12-18 months. "
        "Dips are accumulation windows for the 5-10% allocation — not a momentum chase."
    ),
    "silver": (
        "2025's ~174% surge makes silver whiplash-prone; ~50% industrial demand ties it "
        "to the economy. Analysts flag consolidation risk. Keep tactical (0-5%) and "
        "prefer staggered buys on pullbacks."
    ),
    "bitcoin": (
        "India: 30% tax + 1% TDS, no loss offset — buy-and-hold only if you hold at all; "
        "cap at 0-5% of portfolio. Volatility means 20-30% drawdowns are normal, not "
        "automatically buy signals."
    ),
    "nifty50": (
        "SIP flows above ₹30,000 cr/month keep structural support under Indian equities. "
        "For SIP investors, index dips are scheduled sales — continue or step up SIPs "
        "rather than timing."
    ),
    "sensex": (
        "Same discipline as Nifty: corrections are normal (10%+ most years). "
        "Rebalance to plan, don't react to headlines."
    ),
    "niftybees": (
        "ETF route to Nifty 50 for lump-sum tactical buys on dips; for monthly "
        "investing, an index fund SIP automates the same exposure."
    ),
}

_cache: dict[str, tuple[float, object]] = {}


def _get_json(url: str, timeout: int = 15) -> dict | None:
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as err:
        logger.warning("fetch failed %s: %s", url, err)
        return None


def _cached(key: str, fetch_fn):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < CACHE_TTL_SECONDS:
        return hit[1]
    value = fetch_fn()
    if value is not None:
        _cache[key] = (now, value)
    return value


@dataclass
class AssetQuote:
    key: str
    name: str
    kind: str
    price: float | None = None
    currency: str = "INR"
    change_1d_pct: float | None = None
    change_30d_pct: float | None = None
    pct_from_52w_high: float | None = None
    vs_sma50_pct: float | None = None
    sparkline: list[float] = field(default_factory=list)
    signal: str = "unknown"
    signal_reason: str = ""
    outlook: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def compute_signal(quote: AssetQuote) -> tuple[str, str]:
    """Rule-based zone label. Educational heuristic only.

    dip-watch: meaningfully below recent highs/trend — historically where
    staggered buyers add. extended: well above trend after a run — chasing
    risk. neutral: nothing notable.
    """
    high_gap = quote.pct_from_52w_high
    sma_gap = quote.vs_sma50_pct
    if high_gap is None or sma_gap is None:
        return "unknown", "insufficient data"
    if high_gap <= -15:
        return "dip-watch", f"{abs(high_gap):.1f}% below 52-week high"
    if high_gap <= -8 and sma_gap < 0:
        return (
            "dip-watch",
            f"{abs(high_gap):.1f}% off high and below 50-day average",
        )
    if sma_gap >= 12:
        return "extended", f"{sma_gap:.1f}% above 50-day average after a run"
    if high_gap >= -2 and sma_gap >= 8:
        return "extended", "at highs and stretched above trend"
    return "neutral", "within normal range of trend"


def fetch_yahoo_quote(key: str) -> AssetQuote | None:
    symbol, name, kind = WATCHED_ASSETS[key]
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=6mo&interval=1d"
    data = _get_json(url)
    if not data:
        return None
    try:
        result = data["chart"]["result"][0]
        meta = result["meta"]
        closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
        price = meta.get("regularMarketPrice") or (closes[-1] if closes else None)
        if price is None or not closes:
            return None
        quote = AssetQuote(key=key, name=name, kind=kind, price=round(price, 2))
        quote.currency = meta.get("currency", "INR")
        high_52w = meta.get("fiftyTwoWeekHigh")
        if high_52w:
            quote.pct_from_52w_high = round((price / high_52w - 1) * 100, 2)
        if len(closes) >= 2:
            quote.change_1d_pct = round((price / closes[-2] - 1) * 100, 2)
        if len(closes) >= 22:
            quote.change_30d_pct = round((price / closes[-22] - 1) * 100, 2)
        if len(closes) >= 50:
            sma50 = sum(closes[-50:]) / 50
            quote.vs_sma50_pct = round((price / sma50 - 1) * 100, 2)
        quote.sparkline = [round(c, 2) for c in closes[-60:]]
        quote.signal, quote.signal_reason = compute_signal(quote)
        quote.outlook = MARKET_OUTLOOK_NOTES.get(key, "")
        return quote
    except (KeyError, IndexError, TypeError) as err:
        logger.warning("yahoo parse failed for %s: %s", symbol, err)
        return None


def fetch_bitcoin_inr() -> dict | None:
    data = _get_json(
        "https://api.coingecko.com/api/v3/simple/price"
        "?ids=bitcoin&vs_currencies=usd,inr&include_24hr_change=true"
    )
    if data and "bitcoin" in data:
        return data["bitcoin"]
    return None


def fetch_all_quotes() -> list[dict]:
    quotes: list[dict] = []
    for key in WATCHED_ASSETS:
        quote = _cached(f"quote:{key}", lambda k=key: fetch_yahoo_quote(k))
        if quote:
            quotes.append(quote.to_dict())
    btc_extra = _cached("btc_inr", fetch_bitcoin_inr)
    if btc_extra:
        for quote in quotes:
            if quote["key"] == "bitcoin" and btc_extra.get("inr"):
                quote["price_inr"] = btc_extra["inr"]
    return quotes


def fetch_fund_navs() -> list[dict]:
    """Fetch watchlist NAVs from AMFI's daily NAV dump."""

    def _fetch():
        try:
            req = urllib.request.Request(
                "https://portal.amfiindia.com/spages/NAVAll.txt", headers=UA
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                text = resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError) as err:
            logger.warning("AMFI fetch failed: %s", err)
            return None
        funds = []
        for line in text.splitlines():
            parts = line.split(";")
            if len(parts) >= 6 and parts[0].strip() in AMFI_WATCHLIST:
                code = parts[0].strip()
                try:
                    nav = float(parts[4])
                except ValueError:
                    continue
                funds.append(
                    {
                        "scheme_code": code,
                        "name": AMFI_WATCHLIST[code],
                        "full_name": parts[3].strip(),
                        "nav": nav,
                        "date": parts[5].strip(),
                    }
                )
        return funds or None

    return _cached("amfi_navs", _fetch) or []


def fetch_fx() -> dict:
    def _fetch():
        data = _get_json("https://api.frankfurter.dev/v1/latest?base=USD&symbols=INR,EUR")
        if data and "rates" in data:
            return {"usd_inr": data["rates"].get("INR"), "usd_eur": data["rates"].get("EUR")}
        return None

    return _cached("fx", _fetch) or {}
