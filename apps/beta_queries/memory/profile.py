"""User profile memory — so the same person is never asked the same thing twice.

Two people type "how many accounts" and mean different tables, because they
have different access and different jobs. The system cannot know that from the
question. It can know it from the last time it asked.

So every clarification a user answers is remembered against that user, and the
next time the same ambiguity arises it resolves silently. This is the single
change that moves the experience from "it keeps interrogating me" to "it knows
what I mean" — and it costs one Redis read.

Storage notes that matter:

    the key is a hash     the raw address is never written to Redis. It is the
                          user's identity, it is PII, and the lookup works
                          identically against a digest.
    the TTL slides        seven days from last use, not from creation. Someone
                          who asks every Monday never loses their profile;
                          someone who asked once in March does.
    it is a preference,   nothing here grants access or changes a filter on its
    never a permission    own. Entitlements are resolved per request, always.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

DEFAULT_TTL_SECONDS = 7 * 24 * 3600
MAX_RESOLUTIONS = 200
MAX_GLOSSARY = 100


class KV(Protocol):
    """The slice of Redis this needs. A dict satisfies it in tests."""

    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str, ex: int | None = None) -> Any: ...
    def delete(self, key: str) -> Any: ...


class DictKV:
    """In-memory KV with expiry, for tests and for running without Redis."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float | None]] = {}

    def get(self, key: str) -> str | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        value, expires = entry
        if expires is not None and expires <= time.time():
            del self._data[key]
            return None
        return value

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._data[key] = (value, time.time() + ex if ex else None)

    def delete(self, key: str) -> None:
        self._data.pop(key, None)


def user_key(identity: str, prefix: str = "bq:profile") -> str:
    """Hash the identity so the raw address never reaches the store."""
    digest = hashlib.sha256(identity.strip().lower().encode()).hexdigest()[:32]
    return f"{prefix}:{digest}"


@dataclass
class Profile:
    """What we have learned about how one person asks questions."""

    # datasource id -> how many answered questions came from it
    sources: dict[str, int] = field(default_factory=dict)
    # ambiguity key ("accounts") -> what this user meant ("sales.dbo.customer")
    resolutions: dict[str, str] = field(default_factory=dict)
    # the user's own words -> catalog words ("bookings" -> "order")
    glossary: dict[str, str] = field(default_factory=dict)
    # default filters this user habitually removes, so stop applying them
    dismissed_filters: dict[str, int] = field(default_factory=dict)
    # the grain they usually want ("by month", "by region")
    habits: dict[str, int] = field(default_factory=dict)
    questions: int = 0
    updated_at: float = 0.0

    # ── learning ────────────────────────────────────────────────────────────

    def record_answer(self, datasource: str, grain: str | None = None) -> None:
        self.sources[datasource] = self.sources.get(datasource, 0) + 1
        if grain:
            self.habits[grain] = self.habits.get(grain, 0) + 1
        self.questions += 1

    def record_resolution(self, term: str, chose: str) -> None:
        """Remember the answer to a clarification. This is the valuable one."""
        self.resolutions[term.strip().lower()] = chose
        self._trim(self.resolutions, MAX_RESOLUTIONS)

    def record_glossary(self, word: str, means: str) -> None:
        self.glossary[word.strip().lower()] = means
        self._trim(self.glossary, MAX_GLOSSARY)

    def record_dismissal(self, filter_id: str) -> None:
        self.dismissed_filters[filter_id] = self.dismissed_filters.get(filter_id, 0) + 1

    # ── using it ────────────────────────────────────────────────────────────

    def preferred_source(self, among: list[str] | None = None) -> str | None:
        """Which source to lean toward when two score within the margin.

        Only a tie-break. A source this user has never used still wins on a
        clear score, and a source they use daily never overrides entitlements.
        """
        pool = {k: v for k, v in self.sources.items() if among is None or k in among}
        if not pool:
            return None
        return max(pool.items(), key=lambda kv: kv[1])[0]

    def resolved(self, term: str) -> str | None:
        return self.resolutions.get(term.strip().lower())

    def should_skip_filter(self, filter_id: str, threshold: int = 2) -> bool:
        """Stop re-applying a default this person has removed repeatedly."""
        return self.dismissed_filters.get(filter_id, 0) >= threshold

    def prompt_hints(self, limit: int = 6) -> dict[str, Any]:
        """The compact slice that goes into the prompt. Bounded on purpose."""
        top = sorted(self.sources.items(), key=lambda kv: -kv[1])[:3]
        return {
            "usual_sources": [s for s, _ in top],
            "glossary": dict(list(self.glossary.items())[:limit]),
            "known_choices": dict(list(self.resolutions.items())[:limit]),
        }

    @staticmethod
    def _trim(mapping: dict[str, str], bound: int) -> None:
        while len(mapping) > bound:
            mapping.pop(next(iter(mapping)))


class ProfileStore:
    """Load, mutate, save — with the TTL refreshed on every write."""

    def __init__(self, kv: KV, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self.kv = kv
        self.ttl = ttl_seconds

    def load(self, identity: str) -> Profile:
        raw = self.kv.get(user_key(identity))
        if not raw:
            return Profile()
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            # A corrupt profile is a preference cache, not a system of record:
            # discard it and start again rather than failing the question.
            return Profile()
        known = {f for f in Profile.__dataclass_fields__}
        return Profile(**{k: v for k, v in data.items() if k in known})

    def save(self, identity: str, profile: Profile) -> None:
        profile.updated_at = time.time()
        self.kv.set(user_key(identity), json.dumps(asdict(profile)), ex=self.ttl)

    def forget(self, identity: str) -> None:
        """Honour "forget me". One key, one delete, nothing left behind."""
        self.kv.delete(user_key(identity))

    def update(self, identity: str, **changes: Mapping[str, Any]) -> Profile:
        profile = self.load(identity)
        for name, value in changes.items():
            method = getattr(profile, f"record_{name}", None)
            if method and isinstance(value, dict):
                method(**value)
        self.save(identity, profile)
        return profile
