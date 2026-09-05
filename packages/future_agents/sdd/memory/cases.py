"""Episodic memory — one case per run, on disk as markdown plus a JSON index.

Markdown because a lesson nobody can read is not a lesson: cases are reviewable,
diffable and greppable by the humans who own the repo. The index is the machine's
copy of the same thing.

Retrieval is deliberately opinionated:

* **Recall, not Jaccard.** Score is the share of the *query* a case covers, so a
  rich case is not punished for being rich.
* **Fields are not equal.** A hit in the title or the tags says more than a hit
  buried in a prose problem statement.
* **Failures outrank successes.** A case recording a pitfall changes the next
  plan; a case recording a smooth run rarely does.
* **Recent outranks ancient.** A decision from last month reflects the codebase
  as it is; one from three years ago reflects a codebase that no longer exists.
* **Local outranks foreign.** A case learned in this repo is evidence about this
  repo. One learned elsewhere is a hint, and can be excluded outright.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from future_agents.sdd.config import MemoryHubConfig
from future_agents.sdd.memory.text import (
    condense,
    fingerprint,
    first_line,
    similarity,
    slug,
    tokens,
)
from future_agents.sdd.models import (
    ClarificationResult,
    Lesson,
    MemoryCase,
    QAReport,
    QAVerdict,
    RunState,
)

#: Where a term hits matters more than how often. Weights are relative, not tuned.
FIELD_WEIGHTS: tuple[tuple[str, float], ...] = (
    ("title", 3.0),
    ("tags", 3.0),
    ("objective", 2.0),
    ("problem", 1.0),
    ("solution", 0.6),
    ("pitfalls", 1.2),
)

GLOBAL_SCOPE = "global"


class CaseMatch(BaseModel):
    case: MemoryCase
    score: float
    reason: str = ""


class RetrievalReport(BaseModel):
    """What memory has to say about one query, cases and lessons together."""

    query: str
    scope: str = GLOBAL_SCOPE
    matches: list[CaseMatch] = Field(default_factory=list)
    lessons: list[Lesson] = Field(default_factory=list)

    def warnings(self) -> list[str]:
        """Everything the planner should treat as a constraint, lessons first.

        Lessons lead because they survived recurrence: each one was hit in more
        than one run, which is the only evidence memory has that a pitfall is a
        property of the codebase rather than of one bad afternoon.
        """
        out = [
            f"{lesson.text} (lesson {lesson.id}, seen {lesson.hits}×)" for lesson in self.lessons
        ]
        known = {lesson.text.lower() for lesson in self.lessons}
        for match in self.matches:
            for pitfall in match.case.pitfalls:
                if pitfall.lower() not in known:
                    out.append(f"{pitfall} (learned in {match.case.id})")
        return out

    @property
    def case_ids(self) -> list[str]:
        return [m.case.id for m in self.matches]


class CaseStore:
    """Load, write, retrieve and prune delivery cases."""

    def __init__(
        self,
        config: Optional[MemoryHubConfig] = None,
        root: str | Path = ".",
    ) -> None:
        self.config = config or MemoryHubConfig()
        self.root = Path(root)
        self.path = self.root / self.config.case_studies_path
        self.index_path = (
            Path(self.config.index_path) if self.config.index_path else self.path / "index.json"
        )
        self._cases: dict[str, MemoryCase] = {}
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self.index_path.is_file():
            return
        try:
            raw = json.loads(self.index_path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        for entry in raw.get("cases", []):
            try:
                case = MemoryCase.model_validate(entry)
            except ValueError:
                continue  # a case we cannot parse is not worth failing a run over
            self._cases[case.id] = case

    def save(self) -> None:
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "cases": [c.model_dump(mode="json") for c in self._cases.values()],
        }
        _atomic_write(self.index_path, json.dumps(payload, indent=2) + "\n")

    def write_markdown(self, case: MemoryCase) -> Path:
        self.path.mkdir(parents=True, exist_ok=True)
        target = self.path / f"{slug(case.title)}-{case.id}.md"
        target.write_text(case.to_markdown())
        return target

    # ── Write ─────────────────────────────────────────────────────────────────

    def add(self, case: MemoryCase, *, write_markdown: bool = True) -> MemoryCase:
        self._cases[case.id] = case
        if write_markdown:
            self.write_markdown(case)
        self.save()
        return case

    def remove(self, case_ids: list[str]) -> int:
        removed = 0
        for case_id in case_ids:
            case = self._cases.pop(case_id, None)
            if case is None:
                continue
            removed += 1
            target = self.path / f"{slug(case.title)}-{case.id}.md"
            if target.is_file():
                target.unlink()
        if removed:
            self.save()
        return removed

    def replace_all(self, cases: list[MemoryCase]) -> None:
        self._cases = {c.id: c for c in cases}
        self.save()

    # ── Read ──────────────────────────────────────────────────────────────────

    def get(self, case_id: str) -> Optional[MemoryCase]:
        return self._cases.get(case_id)

    def all_cases(self) -> list[MemoryCase]:
        return sorted(self._cases.values(), key=lambda c: c.created_at, reverse=True)

    def __len__(self) -> int:
        return len(self._cases)

    def retrieve(
        self,
        query: str,
        *,
        scope: str = GLOBAL_SCOPE,
        top_k: Optional[int] = None,
        now: Optional[datetime] = None,
    ) -> list[CaseMatch]:
        if not self._cases:
            return []
        settings = self.config.retrieval
        limit = top_k or settings.max_context_injection
        q_tokens = tokens(query)
        if not q_tokens:
            return []
        moment = now or datetime.now(timezone.utc)
        matches: list[CaseMatch] = []

        for case in self._cases.values():
            foreign = case.scope not in (scope, GLOBAL_SCOPE)
            if foreign and settings.scope_strict:
                continue
            score, hits = self._score(case, q_tokens)
            if score <= 0:
                continue
            reasons = [f"matched {', '.join(sorted(hits)[:4])}"] if hits else []

            score *= _recency_factor(case.created_at, moment, self.config.recency_half_life_days)
            if settings.prefer_failures and case.outcome != "success":
                score *= 1.5
                reasons.append(f"prior {case.outcome}")
            if not foreign and case.scope == scope != GLOBAL_SCOPE:
                score *= settings.scope_boost
                reasons.append(f"same repo ({scope})")
            elif foreign:
                score *= 0.6
                reasons.append(f"from {case.scope}")
            if case.occurrences > 1:
                score *= 1.0 + min(0.5, 0.1 * (case.occurrences - 1))
                reasons.append(f"seen {case.occurrences}×")

            score = round(min(score, 1.0), 3)
            if score < settings.min_score:
                continue
            matches.append(CaseMatch(case=case, score=score, reason="; ".join(reasons)))

        matches.sort(key=lambda m: (m.score, m.case.created_at), reverse=True)
        return matches[:limit]

    @staticmethod
    def _score(case: MemoryCase, q_tokens: set[str]) -> tuple[float, set[str]]:
        """Weighted recall of the query across the case's fields."""
        total_weight = sum(weight for _, weight in FIELD_WEIGHTS)
        earned = 0.0
        hit_terms: set[str] = set()
        for field, weight in FIELD_WEIGHTS:
            value = getattr(case, field, "")
            text = " ".join(value) if isinstance(value, list) else str(value)
            field_tokens = tokens(text)
            overlap = q_tokens & field_tokens
            if not overlap:
                continue
            hit_terms |= overlap
            earned += weight * similarity(q_tokens, field_tokens)
        return earned / total_weight, hit_terms


