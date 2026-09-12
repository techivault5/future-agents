"""Canonical forms, and the words that reliably mean two things.

Deliberately small and explicit. A large learned vocabulary would be more
impressive and less trustworthy: every entry here is one a reviewer can argue
with, which is the property that matters when the output steers a build.
"""

from __future__ import annotations

import re

#: Terms whose plural or participle forms should fold into one concept.
_IRREGULAR = {
    "people": "person",
    "data": "data",
    "criteria": "criterion",
    "indices": "index",
    "analyses": "analysis",
}

#: Words that regularly mean two different things in the same sentence, with the
#: readings a human has to choose between. Presence alone is not a problem —
#: only presence without a criterion that settles it.
AMBIGUOUS_TERMS: dict[str, tuple[str, ...]] = {
    "refund": ("a reversal of the original payment", "a credit issued against a future one"),
    "user": ("the end customer", "the operator of the internal tool"),
    "account": ("the customer's billing account", "the login identity"),
    "report": ("a rendered document", "a queryable dataset"),
    "sync": ("one-way copy", "two-way reconciliation"),
    "archive": ("hidden from the UI", "moved out of the primary store"),
    "delete": ("soft delete, recoverable", "hard delete, unrecoverable"),
    "daily": ("once per calendar day", "every 24 hours from the last run"),
    "real-time": ("sub-second", "as soon as the next batch runs"),
    "customer": ("the paying organisation", "an individual using the product"),
    "order": ("the purchase record", "the sequence of events"),
    "balance": ("the current amount", "the reconciled amount"),
}

#: Domain of the ask, inferred from the words in it. Used to name the model and
#: to pick which repository conventions are worth consulting first.
DOMAIN_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("billing", ("refund", "invoice", "payment", "charge", "ledger", "subscription", "price")),
    ("identity", ("login", "auth", "sso", "permission", "role", "session", "token")),
    ("reporting", ("report", "dashboard", "metric", "export", "analytics", "chart")),
    ("data", ("pipeline", "warehouse", "etl", "ingest", "schema", "table", "dataset")),
    ("messaging", ("notify", "email", "alert", "message", "webhook", "queue")),
    ("catalogue", ("product", "inventory", "sku", "catalog", "listing")),
    ("support", ("ticket", "case", "agent", "customer service", "helpdesk")),
    ("platform", ("deploy", "infrastructure", "cluster", "terraform", "container", "ci")),
)

#: Verbs that carry a system action. The list is short on purpose: a verb that
#: is not here becomes a generic capability rather than a wrong specific one.
ACTION_VERBS: tuple[str, ...] = (
    "add",
    "create",
    "record",
    "issue",
    "refund",
    "reconcile",
    "export",
    "import",
    "sync",
    "notify",
    "alert",
    "send",
    "show",
    "display",
    "list",
    "search",
    "filter",
    "approve",
    "reject",
    "cancel",
    "schedule",
    "retry",
    "archive",
    "delete",
    "update",
    "migrate",
    "validate",
    "calculate",
    "aggregate",
    "publish",
    "track",
    "measure",
    "flag",
    "block",
    "allow",
    "generate",
    "refresh",
)

#: People and teams an ask is usually written on behalf of.
ACTOR_WORDS: tuple[str, ...] = (
    "support",
    "finance",
    "sales",
    "marketing",
    "ops",
    "operations",
    "admin",
    "administrator",
    "customer",
    "user",
    "engineer",
    "analyst",
    "manager",
    "auditor",
    "on-call",
    "scheduler",
    "system",
)

#: Words that are grammar, not domain. Without this, "able", "kept" and
#: "waiting" become entities and the glossary stops being worth reading.
_NON_CONCEPT = {
    "able",
    "not",
    "more",
    "less",
    "only",
    "every",
    "each",
    "both",
    "all",
    "any",
    "new",
    "old",
    "same",
    "other",
    "need",
    "want",
    "make",
    "makes",
    "made",
    "get",
    "gets",
    "put",
    "one",
    "two",
    "way",
    "thing",
    "things",
    "part",
    "kept",
    "keep",
    "still",
    "just",
    "also",
    "etc",
    "via",
    "per",
    "such",
    "there",
    "here",
    "does",
    "done",
    "did",
    "has",
    "have",
    "had",
}


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
    "must",
    "should",
    "will",
    "can",
    "so",
    "without",
    "their",
    "them",
    "they",
    "into",
    "when",
    "then",
    "given",
}


def singular(word: str) -> str:
    """Fold a plural into its singular. Crude, symmetric, and reviewable."""
    low = word.lower()
    if low in _IRREGULAR:
        return _IRREGULAR[low]
    if len(low) > 4 and low.endswith("ies"):
        return low[:-3] + "y"
    if len(low) > 4 and low.endswith("ses"):
        return low[:-2]
    if len(low) > 3 and low.endswith("s") and not low.endswith("ss"):
        return low[:-1]
    return low


def canonicalise(term: str) -> str:
    """The form every downstream artifact uses for this term."""
    cleaned = re.sub(r"[^a-z0-9 _-]+", "", (term or "").lower()).strip()
    return " ".join(singular(word) for word in cleaned.split() if word not in _STOP) or cleaned


def content_words(text: str) -> list[str]:
    """Words worth reasoning about, in the order they appeared."""
    return [
        word
        for word in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", (text or "").lower())
        if word not in _STOP and word not in _NON_CONCEPT
    ]


def is_modifier(word: str) -> bool:
    """A participle or adjective is describing a thing, not naming one.

    "recorded", "paid" and "waiting" are how the ask qualifies a concept; taking
    them for concepts of their own is how a glossary fills with words nobody
    would look up.
    """
    low = word.lower()
    if low in ACTION_VERBS or singular(low) in ACTION_VERBS:
        return False
    return low.endswith(("ed", "ing")) and len(low) > 4


def domain_of(text: str) -> str:
    """Which domain the ask lives in, by weight of evidence, or "general"."""
    low = (text or "").lower()
    scores = {
        name: sum(1 for keyword in keywords if keyword in low) for name, keywords in DOMAIN_HINTS
    }
    best = max(scores, key=lambda name: scores[name]) if scores else ""
    return best if best and scores[best] else "general"
