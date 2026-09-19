"""Datasource routing — pick the source without interrogating the user.

The rule this encodes: **ask only when asking is cheaper than being wrong.**
A question is routed on four signals, strongest first:

    resolved values   the question names "India" and exactly one source has a
                      column whose sampled values contain it. This is close to
                      proof and it is what makes routing feel effortless.
    entity terms      table and column names overlapping the question's nouns.
    domain            the datasource description and its declared subject areas.
    history           sources that previously answered questions like this one.

A clarification is raised only when the top two sources are within `margin`
*and* both are plausible in absolute terms. Two weak candidates are not an
ambiguity — they are a question this catalog cannot answer, which is a
different message to show.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_STOPWORDS = {
    "how",
    "many",
    "much",
    "what",
    "which",
    "who",
    "when",
    "where",
    "the",
    "a",
    "an",
    "of",
    "in",
    "on",
    "for",
    "by",
    "is",
    "are",
    "was",
    "were",
    "do",
    "does",
    "did",
    "show",
    "me",
    "list",
    "count",
    "total",
    "give",
    "get",
    "all",
    "and",
    "or",
    "to",
    "from",
    "with",
    "per",
    "top",
    "last",
    "this",
}


def tokenise(text: str) -> list[str]:
    words = re.split(r"[^a-z0-9]+", (text or "").lower())
    return [w for w in words if w and w not in _STOPWORDS and len(w) > 1]


@dataclass
class SourceProfile:
    """The routable summary of one datasource. Built once per crawl."""

    datasource_id: str
    dialect: str
    description: str = ""
    subject_areas: list[str] = field(default_factory=list)
    table_terms: set[str] = field(default_factory=set)
    column_terms: set[str] = field(default_factory=set)
    # lower-cased sampled value -> "schema.table.column"
    value_index: dict[str, str] = field(default_factory=dict)
    metric_names: set[str] = field(default_factory=set)
    # Business word -> catalog word ("people" -> "employee"). Without this the
    # router scores "how many people" against a table called `employee` at
    # zero, which is the single most common routing miss.
    synonyms: dict[str, str] = field(default_factory=dict)
    success_count: int = 0


@dataclass
class RouteCandidate:
    datasource_id: str
    score: float
    reasons: list[str] = field(default_factory=list)
    matched_values: dict[str, str] = field(default_factory=dict)


@dataclass
class RouteDecision:
    chosen: str | None
    candidates: list[RouteCandidate]
    needs_clarification: bool = False
    reason: str = ""

    @property
    def confident(self) -> bool:
        return self.chosen is not None and not self.needs_clarification


def score_source(question: str, profile: SourceProfile) -> RouteCandidate:
    tokens = tokenise(question)
    token_set = set(tokens)
    expanded = {profile.synonyms[t] for t in token_set if t in profile.synonyms}
    if expanded:
        token_set |= expanded
    score = 0.0
    reasons: list[str] = []
    matched: dict[str, str] = {}

    # Multi-word values ("new york", "north america") matter as much as single
    # tokens, so probe bigrams too before falling back to unigrams.
    grams = list(token_set) + [f"{a} {b}" for a, b in zip(tokens, tokens[1:])]
    for gram in grams:
        target = profile.value_index.get(gram)
        if target:
            score += 40
            matched[gram] = target
            reasons.append(f"'{gram}' is a known value in {target}")

    if expanded:
        reasons.append(f"synonyms: {', '.join(sorted(expanded))}")

    table_hits = token_set & profile.table_terms
    if table_hits:
        score += 18 * len(table_hits)
        reasons.append(f"table names match: {', '.join(sorted(table_hits))}")

    column_hits = token_set & profile.column_terms
    if column_hits:
        score += 7 * len(column_hits)
        reasons.append(f"column names match: {', '.join(sorted(list(column_hits)[:4]))}")

    metric_hits = token_set & profile.metric_names
    if metric_hits:
        score += 25 * len(metric_hits)
        reasons.append(f"certified metric: {', '.join(sorted(metric_hits))}")

    domain_words = set(tokenise(profile.description)) | {
        t for area in profile.subject_areas for t in tokenise(area)
    }
    domain_hits = token_set & domain_words
    if domain_hits:
        score += 5 * len(domain_hits)
        reasons.append(f"subject area matches: {', '.join(sorted(domain_hits))}")

    if profile.success_count:
        bump = min(20.0, 4.0 * (profile.success_count**0.5))
        score += bump
        reasons.append(f"answered {profile.success_count} similar questions before")

    return RouteCandidate(
        datasource_id=profile.datasource_id,
        score=round(score, 2),
        reasons=reasons,
        matched_values=matched,
    )


def route(
    question: str,
    profiles: list[SourceProfile],
    entitled: set[str] | None = None,
    margin: float = 20.0,
    floor: float = 25.0,
) -> RouteDecision:
    """Choose a datasource.

    `floor` is the score below which a source is not a real candidate. It is
    what separates "these two are equally good" (ask) from "neither of these
    can answer this" (say so).
    """
    usable = [p for p in profiles if entitled is None or p.datasource_id in entitled]
    if not usable:
        return RouteDecision(
            chosen=None,
            candidates=[],
            needs_clarification=False,
            reason="no datasource is available to you",
        )

    ranked = sorted(
        (score_source(question, p) for p in usable),
        key=lambda c: (-c.score, c.datasource_id),
    )
    best = ranked[0]

    if best.score < floor:
        return RouteDecision(
            chosen=None,
            candidates=ranked,
            needs_clarification=False,
            reason="no datasource looks like it covers this question",
        )

    if len(ranked) > 1 and ranked[1].score >= floor and (best.score - ranked[1].score) < margin:
        return RouteDecision(
            chosen=None,
            candidates=ranked,
            needs_clarification=True,
            reason=f"{best.datasource_id} and {ranked[1].datasource_id} both fit",
        )

    return RouteDecision(
        chosen=best.datasource_id, candidates=ranked, reason=best.reasons[0] if best.reasons else ""
    )
