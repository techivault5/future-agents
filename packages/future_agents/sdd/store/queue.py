"""The work queue — tickets in, one worker per item, poison quarantined.

A ticket becomes a `WorkItem`. A worker claims the next unclaimed item under a
lease, works it, and either completes it or fails it. A failed item is retried
until `max_attempts`, then moved to the dead letter with its reasons intact —
retrying a poison ticket forever is how automated systems burn budget quietly.

Backed by the same atomic-write discipline as the run store: no daemon, no
database, and the queue is readable with `cat` when something goes wrong.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from future_agents.sdd.models import Objective
from future_agents.sdd.store.run_store import DEFAULT_ROOT, _atomic_write


def _now() -> datetime:
    return datetime.now(timezone.utc)


class WorkItem(BaseModel):
    """One piece of work waiting for, or held by, a worker."""

    id: str
    objective: Objective
    external_key: str = ""
    priority: int = 5  # lower runs first
    attempts: int = 0
    max_attempts: int = 3
    owner: str = ""
    leased_until: Optional[datetime] = None
    run_id: str = ""
    status: str = "queued"  # queued | claimed | done | dead
    reasons: list[str] = Field(default_factory=list)
    enqueued_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    @property
    def claimable(self) -> bool:
        if self.status == "queued":
            return True
        if self.status != "claimed":
            return False
        return self.leased_until is None or self.leased_until < _now()


class WorkQueue:
    """A durable queue with leases, retries and a dead letter."""

    def __init__(self, root: str | Path = DEFAULT_ROOT) -> None:
        self.path = Path(root) / "queue.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # ── Producing ─────────────────────────────────────────────────────────────

    def enqueue(
        self,
        objective: Objective,
        priority: int = 5,
        max_attempts: int = 3,
    ) -> WorkItem:
        """Add a ticket. The same external ticket is never queued twice."""
        items = self._load()
        key = objective.external.key if objective.external else ""
        if key:
            existing = next(
                (i for i in items.values() if i.external_key == key and i.status != "dead"), None
            )
            if existing:
                return existing

        item = WorkItem(
            id=f"wi-{objective.id.split('-')[-1]}",
            objective=objective,
            external_key=key,
            priority=priority,
            max_attempts=max_attempts,
        )
        items[item.id] = item
        self._save(items)
        return item

    # ── Consuming ─────────────────────────────────────────────────────────────

    def claim(self, owner: str, ttl_seconds: int = 900) -> Optional[WorkItem]:
        """Take the highest-priority claimable item, or nothing."""
        items = self._load()
        candidates = [i for i in items.values() if i.claimable]
        if not candidates:
            return None
        candidates.sort(key=lambda i: (i.priority, i.enqueued_at))
        item = candidates[0]
        item.status = "claimed"
        item.owner = owner
        item.attempts += 1
        item.leased_until = _now() + timedelta(seconds=ttl_seconds)
        item.updated_at = _now()
        self._save(items)
        return item

    def heartbeat(self, item_id: str, owner: str, ttl_seconds: int = 900) -> bool:
        items = self._load()
        item = items.get(item_id)
        if not item or item.owner != owner:
            return False
        item.leased_until = _now() + timedelta(seconds=ttl_seconds)
        item.updated_at = _now()
        self._save(items)
        return True

    def complete(self, item_id: str, run_id: str = "") -> None:
        items = self._load()
        item = items.get(item_id)
        if not item:
            return
        item.status = "done"
        item.run_id = run_id
        item.leased_until = None
        item.updated_at = _now()
        self._save(items)

    def fail(self, item_id: str, reason: str) -> WorkItem | None:
        """Requeue for another attempt, or quarantine once attempts run out."""
        items = self._load()
        item = items.get(item_id)
        if not item:
            return None
        item.reasons.append(reason[:300])
        item.owner = ""
        item.leased_until = None
        item.updated_at = _now()
        item.status = "dead" if item.attempts >= item.max_attempts else "queued"
        self._save(items)
        return item

    def release(self, item_id: str) -> None:
        """Give an item back without spending an attempt (a clean shutdown)."""
        items = self._load()
        item = items.get(item_id)
        if not item:
            return
        item.status = "queued"
        item.owner = ""
        item.leased_until = None
        item.attempts = max(0, item.attempts - 1)
        item.updated_at = _now()
        self._save(items)

    # ── Views ─────────────────────────────────────────────────────────────────

    def pending(self) -> list[WorkItem]:
        return sorted(
            (i for i in self._load().values() if i.status in {"queued", "claimed"}),
            key=lambda i: (i.priority, i.enqueued_at),
        )

    def dead_letter(self) -> list[WorkItem]:
        return [i for i in self._load().values() if i.status == "dead"]

    def stats(self) -> dict[str, int]:
        items = self._load().values()
        counts: dict[str, int] = {}
        for item in items:
            counts[item.status] = counts.get(item.status, 0) + 1
        counts["total"] = len(list(items))
        return counts

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load(self) -> dict[str, WorkItem]:
        if not self.path.is_file():
            return {}
        try:
            raw = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
        out: dict[str, WorkItem] = {}
        for entry in raw.get("items", []):
            try:
                item = WorkItem.model_validate(entry)
            except ValueError:
                continue
            out[item.id] = item
        return out

    def _save(self, items: dict[str, WorkItem]) -> None:
        payload = {
            "updated_at": _now().isoformat(),
            "items": [i.model_dump(mode="json") for i in items.values()],
        }
        _atomic_write(self.path, json.dumps(payload, indent=1))
