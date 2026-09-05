"""Shared vocabulary for memory: tokens, stems, fingerprints, normalisation.

Retrieval only works if both sides speak the same dialect, so the stemmer here
is the one the repo index already uses. Fingerprints are how memory recognises
"the same thing again" — the same question asked twice, the same pitfall hit in
two runs, the same ticket re-filed next quarter.
"""

from __future__ import annotations

import hashlib
import re

from future_agents.sdd.knowledge.index import stem

_STOP = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "for",
    "in",
    "on",
    "at",
    "with",
    "is",
    "are",
    "be",
    "that",
    "this",
    "it",
    "as",
    "by",
    "from",
    "we",
    "our",
    "should",
    "must",
    "will",
    "can",
    "what",
    "which",
    "how",
    "when",
    "where",
    "who",
    "does",
    "do",
    "did",
    "you",
    "your",
}


def tokens(text: str) -> set[str]:
    """Stemmed content words. Deliberately identical to the repo index's."""
    return {
        stem(word)
        for word in re.findall(r"[a-z][a-z0-9_-]{2,}", (text or "").lower())
        if word not in _STOP
    }


def fingerprint(*parts: str) -> str:
    """A stable id for "the same thing again".

    Built from the sorted token *set*, so word order, punctuation and filler
    words cannot make two identical questions look different. Unlike retrieval,
    it keeps numbers: "migration v2" and "migration v3" are two things.
    """
    bag: set[str] = set()
    for part in parts:
        bag |= {
            stem(word) if word[0].isalpha() else word
            for word in re.findall(r"[a-z0-9][a-z0-9_.-]*", (part or "").lower())
            if word not in _STOP and (len(word) > 2 or word[0].isdigit())
        }
    if not bag:
        return ""
    return hashlib.sha256(" ".join(sorted(bag)).encode("utf-8")).hexdigest()[:16]


def similarity(left: set[str], right: set[str]) -> float:
    """Coverage of the *query* side, not Jaccard.

    Jaccard punishes a long, rich case for being long. What matters is how much
    of what we are asking about the case actually covers.
    """
    if not left or not right:
        return 0.0
    return len(left & right) / len(left)


def slug(text: str, *, limit: int = 48) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:limit] or "case"


def first_line(text: str, *, limit: int = 160) -> str:
    stripped = (text or "").strip()
    return stripped.splitlines()[0][:limit] if stripped else ""


def condense(text: str, *, limit: int = 400) -> str:
    """One-line, length-capped. Memory stores lessons, not transcripts."""
    flat = re.sub(r"\s+", " ", (text or "").strip())
    return flat[: limit - 1] + "…" if len(flat) > limit else flat
