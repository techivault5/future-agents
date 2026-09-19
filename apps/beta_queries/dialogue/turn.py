"""One turn, end to end — the entry point the orchestrator calls first.

Classify, resolve the reference, decide the response shape. Everything here is
deterministic and costs microseconds, which is what makes it safe to run before
the 2-second budget starts: by the time anything expensive happens, we already
know whether this turn needs the model at all.

Most turns do not. A greeting, a thank-you, a refusal, a pivot and a meta
question are all answered from this layer, and that is where the session p50
of ~150 ms comes from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from beta_queries.context.model import ContextDelta, ConversationContext, diff
from beta_queries.dialogue.policy import DialoguePolicy, Reply
from beta_queries.nlp.classify import Turn, classify
from beta_queries.nlp.preprocess import Preprocessed, preprocess
from beta_queries.nlp.rewrite import Rewrite, rewrite


@dataclass
class TurnOutcome:
    turn: Turn
    reply: Reply
    pre: Preprocessed
    rewritten: Rewrite | None = None
    delta: ContextDelta = field(default_factory=ContextDelta)
    facts: dict[str, Any] = field(default_factory=dict)

    @property
    def scenario(self) -> str:
        return self.turn.scenario

    @property
    def needs_model(self) -> bool:
        """A model call is needed to plan, or to resolve a reference we could not."""
        if self.reply.calls_model:
            return True
        return bool(self.rewritten and not self.rewritten.confident)

    @property
    def question(self) -> str:
        """The self-contained question — what gets cached, logged and shown."""
        if self.rewritten and self.rewritten.question:
            return self.rewritten.question
        return self.pre.normalised

    def as_event(self) -> dict[str, Any]:
        event = self.reply.as_event()
        event["question"] = self.question
        event["needs_model"] = self.needs_model
        if self.rewritten and self.rewritten.edits:
            event["edits"] = [e.as_dict() for e in self.rewritten.edits]
        if not self.delta.empty:
            event["context"] = self.delta.as_events()
        return event


def handle_turn(
    text: str,
    ctx: ConversationContext,
    policy: DialoguePolicy | None = None,
    facts: dict[str, Any] | None = None,
    today: date | None = None,
) -> TurnOutcome:
    """Classify, resolve and decide — without touching a store or a model."""
    pol = policy or DialoguePolicy()
    before = ctx.copy()

    pre = preprocess(text, today)
    # "Something to refer back to" is a standing plan or a standing filter —
    # not merely a previous message. After a reset, "and those?" has nothing to
    # attach to and must say so rather than escalating to the model.
    has_context = bool(ctx.last_plan_id or ctx.filters or ctx.metric or ctx.grain)
    turn = classify(pre.normalised, has_context=has_context, has_last_plan=bool(ctx.last_plan_id))

    resolved: Rewrite | None = None
    if turn.is_followup:
        resolved = rewrite(pre.normalised, turn, ctx, pre)

    merged: dict[str, Any] = dict(facts or {})
    merged.setdefault("n", len(turn.parts) or None)
    merged.setdefault("filters", ", ".join(c.label for c in ctx.filters) or None)
    merged.setdefault("kept", sum(1 for c in ctx.filters if c.pinned))
    if turn.parts:
        merged.setdefault("parts", turn.parts)
    if resolved and resolved.edits:
        merged.setdefault("edit", resolved.edits[0].label)
    merged = {k: v for k, v in merged.items() if v is not None}

    reply = pol.respond(turn.scenario, merged)

    # Session commands act on the context here, because their whole effect is
    # on the context — there is nothing downstream to do them.
    if turn.scenario == "reset":
        ctx.reset(keep_pinned=True)
    ctx.record_turn(pre.normalised, turn.scenario)

    return TurnOutcome(
        turn=turn, reply=reply, pre=pre, rewritten=resolved, delta=diff(before, ctx), facts=merged
    )
