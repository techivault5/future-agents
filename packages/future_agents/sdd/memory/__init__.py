"""Memory — what the system carries from one delivery to the next.

Three tiers, because "remember things" is three different jobs:

| Tier | Holds | Answers | Written by |
|------|-------|---------|------------|
| **Episodic** (`cases.py`) | one case per run | "have we done something like this?" | harvest |
| **Semantic** (`lessons.py`) | recurring pitfalls | "what goes wrong here?" | consolidation |
| **Procedural** (`answers.py`) | prior human answers | "what did they already tell us?" | clarify |

Everything is plain files under `docs/memory/` — markdown cases a human can
read and review, plus three JSON indexes. No database, no embedding service, no
network call on the read path. `MemoryHub` is the one object the pipeline holds,
and it is safe when memory is disabled: every method degrades to an empty answer
rather than an exception.

Two properties are load-bearing:

* **Memory is untrusted text.** Cases are built from ticket bodies and meeting
  notes, and are later injected into planning prompts. Without a filter, one
  poisoned ticket writes a "lesson" that steers every future run in the repo.
  Everything written passes the intake sanitiser first.
* **Memory forgets.** Lessons decay and go dormant, answers expire, duplicate
  cases merge, and the store is pruned. A memory that only grows eventually
  matches every query and helps with none.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from future_agents.sdd.config import MemoryHubConfig
from future_agents.sdd.intake.sanitize import sanitize, sanitize_many
from future_agents.sdd.memory.answers import AnswerBook, Recalled
from future_agents.sdd.memory.cases import (
    GLOBAL_SCOPE,
    CaseMatch,
    CaseStore,
    RetrievalReport,
    case_from_run,
)
from future_agents.sdd.memory.consolidate import ConsolidationReport, consolidate
from future_agents.sdd.memory.lessons import LessonBook, learn_from_case
from future_agents.sdd.memory.text import tokens
from future_agents.sdd.models import (
    AnswerRecord,
    ClarificationResult,
    Lesson,
    MemoryCase,
    RunState,
)

__all__ = [
    "AnswerBook",
    "AnswerRecord",
    "CaseMatch",
    "CaseStore",
    "ConsolidationReport",
    "GLOBAL_SCOPE",
    "Lesson",
    "LessonBook",
    "MemoryHub",
    "Recalled",
    "RetrievalReport",
    "consolidate",
    "learn_from_case",
]


class MemoryHub:
    """The pipeline's single door to memory: recall, harvest, consolidate."""

    def __init__(
        self,
        config: Optional[MemoryHubConfig] = None,
        root: str | Path = ".",
        memory: object | None = None,
        scope: str = GLOBAL_SCOPE,
    ) -> None:
        self.config = config or MemoryHubConfig()
        self.root = Path(root)
        self.scope = scope or GLOBAL_SCOPE
        self.cases = CaseStore(self.config, root)
        self.lessons = LessonBook(self.config, root)
        self.answers = AnswerBook(self.config, root)
        self._memory = memory  # optional LifelongMemory, for the wider agent brain

    # ── Convenience for older call sites ──────────────────────────────────────

    @property
    def path(self) -> Path:
        return self.cases.path

    @property
    def index_path(self) -> Path:
        return self.cases.index_path

    # ── Read ──────────────────────────────────────────────────────────────────

    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        *,
        scope: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> RetrievalReport:
        """Cases and lessons for one query, ready to hand the architect."""
        target = scope or self.scope
        if not self.config.enabled:
            return RetrievalReport(query=query, scope=target)
        moment = now or datetime.now(timezone.utc)
        matches = self.cases.retrieve(query, scope=target, top_k=top_k, now=moment)
        lessons = self.lessons.active(
            scope=target,
            query_tokens=tokens(query) or None,
            now=moment,
        )
        return RetrievalReport(query=query, scope=target, matches=matches, lessons=lessons)

    def recall_answer(
        self,
        question: str,
        *,
        topic: str = "",
        blocking: bool = False,
        scope: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> Optional[Recalled]:
        """What a human already said about this question, if it still stands."""
        if not self.config.enabled:
            return None
        return self.answers.recall(
            question,
            topic=topic,
            scope=scope or self.scope,
            blocking=blocking,
            now=now,
        )

    def lessons_for(
        self,
        query: str = "",
        *,
        scope: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[Lesson]:
        return self.lessons.active(
            scope=scope or self.scope,
            query_tokens=tokens(query) or None,
            limit=limit,
        )

    def all_cases(self) -> list[MemoryCase]:
        return self.cases.all_cases()

    def stats(self) -> dict[str, object]:
        by_outcome: dict[str, int] = {}
        for case in self.cases.all_cases():
            by_outcome[case.outcome] = by_outcome.get(case.outcome, 0) + 1
        return {
            "enabled": self.config.enabled,
            "scope": self.scope,
            "total": len(self.cases),
            "by_outcome": by_outcome,
            "path": str(self.cases.path),
            "lessons": self.lessons.stats(),
            "answers": self.answers.stats(),
        }

    # ── Write ─────────────────────────────────────────────────────────────────

    def store(self, case: MemoryCase, write_markdown: bool = True) -> MemoryCase:
        """Write one case, sanitising first — memory is an injection channel."""
        if not self.config.enabled:
            return case
        case = self._clean(case)
        self.cases.add(case, write_markdown=write_markdown)
        learn_from_case(self.lessons, case)
        self.lessons.save()
        if self._memory is not None and hasattr(self._memory, "remember"):
            self._memory.remember(  # type: ignore[attr-defined]
                case.to_markdown(),
                memory_type="episodic",
                tags=["sdd-case", *case.tags],
                importance=0.9 if case.outcome != "success" else 0.6,
                metadata={"case_id": case.id, "scope": case.scope},
            )
        return case

    def harvest(self, state: RunState, *, scope: Optional[str] = None) -> MemoryCase:
        """Turn a finished run into a case, and its answers into recall."""
        case = case_from_run(state, scope=scope or self.scope)
        stored = self.store(case)
        if state.clarification:
            self.remember_answers(state.clarification, scope=scope)
        return stored

    def remember_answers(
        self,
        result: ClarificationResult,
        *,
        scope: Optional[str] = None,
        answered_by: str = "",
    ) -> int:
        """Record every answered question so the next run does not re-ask it."""
        if not self.config.enabled or not self.config.answers.enabled:
            return 0
        pairs: list[tuple[str, str, str]] = []
        for question in result.questions:
            if not question.answered:
                continue
            answer = sanitize(question.answer or "", max_chars=2000).text
            if not answer:
                continue
            pairs.append((question.text, answer, question.topic.value))
        if not pairs:
            return 0
        return self.answers.record_many(
            pairs,
            scope=scope or self.scope,
            answered_by=answered_by or "human",
        )

    def consolidate(self, *, now: Optional[datetime] = None) -> ConsolidationReport:
        """Merge duplicates, promote lessons, age them out, prune the tail."""
        if not self.config.enabled:
            return ConsolidationReport()
        return consolidate(self.cases, self.lessons, self.answers, now=now)

    def forget_lessons(self, lesson_ids: list[str]) -> int:
        return self.lessons.forget(lesson_ids)

    def forget_cases(self, case_ids: list[str]) -> int:
        return self.cases.remove(case_ids)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _clean(self, case: MemoryCase) -> MemoryCase:
        """Strip instruction-shaped text before it can become a future prompt."""
        if not self.config.sanitize_on_write:
            return case
        removed: list[str] = []
        for field in ("title", "objective", "problem", "solution"):
            result = sanitize(getattr(case, field) or "", max_chars=4000)
            setattr(case, field, result.text)
            removed.extend(result.removed)
        case.pitfalls, pitfall_removals = sanitize_many(case.pitfalls, max_chars=1000)
        removed.extend(pitfall_removals)
        case.sanitized = True
        if removed:
            # Kept on the case: a human reviewing memory should see that the
            # source text tried something, not just find it quietly rewritten.
            case.pitfalls.append(f"Source text was filtered on the way in: {'; '.join(removed)}")
        return case