# ── Harvest ───────────────────────────────────────────────────────────────────


def case_from_run(state: RunState, *, scope: str = GLOBAL_SCOPE) -> MemoryCase:
    """Compress one run into a case. Failures carry the useful part."""
    spec = state.spec
    qa = state.qa
    failed_work = [w for w in state.work_results if w.error]
    outcome = "success"
    if qa is None or qa.verdict is QAVerdict.BLOCKED:
        outcome = "partial"
    elif qa.verdict is QAVerdict.FAIL or failed_work:
        outcome = "failure"

    solution_bits: list[str] = []
    if state.plan:
        solution_bits.append(state.plan.architecture)
        solution_bits.extend(f"{c.name}: {c.responsibility}" for c in state.plan.components)
        solution_bits.extend(
            f"placed {p.requirement_id} at {p.target_path} ({p.approach})"
            for p in state.plan.placements
            if p.target_path
        )

    return MemoryCase(
        title=spec.title if spec else first_line(state.objective.statement),
        objective=state.objective.statement,
        problem=(spec.summary if spec else state.objective.context) or "—",
        solution="\n".join(b for b in solution_bits if b) or "—",
        pitfalls=pitfalls_from_run(state.clarification, qa, state),
        tags=tags_from_run(state),
        outcome=outcome,
        requirement_ids=[r.id for r in spec.requirements] if spec else [],
        scope=scope,
        run_id=state.id,
    )


def pitfalls_from_run(
    clarification: Optional[ClarificationResult],
    qa: Optional[QAReport],
    state: RunState,
) -> list[str]:
    """What went wrong, phrased so the next run can act on it."""
    out: list[str] = []
    if clarification:
        for question in clarification.questions:
            if question.blocking and question.answered:
                out.append(
                    f"Intent gap — '{condense(question.text, limit=120)}' had to be asked; "
                    f"answer: {first_line(question.answer or '')}"
                )
        if clarification.meeting:
            out.append(f"Needed a live meeting: {clarification.meeting.reason}")
    if qa:
        out.extend(f"QA {f.severity}: {f.summary}" for f in qa.findings if f.in_scope)
    out.extend(
        f"Task {w.task_id} failed: {first_line(w.error)}" for w in state.work_results if w.error
    )
    return [condense(p) for p in out[:12]]


def tags_from_run(state: RunState) -> list[str]:
    tags = {state.objective.source.value}
    if state.plan:
        tags.update(c.name.lower() for c in state.plan.components)
    if state.qa:
        tags.add(f"qa-{state.qa.verdict.value}")
    if state.objective.external:
        tags.update(label.lower() for label in state.objective.external.labels)
    return sorted(t for t in tags if t)[:10]


def case_fingerprint(case: MemoryCase) -> str:
    """Two runs of the same ask in the same repo are one case, not two."""
    return fingerprint(case.scope, case.title, case.objective)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _recency_factor(created: datetime, now: datetime, half_life_days: float) -> float:
    if half_life_days <= 0:
        return 1.0
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - created).total_seconds() / 86400.0)
    # Floored: an old case is weaker evidence, never zero evidence.
    return max(0.35, 0.5 ** (age_days / half_life_days))


def _atomic_write(path: Path, payload: str) -> None:
    """Write-then-rename: a crash mid-write must not corrupt the index."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w") as fh:
            fh.write(payload)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
