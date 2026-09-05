"""Semantic memory — pitfalls that recurred, promoted into rules.

A single case is an anecdote. The same pitfall in two independent cases is a
property of the codebase, and that is what the planner should be told about.

Three mechanics keep this honest:

* **Promotion** — a pitfall is only a lesson once it has been hit in
  `promote_after` distinct cases. Nothing gets promoted on one bad run.
* **Decay** — confidence halves every `half_life_days` without a fresh hit, so
  a rule about a subsystem that has since been rewritten fades on its own.
* **Dormancy** — past `dormant_after_days` a lesson stops being injected
  entirely. It is kept, not deleted: if it recurs, it wakes with its history.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from future_agents.sdd.config import MemoryHubConfig
from future_agents.sdd.memory.text import condense, fingerprint
from future_agents.sdd.models import Lesson, MemoryCase

GLOBAL_SCOPE = "global"


class PromotionReport(BaseModel):
    """What one consolidation pass changed, so the CLI can print it."""

    promoted: list[str] = Field(default_factory=list)  # lesson ids newly created
    reinforced: list[str] = Field(default_factory=list)  # existing lessons hit again
    dormant: list[str] = Field(default_factory=list)  # lessons that aged out

    @property
    def changed(self) -> int:
        return len(self.promoted) + len(self.reinforced) + len(self.dormant)


class LessonBook:
    """Durable, deduplicated lessons with confidence that moves both ways."""

    def __init__(
        self,
        config: Optional[MemoryHubConfig] = None,
        root: str | Path = ".",
    ) -> None:
        self.config = config or MemoryHubConfig()
        self.settings = self.config.lessons
        self.root = Path(root)
        base = (
            Path(self.config.index_path).parent
            if self.config.index_path
            else self.root / self.config.case_studies_path
        )
        self.path = base / "lessons.json"
        self._lessons: dict[str, Lesson] = {}
        self._by_key: dict[str, str] = {}  # fingerprint(scope, text) → lesson id
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        for entry in raw.get("lessons", []):
            try:
                lesson = Lesson.model_validate(entry)
            except ValueError:
                continue
            self._lessons[lesson.id] = lesson
            self._by_key[_key(lesson.scope, lesson.text)] = lesson.id

    def save(self) -> None:
        from future_agents.sdd.memory.cases import _atomic_write

        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "lessons": [ln.model_dump(mode="json") for ln in self._lessons.values()],
        }
        _atomic_write(self.path, json.dumps(payload, indent=2) + "\n")

    # ── Write ─────────────────────────────────────────────────────────────────

    def observe(
        self,
        text: str,
        *,
        scope: str = GLOBAL_SCOPE,
        case_id: str = "",
        topic: str = "",
        now: Optional[datetime] = None,
    ) -> Optional[Lesson]:
        """Record one sighting of a pitfall. Returns the lesson once promoted.

        Sightings from the same case never count twice — otherwise a single run
        that logs the same QA finding for three requirements would mint a
        "recurring" lesson out of one event.
        """
        text = condense(text)
        if not text:
            return None
        moment = now or datetime.now(timezone.utc)
        key = _key(scope, text)
        existing_id = self._by_key.get(key)

        if existing_id is None:
            lesson = Lesson(
                text=text,
                scope=scope,
                topic=topic,
                hits=1,
                sources=[case_id] if case_id else [],
                first_seen=moment,
                last_seen=moment,
                status="pending",
            )
            self._lessons[lesson.id] = lesson
            self._by_key[key] = lesson.id
            return self._settle(lesson, moment)

        lesson = self._lessons[existing_id]
        if case_id and case_id in lesson.sources:
            return self._settle(lesson, moment)  # same case again — not evidence
        if case_id:
            lesson.sources.append(case_id)
        lesson.hits = max(lesson.hits + 1, len(lesson.sources))
        lesson.last_seen = moment
        return self._settle(lesson, moment)

    def _settle(self, lesson: Lesson, now: datetime) -> Optional[Lesson]:
        """Pending until the evidence bar is met; active once it is."""
        distinct = len(lesson.sources) or lesson.hits
        if distinct >= max(1, self.settings.promote_after):
            lesson.status = "active"
            lesson.last_seen = now
            return lesson
        return None

    def forget(self, lesson_ids: list[str]) -> int:
        removed = 0
        for lesson_id in lesson_ids:
            lesson = self._lessons.pop(lesson_id, None)
            if lesson is None:
                continue
            self._by_key.pop(_key(lesson.scope, lesson.text), None)
            removed += 1
        if removed:
            self.save()
        return removed

    def age(self, *, now: Optional[datetime] = None) -> list[str]:
        """Move lessons nobody has hit lately to dormant. Returns their ids."""
        moment = now or datetime.now(timezone.utc)
        gone: list[str] = []
        for lesson in self._lessons.values():
            if lesson.status != "active":
                continue
            if _age_days(lesson.last_seen, moment) > self.settings.dormant_after_days:
                lesson.status = "dormant"
                gone.append(lesson.id)
        return gone

    # ── Read ──────────────────────────────────────────────────────────────────

    def active(
        self,
        *,
        scope: str = GLOBAL_SCOPE,
        query_tokens: Optional[set[str]] = None,
        now: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> list[Lesson]:
        """Lessons worth injecting: active, in scope, confident, and relevant.

        Relevance is optional — with no query the ranking is pure confidence,
        which is what a caller listing the book wants.
        """
        if not self.settings.enabled:
            return []
        moment = now or datetime.now(timezone.utc)
        half_life = self.settings.half_life_days
        scored: list[tuple[float, Lesson]] = []
        for lesson in self._lessons.values():
            if lesson.status != "active":
                continue
            if lesson.scope not in (scope, GLOBAL_SCOPE):
                continue
            confidence = lesson.confidence(now=moment, half_life_days=half_life)
            if confidence < self.settings.min_confidence:
                continue
            if query_tokens:
                from future_agents.sdd.memory.text import similarity, tokens

                overlap = similarity(query_tokens, tokens(lesson.text))
                if overlap <= 0:
                    continue
                confidence *= 0.5 + overlap
            if lesson.scope == scope != GLOBAL_SCOPE:
                confidence *= 1.2
            scored.append((confidence, lesson))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        ceiling = limit or self.settings.max_injected
        return [lesson for _, lesson in scored[:ceiling]]

    def all_lessons(self) -> list[Lesson]:
        return sorted(self._lessons.values(), key=lambda ln: ln.last_seen, reverse=True)

    def get(self, lesson_id: str) -> Optional[Lesson]:
        return self._lessons.get(lesson_id)

    def __len__(self) -> int:
        return len(self._lessons)

    def stats(self, *, now: Optional[datetime] = None) -> dict[str, object]:
        moment = now or datetime.now(timezone.utc)
        by_status: dict[str, int] = {}
        for lesson in self._lessons.values():
            by_status[lesson.status] = by_status.get(lesson.status, 0) + 1
        confidences = [
            ln.confidence(now=moment, half_life_days=self.settings.half_life_days)
            for ln in self._lessons.values()
            if ln.status == "active"
        ]
        return {
            "total": len(self._lessons),
            "by_status": by_status,
            "mean_confidence": round(sum(confidences) / len(confidences), 3)
            if confidences
            else 0.0,
            "path": str(self.path),
        }


def learn_from_case(
    book: LessonBook,
    case: MemoryCase,
    *,
    now: Optional[datetime] = None,
) -> list[Lesson]:
    """Feed one case's pitfalls into the book, returning what got promoted."""
    promoted: list[Lesson] = []
    for pitfall in case.pitfalls:
        lesson = book.observe(pitfall, scope=case.scope, case_id=case.id, now=now)
        if lesson is not None:
            promoted.append(lesson)
    return promoted


def _key(scope: str, text: str) -> str:
    """Same lesson, differently worded, is the same lesson."""
    return f"{scope}:{fingerprint(text)}"


def _age_days(moment: datetime, now: datetime) -> float:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max(0.0, (now - moment).total_seconds() / 86400.0)
