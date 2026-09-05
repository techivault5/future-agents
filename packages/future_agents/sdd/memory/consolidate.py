"""Consolidation — the maintenance pass that stops memory rotting.

An append-only memory degrades in three predictable ways, and each has a step
here:

1. **Duplication.** The same ticket re-filed, or a run retried after a fix,
   writes near-identical cases. They are merged into one case with an
   occurrence count, which then *outranks* singletons in retrieval — recurrence
   is signal, not noise.
2. **Anecdote.** Pitfalls sit inside individual cases where nothing generalises
   them. Promotion lifts the ones seen in several cases into lessons.
3. **Unbounded growth.** Cases accumulate until retrieval is slow and every
   query matches something. Pruning drops the oldest *successful*, unreferenced
   cases first — failures and anything backing a lesson are kept.

Run it after a harvest, or from `spec_kit.py memory consolidate`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from future_agents.sdd.memory.answers import AnswerBook
from future_agents.sdd.memory.cases import CaseStore, case_fingerprint
from future_agents.sdd.memory.lessons import LessonBook, learn_from_case
from future_agents.sdd.models import MemoryCase

_OUTCOME_RANK = {"failure": 3, "partial": 2, "success": 1}


class ConsolidationReport(BaseModel):
    merged: int = 0
    promoted: list[str] = Field(default_factory=list)
    dormant: list[str] = Field(default_factory=list)
    pruned: int = 0
    stale_answers: int = 0

    def summary(self) -> str:
        return (
            f"merged {self.merged}, promoted {len(self.promoted)}, "
            f"dormant {len(self.dormant)}, pruned {self.pruned}, "
            f"stale answers {self.stale_answers}"
        )

    @property
    def changed(self) -> bool:
        return bool(
            self.merged or self.promoted or self.dormant or self.pruned or self.stale_answers
        )


def consolidate(
    cases: CaseStore,
    lessons: LessonBook,
    answers: Optional[AnswerBook] = None,
    *,
    now: Optional[datetime] = None,
) -> ConsolidationReport:
    moment = now or datetime.now(timezone.utc)
    report = ConsolidationReport()

    surviving, merged = _merge_duplicates(cases.all_cases())
    report.merged = merged
    if merged:
        cases.replace_all(surviving)

    for case in surviving:
        for lesson in learn_from_case(lessons, case, now=moment):
            if lesson.id not in report.promoted:
                report.promoted.append(lesson.id)

    report.dormant = lessons.age(now=moment)
    lessons.save()

    report.pruned = _prune(cases, lessons, surviving)
    if answers is not None:
        report.stale_answers = _drop_stale_answers(answers, moment)
    return report


def _merge_duplicates(cases: list[MemoryCase]) -> tuple[list[MemoryCase], int]:
    """Fold cases with the same scope+objective fingerprint into one.

    The survivor keeps the worst outcome seen (a run that failed once is not
    made safe by later succeeding), the union of the pitfalls, and the sum of
    the occurrences.
    """
    by_print: dict[str, MemoryCase] = {}
    order: list[str] = []
    merged = 0

    for case in sorted(cases, key=lambda c: c.created_at):
        print_ = case_fingerprint(case)
        if not print_:
            print_ = case.id
        keeper = by_print.get(print_)
        if keeper is None:
            by_print[print_] = case
            order.append(print_)
            continue

        merged += 1
        keeper.occurrences += case.occurrences
        keeper.updated_at = max(keeper.updated_at, case.created_at, case.updated_at)
        if _OUTCOME_RANK.get(case.outcome, 0) > _OUTCOME_RANK.get(keeper.outcome, 0):
            keeper.outcome = case.outcome
        seen = {p.lower() for p in keeper.pitfalls}
        keeper.pitfalls.extend(p for p in case.pitfalls if p.lower() not in seen)
        keeper.pitfalls = keeper.pitfalls[:12]
        keeper.tags = sorted(set(keeper.tags) | set(case.tags))[:10]
        keeper.requirement_ids = sorted(set(keeper.requirement_ids) | set(case.requirement_ids))

    return [by_print[p] for p in order], merged


def _prune(cases: CaseStore, lessons: LessonBook, surviving: list[MemoryCase]) -> int:
    """Drop the oldest disposable cases once past the configured ceiling."""
    ceiling = cases.config.max_cases
    if ceiling <= 0 or len(surviving) <= ceiling:
        return 0

    cited = {case_id for lesson in lessons.all_lessons() for case_id in lesson.sources}
    disposable = sorted(
        (c for c in surviving if c.outcome == "success" and c.id not in cited),
        key=lambda c: c.created_at,
    )
    overflow = len(surviving) - ceiling
    doomed = [c.id for c in disposable[:overflow]]
    # Everything left is a failure or a lesson's evidence: keeping it and
    # letting the store grow past the ceiling is the lesser harm.
    return cases.remove(doomed) if doomed else 0


def _drop_stale_answers(answers: AnswerBook, now: datetime) -> int:
    limit = answers.settings.max_age_days * 2  # twice unusable before we forget
    stale = [r for r in answers.all_records() if r.age_days(now=now) > limit]
    dropped = 0
    for record in stale:
        dropped += answers.forget([record.fingerprint], scope=record.scope)
    return dropped
