"""Preprocessing — everything that can be decided without a model.

The 2-second budget allows exactly one model call, and that call is worth
spending on generating SQL, not on working out that "last quarter" means
2026-04-01..2026-06-30. Anything deterministic is decided here, where it is
right every time and costs microseconds.

Dates are the clearest case. A model resolves "last quarter" correctly most of
the time; a calendar resolves it correctly always, and the model's failure is
silent because the SQL still looks reasonable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

# ── vocabulary ───────────────────────────────────────────────────────────────

_NEGATIONS = (
    "not",
    "no",
    "never",
    "without",
    "excluding",
    "exclude",
    "except",
    "other than",
    "apart from",
    "besides",
    "minus",
    "less",
)
_COMPARATORS = {
    "more than": ">",
    "greater than": ">",
    "over": ">",
    "above": ">",
    "exceeds": ">",
    "less than": "<",
    "fewer than": "<",
    "under": "<",
    "below": "<",
    "at least": ">=",
    "no less than": ">=",
    "at most": "<=",
    "no more than": "<=",
    "equal to": "=",
    "equals": "=",
    "exactly": "=",
}
_SUPERLATIVES = {
    "top": "desc",
    "highest": "desc",
    "largest": "desc",
    "biggest": "desc",
    "most": "desc",
    "bottom": "asc",
    "lowest": "asc",
    "smallest": "asc",
    "least": "asc",
    "fewest": "asc",
}
_AGGREGATES = {
    "how many": "count",
    "count": "count",
    "number of": "count",
    "total": "sum",
    "sum": "sum",
    "revenue": "sum",
    "average": "avg",
    "avg": "avg",
    "mean": "avg",
    "median": "median",
    "max": "max",
    "maximum": "max",
    "min": "min",
    "minimum": "min",
}
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "twenty": 20,
    "thirty": 30,
    "fifty": 50,
    "hundred": 100,
    "thousand": 1000,
}

# Quoted text is a literal the user typed, not a phrase to interpret. The
# closing quote is required: an unbalanced pattern turns `"Contractor" grade`
# into two literals, the second being the word that follows the quote.
# Single quotes need word boundaries so that "don't" is not a quote opener.
_QUOTED = re.compile(
    r"\"([^\"]{1,64})\""
    "|"
    r"\u201c([^\u201d]{1,64})\u201d"
    "|"
    r"(?<![A-Za-z])'([^']{1,64})'(?![A-Za-z])"
)
_NUMERIC = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*(k|m|bn|b|%)?(?![\w.])", re.I)
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_YEAR = re.compile(r"\b(19|20)(\d{2})\b")
_QUARTER = re.compile(r"\bq([1-4])\b", re.I)


@dataclass
class DateRange:
    start: date
    end: date
    label: str
    # A relative phrase must be re-resolved on a cached plan; an absolute one
    # never changes, which is what makes it safe to key a cache on.
    relative: bool = True

    def as_params(self) -> tuple[str, str]:
        return (self.start.isoformat(), self.end.isoformat())


@dataclass
class Preprocessed:
    raw: str
    normalised: str
    tokens: list[str] = field(default_factory=list)
    dates: list[DateRange] = field(default_factory=list)
    quantities: list[tuple[float, str]] = field(default_factory=list)
    comparators: list[tuple[str, float]] = field(default_factory=list)
    literals: list[str] = field(default_factory=list)
    negated: bool = False
    aggregate: str | None = None
    sort: str | None = None
    limit: int | None = None
    question_words: list[str] = field(default_factory=list)

    @property
    def has_date(self) -> bool:
        return bool(self.dates)


def normalise(text: str) -> str:
    """Fold the typing noise that would otherwise fragment every cache key."""
    t = (text or "").strip()
    t = t.replace("’", "'").replace("‘", "'")
    t = t.replace("“", '"').replace("”", '"')
    t = re.sub(r"\s+", " ", t)
    return t


def _quarter_range(year: int, q: int) -> DateRange:
    start_month = 3 * (q - 1) + 1
    start = date(year, start_month, 1)
    end_month = start_month + 2
    last_day = (date(year + (end_month == 12), (end_month % 12) + 1, 1) - timedelta(days=1)).day
    return DateRange(start, date(year, end_month, last_day), f"Q{q} {year}", relative=False)


def _month_range(year: int, month: int) -> DateRange:
    start = date(year, month, 1)
    nxt = date(year + (month == 12), (month % 12) + 1, 1)
    return DateRange(start, nxt - timedelta(days=1), start.strftime("%B %Y"), relative=False)


def resolve_dates(text: str, today: date | None = None) -> list[DateRange]:
    """Turn every date phrase in the question into an explicit closed range.

    Returned ranges are inclusive on both ends, because that is what a BETWEEN
    predicate means and half the date bugs in text-to-SQL are an off-by-one at
    one edge of a quarter.
    """
    now = today or date.today()
    low = (text or "").lower()
    found: list[DateRange] = []

    for m in _ISO_DATE.finditer(low):
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        found.append(DateRange(d, d, d.isoformat(), relative=False))

    if "year to date" in low or "ytd" in low:
        found.append(DateRange(date(now.year, 1, 1), now, f"YTD {now.year}"))
    if "last year" in low or "previous year" in low:
        y = now.year - 1
        found.append(DateRange(date(y, 1, 1), date(y, 12, 31), str(y), relative=False))
    if "this year" in low or "current year" in low:
        found.append(DateRange(date(now.year, 1, 1), date(now.year, 12, 31), str(now.year)))
    if "last month" in low:
        first = date(now.year, now.month, 1)
        prev_end = first - timedelta(days=1)
        found.append(_month_range(prev_end.year, prev_end.month))
    if "this month" in low:
        found.append(_month_range(now.year, now.month))
    if "last quarter" in low or "previous quarter" in low:
        q = (now.month - 1) // 3 + 1
        year, q = (now.year - 1, 4) if q == 1 else (now.year, q - 1)
        found.append(_quarter_range(year, q))
    if "this quarter" in low or "current quarter" in low:
        found.append(_quarter_range(now.year, (now.month - 1) // 3 + 1))
    if "today" in low:
        found.append(DateRange(now, now, "today"))
    if "yesterday" in low:
        y = now - timedelta(days=1)
        found.append(DateRange(y, y, "yesterday"))

    m = re.search(r"last (\d+) (day|week|month|year)s?", low)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        days = {"day": 1, "week": 7, "month": 30, "year": 365}[unit] * n
        found.append(DateRange(now - timedelta(days=days), now, f"last {n} {unit}s"))

    for m in _QUARTER.finditer(low):
        q = int(m.group(1))
        ym = _YEAR.search(low)
        year = int(ym.group(0)) if ym else now.year
        found.append(_quarter_range(year, q))

    for name, month in _MONTHS.items():
        if re.search(rf"\b{name}\b", low):
            ym = _YEAR.search(low)
            found.append(_month_range(int(ym.group(0)) if ym else now.year, month))
            break

    if not found:
        for m in _YEAR.finditer(low):
            year = int(m.group(0))
            found.append(DateRange(date(year, 1, 1), date(year, 12, 31), str(year), relative=False))

    # Deduplicate while keeping the first (most specific) reading.
    seen: set[tuple[date, date]] = set()
    unique: list[DateRange] = []
    for r in found:
        key = (r.start, r.end)
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def _to_number(raw: str, suffix: str | None) -> float:
    n = float(raw.replace(",", ""))
    mult = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000, "bn": 1_000_000_000}
    if suffix and suffix.lower() in mult:
        n *= mult[suffix.lower()]
    return n


def preprocess(text: str, today: date | None = None) -> Preprocessed:
    raw = text or ""
    norm = normalise(raw)
    low = norm.lower()
    out = Preprocessed(raw=raw, normalised=norm)

    out.tokens = [t for t in re.split(r"[^a-z0-9_]+", low) if t]
    out.literals = [
        next(g for g in m.groups() if g).strip()
        for m in _QUOTED.finditer(norm)
        if any(g and g.strip() for g in m.groups())
    ]
    out.dates = resolve_dates(norm, today)

    for m in _NUMERIC.finditer(low):
        out.quantities.append((_to_number(m.group(1), m.group(2)), m.group(2) or ""))

    for phrase, op in _COMPARATORS.items():
        idx = low.find(phrase)
        if idx == -1:
            continue
        tail = low[idx + len(phrase) :]
        nm = _NUMERIC.search(tail)
        if nm:
            out.comparators.append((op, _to_number(nm.group(1), nm.group(2))))
        else:
            word = next((w for w in _NUMBER_WORDS if tail.strip().startswith(w)), None)
            if word:
                out.comparators.append((op, float(_NUMBER_WORDS[word])))

    out.negated = any(re.search(rf"\b{re.escape(n)}\b", low) for n in _NEGATIONS)

    for phrase, agg in _AGGREGATES.items():
        if phrase in low:
            out.aggregate = agg
            break

    for word, direction in _SUPERLATIVES.items():
        if re.search(rf"\b{word}\b", low):
            out.sort = direction
            m = re.search(rf"\b{word}\s+(\d+)\b", low)
            if m:
                out.limit = int(m.group(1))
            elif out.quantities and word in ("top", "bottom"):
                out.limit = int(out.quantities[0][0])
            break

    out.question_words = [
        w
        for w in ("how", "what", "which", "who", "when", "where", "why")
        if re.search(rf"\b{w}\b", low)
    ]
    return out
