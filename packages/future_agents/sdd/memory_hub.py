"""Memory Hub — case-based reasoning over past runs.

Cases are markdown on disk (reviewable, diffable, greppable) with a JSON index
for retrieval. Retrieval is deliberately biased toward *failures*: a case that
records a pitfall changes the next plan more than one that records a success.

Backed by `LifelongMemory` when available so cases join the wider agent memory;
falls back to the on-disk index alone.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from future_agents.sdd.config import MemoryHubConfig
from future_agents.sdd.models import (
    ClarificationResult,
    MemoryCase,
    QAReport,
    QAVerdict,
    RunState,
)

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
}


class CaseMatch(BaseModel):
    case: MemoryCase
    score: float
    reason: str = ""


class RetrievalReport(BaseModel):
    query: str
    matches: list[CaseMatch] = Field(default_factory=list)

    def warnings(self) -> list[str]:
        """Pitfalls from matched cases, phrased as constraints for the planner."""
        out: list[str] = []
        for match in self.matches:
            for pitfall in match.case.pitfalls:
                out.append(f"{pitfall} (learned in {match.case.id})")
        return out


class MemoryHub:
    """Store, retrieve and harvest delivery cases."""

    def __init__(
        self,
        config: Optional[MemoryHubConfig] = None,
        root: str | Path = ".",
        memory: object | None = None,
    ) -> None:
        self.config = config or MemoryHubConfig()
        self.root = Path(root)
        self.path = self.root / self.config.case_studies_path
        self.index_path = (
            Path(self.config.index_path) if self.config.index_path else self.path / "index.json"
        )
        self._cases: dict[str, MemoryCase] = {}
        self._memory = memory  # optional LifelongMemory
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
                continue
            self._cases[case.id] = case

    def _save(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "cases": [c.model_dump(mode="json") for c in self._cases.values()],
        }
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(payload, indent=2) + "\n")

    # ── Write ─────────────────────────────────────────────────────────────────

    def store(self, case: MemoryCase, write_markdown: bool = True) -> MemoryCase:
        if not self.config.enabled:
            return case
        self._cases[case.id] = case
        if write_markdown:
            self.path.mkdir(parents=True, exist_ok=True)
            (self.path / f"{_slug(case.title)}-{case.id}.md").write_text(case.to_markdown())
        self._save()
        if self._memory is not None and hasattr(self._memory, "remember"):
            self._memory.remember(  # type: ignore[attr-defined]
                case.to_markdown(),
                memory_type="episodic",
                tags=["sdd-case", *case.tags],
                importance=0.9 if case.outcome != "success" else 0.6,
                metadata={"case_id": case.id},
            )
        return case

    def harvest(self, state: RunState) -> MemoryCase:
        """Synthesise one run into a case. Failures carry the useful lessons."""
        spec = state.spec
        qa = state.qa
        pitfalls = _pitfalls(state.clarification, qa, state)
        failed_work = [w for w in state.work_results if w.error]
        outcome = "success"
        if qa is None or qa.verdict is QAVerdict.BLOCKED:
            outcome = "partial"
        elif qa.verdict is QAVerdict.FAIL or failed_work:
            outcome = "failure"

        solution_bits = []
        if state.plan:
            solution_bits.append(state.plan.architecture)
            solution_bits.extend(f"{c.name}: {c.responsibility}" for c in state.plan.components)
        case = MemoryCase(
            title=spec.title if spec else _first_line(state.objective.statement),
            objective=state.objective.statement,
            problem=(spec.summary if spec else state.objective.context) or "—",
            solution="\n".join(b for b in solution_bits if b) or "—",
            pitfalls=pitfalls,
            tags=_tags(state),
            outcome=outcome,
            requirement_ids=[r.id for r in spec.requirements] if spec else [],
        )
        return self.store(case)

    # ── Read ──────────────────────────────────────────────────────────────────

    def retrieve(self, query: str, top_k: Optional[int] = None) -> RetrievalReport:
        """Top-k cases by keyword overlap, with failures weighted up."""
        if not self.config.enabled or not self._cases:
            return RetrievalReport(query=query)
        limit = top_k or self.config.retrieval.max_context_injection
        q_words = _tokens(query)
        matches: list[CaseMatch] = []
        for case in self._cases.values():
            c_words = _tokens(
                " ".join([case.title, case.objective, case.problem, " ".join(case.tags)])
            )
            if not q_words or not c_words:
                continue
            score = len(q_words & c_words) / len(q_words | c_words)
            if score < self.config.retrieval.min_score:
                continue
            reason = "keyword overlap"
            if self.config.retrieval.prefer_failures and case.outcome != "success":
                score *= 1.5
                reason = f"{reason}; prior {case.outcome}"
            matches.append(CaseMatch(case=case, score=round(min(score, 1.0), 3), reason=reason))
        matches.sort(key=lambda m: m.score, reverse=True)
        return RetrievalReport(query=query, matches=matches[:limit])

    def all_cases(self) -> list[MemoryCase]:
        return sorted(self._cases.values(), key=lambda c: c.created_at, reverse=True)

    def stats(self) -> dict[str, object]:
        by_outcome: dict[str, int] = {}
        for case in self._cases.values():
            by_outcome[case.outcome] = by_outcome.get(case.outcome, 0) + 1
        return {
            "total": len(self._cases),
            "by_outcome": by_outcome,
            "path": str(self.path),
        }


# ── Helpers ───────────────────────────────────────────────────────────────────


def _pitfalls(
    clarification: Optional[ClarificationResult],
    qa: Optional[QAReport],
    state: RunState,
) -> list[str]:
    out: list[str] = []
    if clarification:
        for question in clarification.questions:
            if question.blocking and question.answered:
                out.append(
                    f"Intent gap — '{question.text}' had to be asked; "
                    f"answer: {_first_line(question.answer or '')}"
                )
        if clarification.meeting:
            out.append(f"Needed a live meeting: {clarification.meeting.reason}")
    if qa:
        out.extend(f"QA {f.severity}: {f.summary}" for f in qa.findings if f.in_scope)
    out.extend(
        f"Task {w.task_id} failed: {_first_line(w.error)}" for w in state.work_results if w.error
    )
    return out[:12]


def _tags(state: RunState) -> list[str]:
    tags = {state.objective.source.value}
    if state.plan:
        tags.update(c.name.lower() for c in state.plan.components)
    if state.qa:
        tags.add(f"qa-{state.qa.verdict.value}")
    return sorted(t for t in tags if t)[:10]


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9_-]{2,}", text.lower()) if w not in _STOP}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "case"


def _first_line(text: str) -> str:
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    return line[:160]
