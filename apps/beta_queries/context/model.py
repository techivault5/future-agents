"""The conversation context — a typed object, not a replayed transcript.

A transcript grows without bound, drifts as it grows, cannot be shown to the
user, and cannot be diffed. This object is bounded (12 entities, 8 filters,
5 turns), which means a 30-turn session costs the same prompt budget as a
3-turn one, and the right-hand panel can render exactly what the model was
given.

Two rules make it behave:

    pinning     a chip the user pinned survives a topic change; everything
                else is evicted oldest-first once a bound is hit.
    provenance  every entry records the turn that introduced it, so "why is
                this filter here?" is answerable without a model.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any, Literal

MAX_ENTITIES = 12
MAX_FILTERS = 8
MAX_TURNS = 5

FilterSource = Literal["question", "catalog_default", "policy", "user_pinned"]


@dataclass
class Entity:
    """Something the conversation is about: a table, a metric, a dimension."""

    name: str
    kind: str  # table | column | metric | value | datasource
    turn: int = 0
    pinned: bool = False


@dataclass
class FilterChip:
    """A predicate in force, rendered in the panel and removable by clicking.

    `removable` is False only for policy filters: a row-level security
    predicate is not the user's to dismiss, and showing it as dismissible
    teaches people the wrong thing about the system.
    """

    id: str
    label: str
    column: str | None = None
    value: Any = None
    source: FilterSource = "question"
    turn: int = 0
    pinned: bool = False
    removable: bool = True
    rationale: str = ""

    @property
    def auto(self) -> bool:
        return self.source in ("catalog_default", "policy")


@dataclass
class TurnRecord:
    n: int
    question: str
    scenario: str
    answered: bool = False
    plan_id: str | None = None
    ms: int | None = None
    rows: int | None = None
    error: str | None = None


@dataclass
class ConversationContext:
    session_id: str = ""
    datasource: str | None = None
    grain: str | None = None
    metric: str | None = None
    entities: list[Entity] = field(default_factory=list)
    filters: list[FilterChip] = field(default_factory=list)
    period: str | None = None
    period_range: tuple[str, str] | None = None
    turns: list[TurnRecord] = field(default_factory=list)
    last_plan_id: str | None = None
    last_sql: str | None = None
    last_answer: str | None = None
    turn_no: int = 0

    # ── mutation ────────────────────────────────────────────────────────────

    def add_entity(self, name: str, kind: str, pinned: bool = False) -> None:
        existing = next((e for e in self.entities if e.name == name and e.kind == kind), None)
        if existing:
            existing.turn = self.turn_no
            existing.pinned = existing.pinned or pinned
            return
        self.entities.append(Entity(name=name, kind=kind, turn=self.turn_no, pinned=pinned))
        self._evict(self.entities, MAX_ENTITIES)

    def add_filter(self, chip: FilterChip) -> None:
        chip.turn = chip.turn or self.turn_no
        for i, existing in enumerate(self.filters):
            # A new value for the same column replaces it — that is what a
            # pivot is. Two filters on one column would silently AND together
            # and return nothing.
            if existing.column and existing.column == chip.column:
                chip.pinned = chip.pinned or existing.pinned
                self.filters[i] = chip
                return
            if existing.id == chip.id:
                self.filters[i] = chip
                return
        self.filters.append(chip)
        self._evict(self.filters, MAX_FILTERS)

    def remove_filter(self, chip_id: str) -> bool:
        for i, chip in enumerate(self.filters):
            if chip.id == chip_id:
                if not chip.removable:
                    return False
                del self.filters[i]
                return True
        return False

    def pin(self, chip_id: str, pinned: bool = True) -> bool:
        for chip in self.filters:
            if chip.id == chip_id:
                chip.pinned = pinned
                return True
        for entity in self.entities:
            if entity.name == chip_id:
                entity.pinned = pinned
                return True
        return False

    def record_turn(self, question: str, scenario: str, **kw: Any) -> TurnRecord:
        self.turn_no += 1
        rec = TurnRecord(n=self.turn_no, question=question, scenario=scenario, **kw)
        self.turns.append(rec)
        if len(self.turns) > MAX_TURNS:
            del self.turns[0 : len(self.turns) - MAX_TURNS]
        return rec

    def reset(self, keep_pinned: bool = True) -> None:
        """Start over. Pinned chips survive unless the user says otherwise."""
        self.filters = [c for c in self.filters if c.pinned] if keep_pinned else []
        self.entities = [e for e in self.entities if e.pinned] if keep_pinned else []
        self.grain = self.metric = self.period = None
        self.period_range = None
        self.last_plan_id = self.last_sql = self.last_answer = None
        self.turns = []

    @staticmethod
    def _evict(items: list[Any], bound: int) -> None:
        while len(items) > bound:
            victim = next((i for i, it in enumerate(items) if not it.pinned), None)
            if victim is None:  # everything pinned — drop the oldest anyway
                victim = 0
            del items[victim]

    # ── projection ──────────────────────────────────────────────────────────

    def to_prompt(self) -> dict[str, Any]:
        """The exact object handed to the model. The panel renders this too."""
        return {
            "datasource": self.datasource,
            "grain": self.grain,
            "metric": self.metric,
            "period": self.period,
            "entities": [{"name": e.name, "kind": e.kind} for e in self.entities],
            "filters": [
                {"label": c.label, "column": c.column, "value": c.value, "source": c.source}
                for c in self.filters
            ],
            "recent": [{"q": t.question, "scenario": t.scenario} for t in self.turns[-3:]],
        }

    def to_panel(self) -> dict[str, Any]:
        return {
            "source": self.datasource,
            "grain": self.grain,
            "metric": self.metric,
            "period": self.period,
            "filters": [
                {
                    "id": c.id,
                    "label": c.label,
                    "auto": c.auto,
                    "pinned": c.pinned,
                    "removable": c.removable,
                    "rationale": c.rationale,
                }
                for c in self.filters
            ],
            "queries": [
                {"n": t.n, "q": t.question, "ms": t.ms, "scenario": t.scenario}
                for t in reversed(self.turns)
            ],
        }

    def fingerprint(self) -> str:
        """Cache key for "this context, this question" — order-independent."""
        payload = {
            "ds": self.datasource,
            "grain": self.grain,
            "metric": self.metric,
            "period": self.period,
            "filters": sorted(f"{c.column}={c.value}" for c in self.filters),
        }
        blob = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def copy(self) -> ConversationContext:
        return replace(
            self,
            entities=[replace(e) for e in self.entities],
            filters=[replace(c) for c in self.filters],
            turns=[replace(t) for t in self.turns],
        )


@dataclass
class ContextDelta:
    """What changed this turn — the panel animates this, not a full re-render."""

    added_filters: list[FilterChip] = field(default_factory=list)
    removed_filters: list[FilterChip] = field(default_factory=list)
    changed: dict[str, tuple[Any, Any]] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not (self.added_filters or self.removed_filters or self.changed)

    def as_events(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for chip in self.added_filters:
            events.append(
                {
                    "op": "add_filter",
                    "id": chip.id,
                    "label": chip.label,
                    "auto": chip.auto,
                    "rationale": chip.rationale,
                }
            )
        for chip in self.removed_filters:
            events.append({"op": "remove_filter", "id": chip.id})
        for key, (before, after) in self.changed.items():
            events.append({"op": "set", "key": key, "from": before, "to": after})
        return events


def diff(before: ConversationContext, after: ConversationContext) -> ContextDelta:
    delta = ContextDelta()
    before_ids = {c.id: c for c in before.filters}
    after_ids = {c.id: c for c in after.filters}
    delta.added_filters = [c for cid, c in after_ids.items() if cid not in before_ids]
    delta.removed_filters = [c for cid, c in before_ids.items() if cid not in after_ids]
    for key in ("datasource", "grain", "metric", "period"):
        b, a = getattr(before, key), getattr(after, key)
        if b != a:
            delta.changed[key] = (b, a)
    return delta
