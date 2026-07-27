"""Finance vocabulary aliasing for the zero-dependency embedder.

The hashing embedder is lexical: "what is my income" scores ~0 against
"take_home=180000" because the two share no tokens. A local transformer would
bridge that gap semantically; when one is not installed, this table bridges the
gap for the terms that actually matter in personal finance.

Applied at *query* time only, so stored vectors stay pure and a later switch to
a real embedding model needs no re-indexing. The JavaScript SDK carries the
identical table, so recall ranks the same in the browser.

Keep it small and unambiguous: these are synonyms, not a thesaurus.
"""

from __future__ import annotations

FINANCE_ALIASES: dict[str, list[str]] = {
    "income": ["take_home", "salary", "earn", "earnings", "pay", "ctc"],
    "salary": ["take_home", "income", "pay"],
    "earn": ["income", "take_home", "salary"],
    "take_home": ["income", "salary", "pay"],
    "debt": ["loan", "emi", "borrowed", "credit", "card"],
    "loan": ["debt", "emi", "mortgage", "borrowed"],
    "emi": ["loan", "debt", "instalment", "installment"],
    "house": ["home", "property", "flat", "apartment", "mortgage"],
    "property": ["house", "home", "flat", "real", "estate"],
    "sip": ["mutual", "fund", "systematic", "investment"],
    "fund": ["sip", "mutual", "scheme", "nav"],
    "invest": ["investment", "sip", "equity", "portfolio"],
    "gold": ["bullion", "goldbees", "metal"],
    "silver": ["silverbees", "metal"],
    "crypto": ["bitcoin", "btc", "vda", "ethereum"],
    "bitcoin": ["crypto", "btc", "vda"],
    "tax": ["taxes", "ltcg", "stcg", "80c", "regime", "tds"],
    "taxes": ["tax", "ltcg", "stcg", "80c", "regime"],
    "gains": ["ltcg", "stcg", "capital", "profit"],
    "retire": ["retirement", "nps", "epf", "pension"],
    "emergency": ["buffer", "reserve", "rainy", "fund"],
    "save": ["saving", "savings", "surplus"],
    "goal": ["target", "plan", "objective"],
    "risk": ["tolerance", "appetite", "volatility"],
    "insurance": ["term", "health", "cover", "premium"],
}


def expand(tokens: list[str]) -> list[str]:
    """Return the query tokens plus their finance aliases, de-duplicated."""
    out = list(tokens)
    seen = set(tokens)
    for token in tokens:
        for alias in FINANCE_ALIASES.get(token, ()):
            if alias not in seen:
                seen.add(alias)
                out.append(alias)
    return out
