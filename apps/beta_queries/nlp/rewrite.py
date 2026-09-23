"""Follow-up resolution — a slot edit, not a regenerated question.

"And in Germany?" does not need a model. It needs one literal swapped in a plan
that already exists, which is why a follow-up is the *fastest* turn in the
system rather than the slowest: ~70 ms against ~1 100 ms for a cold question.

Two outputs, and both matter:

    edits     what to change in the standing plan — this is what executes.
    question  the self-contained rewrite ("how many active employees are in
              Germany?"). Nothing runs it; it is the cache key, the audit
              record, and what the user sees if they ask what was actually
              asked.

`confident` is false when the rules could not resolve the reference. That is
the escalation signal to the fast tier — never a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from beta_queries.context.model import ConversationContext
from beta_queries.nlp.classify import Turn
from beta_queries.nlp.preprocess import Preprocessed

# Words that are never the new value in a pivot, however capitalised.
_STOP_VALUES = frozenset(
    {
        "and",
        "what",
        "about",
        "how",
        "the",
        "in",
        "for",
        "of",
        "it",
        "that",
        "this",
        "those",
        "these",
        "now",
        "then",
        "also",
        "please",
        "just",
        "only",
        "i",
        "meant",
        "mean",
        "no",
        "nope",
        "sorry",
        "actually",
        "wait",
    }
)

_VALUE_AFTER = re.compile(
    r"\b(?:in|for|at|from|to|within|across)\s+([A-Z][\w&.\-]*(?:\s+[A-Z][\w&.\-]*)*)"
)
_QUOTED_VALUE = re.compile(r"[\"']([^\"']{1,64})[\"']")
_BY_DIMENSION = re.compile(r"\b(?:by|per|for each|across)\s+([a-z][\w]*(?:\s+[a-z][\w]*)?)", re.I)
_REMOVE_TARGET = re.compile(
    r"\b(?:remove|drop|clear|without|ignore|exclude)\s+(?:the\s+)?([\w\s]{2,32}?)"
    r"(?:\s+(?:filter|chip|condition|assumption))?$",
    re.I,
)


@dataclass
class PlanEdit:
    op: str  # swap_value | add_filter | remove_filter | set_grain | set_period
    column: str | None = None
    value: Any = None
    label: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"op": self.op, "column": self.column, "value": self.value, "label": self.label}


@dataclass
class Rewrite:
    question: str
    edits: list[PlanEdit] = field(default_factory=list)
    confident: bool = True
    reason: str = ""

    @property
    def is_slot_edit(self) -> bool:
        """True when the standing plan can be re-bound instead of regenerated."""
        return (
            self.confident
            and bool(self.edits)
            and all(e.op in ("swap_value", "set_period") for e in self.edits)
        )


# "add a filter for X", "just X", "only X" — the imperative wrapper people put
# around a value. Stripped before extraction, or the verb becomes the value.
_FILTER_LEAD = re.compile(
    r"^\s*(?:please\s+)?(?:can you\s+)?"
    r"(?:(?:add|apply|include|set|put|restrict|limit|narrow)\b\s*"
    r"(?:a|an|the)?\s*(?:filter|condition|clause)?\s*(?:for|on|by|to|where)?"
    r"|only|just|filter(?:\s+(?:for|on|by|to|where))?)\s+",
    re.I,
)
# "active ones", "active only" — filler that is not part of the value.
_VALUE_TAIL = re.compile(r"\s*\b(?:ones?|only|please)\b\s*$", re.I)


def _strip_command(text: str) -> str:
    """Peel the imperative off a narrowing phrase, leaving the value itself."""
    out = _FILTER_LEAD.sub("", text.strip(), count=1)
    out = _VALUE_TAIL.sub("", out).strip("?,.! ")
    return out or text.strip()


def _candidate_value(text: str) -> str | None:
    text = _strip_command(text)
    quoted = _QUOTED_VALUE.search(text)
    if quoted:
        return quoted.group(1).strip()
    m = _VALUE_AFTER.search(text)
    if m:
        return m.group(1).strip()
    # A bare capitalised phrase — "Germany?" — with the question mark stripped.
    words = [w.strip("?,.!") for w in text.split()]
    caps = [w for w in words if w[:1].isupper() and w.lower() not in _STOP_VALUES]
    if caps:
        return " ".join(caps)
    # Lower-cased single token after a leading conjunction: "and germany?"
    tail = re.sub(r"^(and|also|what about|how about|but|plus)\s+", "", text.strip(), flags=re.I)
    tail = re.sub(r"^(in|for|at)\s+", "", tail, flags=re.I).strip("?,.! ")
    if tail and len(tail.split()) <= 3 and tail.lower() not in _STOP_VALUES:
        return tail
    return None


def _pivot_column(ctx: ConversationContext) -> str | None:
    """The column a bare value most likely replaces: the last one the user set."""
    user_set = [c for c in ctx.filters if c.source == "question"]
    if user_set:
        return max(user_set, key=lambda c: c.turn).column
    return None


_UNSET = object()


def _describe(ctx: ConversationContext, overrides: dict[str, Any] | None = None) -> str:
    """Render the context as a self-contained English question.

    An override of `None` means "drop this", which is different from an absent
    key meaning "keep whatever the context has" — the distinction is the whole
    of what `rollup` and `undo` do.
    """
    over = overrides or {}

    def pick(key: str, current: Any) -> Any:
        return over[key] if key in over else current

    metric = pick("metric", ctx.metric) or "records"
    grain = pick("grain", ctx.grain)
    bits = [f"how many {metric}"]
    if grain:
        bits = [f"{metric} by {grain}"]
    clauses: list[str] = []
    for chip in ctx.filters:
        value = over.get(chip.column) if chip.column in over else chip.value
        if value is None:
            continue
        clauses.append(f"{chip.column} = {value}")
    period = over.get("period") or ctx.period
    if period:
        clauses.append(f"period {period}")
    tail = " where " + " and ".join(clauses) if clauses else ""
    return (" ".join(bits) + tail).strip()


def rewrite(
    text: str,
    turn: Turn,
    ctx: ConversationContext,
    pre: Preprocessed | None = None,
) -> Rewrite:
    """Resolve a follow-up against the standing context."""
    raw = (text or "").strip()

    if not turn.is_followup:
        return Rewrite(question=raw, confident=True, reason="not a follow-up")

    if turn.scenario == "repeat":
        return Rewrite(
            question=_describe(ctx), edits=[], confident=True, reason="re-runs the standing plan"
        )

    if turn.scenario == "pivot":
        # A resolved date is a period change, never a value swap. The
        # preprocessor already turned "last year" into a range; without this
        # it lands in the last filtered column as the literal "last year".
        if pre is not None and pre.dates:
            span = pre.dates[0]
            label = getattr(span, "label", "") or f"{span.start} to {span.end}"
            return Rewrite(
                question=_describe(ctx, {"period": label}),
                edits=[PlanEdit("set_period", value=label, label=f"period {label}")],
                reason=f"period → {label}",
            )
        value = _candidate_value(raw)
        column = _pivot_column(ctx)
        if value and column:
            return Rewrite(
                question=_describe(ctx, {column: value}),
                edits=[
                    PlanEdit("swap_value", column=column, value=value, label=f"{column} = {value}")
                ],
                reason=f"swapped {column}",
            )
        if value and not column:
            # We know what changed but not which slot it fills. The model is
            # cheaper than a wrong column.
            return Rewrite(
                question=f"{_describe(ctx)} — now for {value}",
                confident=False,
                reason="no standing filter to swap",
            )
        return Rewrite(question=raw, confident=False, reason="no value found to swap")

    if turn.scenario == "drill":
        m = _BY_DIMENSION.search(raw)
        if m:
            dim = m.group(1).strip().rstrip("s") if m.group(1).endswith("s") else m.group(1)
            dim = dim.strip()
            return Rewrite(
                question=_describe(ctx, {"grain": dim}),
                edits=[PlanEdit("set_grain", value=dim, label=f"by {dim}")],
                reason=f"grain → {dim}",
            )
        return Rewrite(question=raw, confident=False, reason="no dimension named")

    if turn.scenario == "rollup":
        return Rewrite(
            question=_describe(ctx, {"grain": None}),
            edits=[PlanEdit("set_grain", value=None, label="overall")],
            reason="grain removed",
        )

    if turn.scenario == "undo":
        m = _REMOVE_TARGET.search(raw)
        target = m.group(1).strip().lower() if m else ""
        chip = next(
            (
                c
                for c in ctx.filters
                if target and (target in c.label.lower() or target in (c.column or "").lower())
            ),
            None,
        )
        if chip is None and ctx.filters:
            removable = [c for c in ctx.filters if c.removable]
            chip = max(removable, key=lambda c: c.turn) if removable else None
        if chip is None:
            return Rewrite(question=raw, confident=False, reason="nothing to remove")
        if not chip.removable:
            return Rewrite(
                question=raw,
                confident=False,
                reason=f"{chip.label} is a policy filter and cannot be removed",
            )
        return Rewrite(
            question=_describe(ctx, {chip.column: None}),
            edits=[PlanEdit("remove_filter", column=chip.column, label=chip.label)],
            reason=f"removed {chip.label}",
        )

    if turn.scenario == "refine":
        value = _candidate_value(raw)
        if value:
            return Rewrite(
                question=f"{_describe(ctx)} and {value}",
                edits=[PlanEdit("add_filter", value=value, label=str(value))],
                confident=False,  # which column it constrains is the model's call
                reason="narrowing term found, column unresolved",
            )
        return Rewrite(question=raw, confident=False, reason="no narrowing term found")

    if turn.scenario == "amend":
        # A correction replaces the *previous* turn rather than adding to it,
        # so the standing plan is rebuilt from the turn before last.
        corrected = re.sub(r"^(no|nope|sorry|actually|wait)\b[, ]*", "", raw, flags=re.I)
        corrected = re.sub(r"^(i\s+)?(mean[t]?|said)\b[, ]*", "", corrected.strip(), flags=re.I)
        value = _candidate_value(corrected)
        column = _pivot_column(ctx)
        if value and column:
            return Rewrite(
                question=_describe(ctx, {column: value}),
                edits=[
                    PlanEdit(
                        "swap_value",
                        column=column,
                        value=value,
                        label=f"{column} = {value} (corrected)",
                    )
                ],
                reason="correction applied to the last turn",
            )
        return Rewrite(question=raw, confident=False, reason="correction target unclear")

    if turn.scenario in ("trend", "rank", "compare"):
        if pre and pre.dates:
            period = pre.dates[0]
            return Rewrite(
                question=f"{_describe(ctx)} for {period.label}",
                edits=[PlanEdit("set_period", value=period.as_params(), label=period.label)],
                confident=turn.scenario != "compare",
                reason=f"period → {period.label}",
            )
        return Rewrite(question=raw, confident=False, reason=f"{turn.scenario} needs a plan")

    return Rewrite(question=raw, confident=False, reason="unhandled follow-up")
