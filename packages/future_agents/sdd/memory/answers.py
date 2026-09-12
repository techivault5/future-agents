"""Procedural memory — the answers a human already gave.

The clarifier's job is to ask what it cannot know. Asking the *same* question
every quarter is not diligence, it is amnesia, and it is the fastest way to make
people stop answering. The answer book closes that loop: a question whose
fingerprint has been answered before comes back as a stated assumption instead
of a blocking question, with the provenance attached so a human can see it was
recalled rather than invented.

Three rules keep recall from becoming a liability:

* **Scope.** "Which queue do we use?" has a different answer per repository.
  Cross-repo reuse is off by default.
* **Age.** An answer past `max_age_days` is a guess about the present, so the
  question is asked again.
* **Blocking questions are still asked.** Anything the detectors marked
  blocking — a safety, compliance or irreversibility trigger — is re-confirmed
  by default, however well remembered. `reuse_blocking` can relax that, and it
  is a deliberate, configured decision.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from future_agents.sdd.config import MemoryHubConfig
from future_agents.sdd.memory.text import condense, fingerprint
from future_agents.sdd.models import AnswerRecord

GLOBAL_SCOPE = "global"


class Recalled(BaseModel):
    """A remembered answer, with everything a human needs to challenge it."""

    record: AnswerRecord
    basis: str

    @property
    def answer(self) -> str:
        return self.record.answer


class AnswerBook:
    """Question fingerprint → the answer a human gave, scoped and dated."""

    def __init__(
        self,
        config: Optional[MemoryHubConfig] = None,
        root: str | Path = ".",
    ) -> None:
        self.config = config or MemoryHubConfig()
        self.settings = self.config.answers
        self.root = Path(root)
        base = (
            Path(self.config.index_path).parent
            if self.config.index_path
            else self.root / self.config.case_studies_path
        )
        self.path = base / "answers.json"
        self._records: dict[str, AnswerRecord] = {}  # keyed by scope:fingerprint
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        for entry in raw.get("answers", []):
            try:
                record = AnswerRecord.model_validate(entry)
            except ValueError:
                continue
            self._records[_key(record.scope, record.fingerprint)] = record

    def save(self) -> None:
        from future_agents.sdd.memory.cases import _atomic_write

        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "answers": [r.model_dump(mode="json") for r in self._records.values()],
        }
        _atomic_write(self.path, json.dumps(payload, indent=2) + "\n")

    # ── Write ─────────────────────────────────────────────────────────────────

    def record(
        self,
        question: str,
        answer: str,
        *,
        topic: str = "",
        scope: str = GLOBAL_SCOPE,
        answered_by: str = "human",
        now: Optional[datetime] = None,
    ) -> Optional[AnswerRecord]:
        """Remember one answer. Re-answering an old question refreshes it."""
        question, answer = condense(question, limit=300), condense(answer, limit=600)
        if not question or not answer:
            return None
        moment = now or datetime.now(timezone.utc)
        print_ = fingerprint(topic, question)
        if not print_:
            return None
        key = _key(scope, print_)
        existing = self._records.get(key)
        if existing is not None:
            existing.answer = answer
            existing.answered_by = answered_by
            existing.last_seen = moment
            record = existing
        else:
            record = AnswerRecord(
                fingerprint=print_,
                question=question,
                answer=answer,
                topic=topic,
                scope=scope,
                answered_by=answered_by,
                first_seen=moment,
                last_seen=moment,
            )
            self._records[key] = record
        self.save()
        return record

    def record_many(
        self,
        pairs: list[tuple[str, str, str]],
        *,
        scope: str = GLOBAL_SCOPE,
        answered_by: str = "human",
        now: Optional[datetime] = None,
    ) -> int:
        """`(question, answer, topic)` triples in one write."""
        written = 0
        for question, answer, topic in pairs:
            if self.record(
                question,
                answer,
                topic=topic,
                scope=scope,
                answered_by=answered_by,
                now=now,
            ):
                written += 1
        return written

    def forget(self, fingerprints: list[str], *, scope: str = GLOBAL_SCOPE) -> int:
        removed = 0
        for print_ in fingerprints:
            if self._records.pop(_key(scope, print_), None) is not None:
                removed += 1
        if removed:
            self.save()
        return removed

    # ── Read ──────────────────────────────────────────────────────────────────

    def recall(
        self,
        question: str,
        *,
        topic: str = "",
        scope: str = GLOBAL_SCOPE,
        blocking: bool = False,
        now: Optional[datetime] = None,
    ) -> Optional[Recalled]:
        """The prior answer to this question, or None if we should ask again."""
        if not self.settings.enabled:
            return None
        if blocking and not self.settings.reuse_blocking:
            return None
        print_ = fingerprint(topic, condense(question, limit=300))
        if not print_:
            return None
        moment = now or datetime.now(timezone.utc)

        record = self._records.get(_key(scope, print_))
        if record is None and not self.settings.scope_strict:
            record = self._records.get(_key(GLOBAL_SCOPE, print_))
            if record is None:
                record = next(
                    (r for r in self._records.values() if r.fingerprint == print_),
                    None,
                )
        if record is None:
            return None

        age = record.age_days(now=moment)
        if age > self.settings.max_age_days:
            return None  # too old to stand in for a person

        record.hits += 1
        self.save()
        where = "this repo" if record.scope == scope else f"repo {record.scope}"
        return Recalled(
            record=record,
            basis=(
                f"recalled from memory ({where}, answered by {record.answered_by} "
                f"{age:.0f}d ago): {record.question}"
            ),
        )

    def all_records(self) -> list[AnswerRecord]:
        return sorted(self._records.values(), key=lambda r: r.last_seen, reverse=True)

    def __len__(self) -> int:
        return len(self._records)

    def stats(self) -> dict[str, object]:
        return {
            "total": len(self._records),
            "reused": sum(r.hits for r in self._records.values()),
            "scopes": sorted({r.scope for r in self._records.values()}),
            "path": str(self.path),
        }


def _key(scope: str, print_: str) -> str:
    return f"{scope}:{print_}"
