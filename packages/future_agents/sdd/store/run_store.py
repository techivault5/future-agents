"""Durable run storage — a run survives the process that started it.

Files on disk, written atomically (temp file + rename), one JSON per run plus a
small index. No database to operate, no daemon to run, and a crashed worker
leaves a readable artifact rather than a lost conversation.

Leases are advisory and time-bounded: a worker claims a run, heartbeats while it
works, and an expired lease is reclaimable by anyone. That is what stops two
agents from picking up the same ticket, and what lets work resume when a worker
dies mid-task.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

from pydantic import BaseModel, Field

from future_agents.sdd.models import SCHEMA_VERSION, RunState, Stage

DEFAULT_ROOT = Path(".spec-kit/state")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Lease(BaseModel):
    owner: str
    until: datetime
    heartbeat_at: datetime = Field(default_factory=_now)

    def live(self, now: Optional[datetime] = None) -> bool:
        return (now or _now()) < self.until


class RunRecord(BaseModel):
    """The index entry — enough to find and triage a run without loading it."""

    run_id: str
    external_key: str = ""
    stage: str = Stage.INTAKE.value
    objective: str = ""
    schema_version: int = SCHEMA_VERSION
    updated_at: datetime = Field(default_factory=_now)
    lease: Optional[Lease] = None
    attempts: int = 0
    dead: bool = False
    reason: str = ""


class StoreError(RuntimeError):
    """The store could not satisfy the request — usually a lost lease."""


class RunStore:
    """Durable, atomic, leased storage for runs."""

    def __init__(self, root: str | Path = DEFAULT_ROOT) -> None:
        self.root = Path(root)
        self.runs_dir = self.root / "runs"
        self.index_path = self.root / "index.json"
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    # ── Runs ──────────────────────────────────────────────────────────────────

    def save(self, state: RunState, owner: str = "") -> Path:
        """Write the run and refresh its index entry. Never partially written."""
        record = self._record(state.id) or RunRecord(run_id=state.id)
        if owner and record.lease and record.lease.live() and record.lease.owner != owner:
            raise StoreError(f"run {state.id} is leased by {record.lease.owner}")

        path = self.runs_dir / f"{state.id}.json"
        _atomic_write(path, json.dumps(state.model_dump(mode="json"), indent=1))

        record.external_key = state.external_key
        record.stage = state.stage.value
        record.objective = state.objective.statement[:200]
        record.schema_version = state.schema_version
        record.updated_at = _now()
        self._put(record)
        return path

    def load(self, run_id: str) -> RunState:
        path = self.runs_dir / f"{run_id}.json"
        if not path.is_file():
            raise StoreError(f"run {run_id} not found")
        payload = json.loads(path.read_text())
        version = payload.get("schema_version", 1)
        if version > SCHEMA_VERSION:
            raise StoreError(
                f"run {run_id} was written by a newer schema (v{version} > v{SCHEMA_VERSION})"
            )
        return RunState.model_validate(_migrate(payload, version))

    def exists_for(self, external_key: str) -> Optional[str]:
        """The run already handling this ticket, if there is one."""
        if not external_key:
            return None
        for record in self.records():
            if record.external_key == external_key and not record.dead:
                return record.run_id
        return None

    def records(self) -> list[RunRecord]:
        index = self._index()
        return sorted(index.values(), key=lambda r: r.updated_at, reverse=True)

    def stuck(self, older_than_seconds: float = 3600) -> list[RunRecord]:
        """Runs nobody is working on and nobody finished — the watchdog's input."""
        cutoff = _now() - timedelta(seconds=older_than_seconds)
        return [
            record
            for record in self.records()
            if record.stage not in {Stage.DONE.value, Stage.BLOCKED.value}
            and record.updated_at < cutoff
            and not (record.lease and record.lease.live())
        ]

    # ── Leases ────────────────────────────────────────────────────────────────

    def claim(self, run_id: str, owner: str, ttl_seconds: int = 900) -> bool:
        record = self._record(run_id) or RunRecord(run_id=run_id)
        if record.lease and record.lease.live() and record.lease.owner != owner:
            return False
        record.lease = Lease(owner=owner, until=_now() + timedelta(seconds=ttl_seconds))
        record.attempts += 1
        self._put(record)
        return True

    def heartbeat(self, run_id: str, owner: str, ttl_seconds: int = 900) -> bool:
        record = self._record(run_id)
        if not record or not record.lease or record.lease.owner != owner:
            return False
        record.lease.until = _now() + timedelta(seconds=ttl_seconds)
        record.lease.heartbeat_at = _now()
        self._put(record)
        return True

    def release(self, run_id: str, owner: str = "") -> None:
        record = self._record(run_id)
        if not record:
            return
        if owner and record.lease and record.lease.owner != owner:
            return
        record.lease = None
        self._put(record)

    def mark_dead(self, run_id: str, reason: str) -> None:
        """Poison runs stop being retried and start being visible."""
        record = self._record(run_id) or RunRecord(run_id=run_id)
        record.dead = True
        record.reason = reason[:400]
        record.lease = None
        self._put(record)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _index(self) -> dict[str, RunRecord]:
        if not self.index_path.is_file():
            return {}
        try:
            raw = json.loads(self.index_path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
        out: dict[str, RunRecord] = {}
        for entry in raw.get("runs", []):
            try:
                record = RunRecord.model_validate(entry)
            except ValueError:
                continue
            out[record.run_id] = record
        return out

    def _record(self, run_id: str) -> Optional[RunRecord]:
        return self._index().get(run_id)

    def _put(self, record: RunRecord) -> None:
        index = self._index()
        index[record.run_id] = record
        payload = {
            "updated_at": _now().isoformat(),
            "runs": [r.model_dump(mode="json") for r in index.values()],
        }
        _atomic_write(self.index_path, json.dumps(payload, indent=1))


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file in the same directory, then rename — never partial."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    )
    try:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    finally:
        handle.close()
    os.replace(handle.name, path)


def _migrate(payload: dict, version: int) -> dict:
    """Bring an older run forward. Additive fields need no work; gaps get defaults."""
    if version < 2:
        payload.setdefault("budget", {})
        payload.setdefault("assignments", [])
        payload.setdefault("owner", "")
        objective = payload.get("objective", {})
        objective.setdefault("untrusted", False)
        objective.setdefault("external", None)
    payload["schema_version"] = SCHEMA_VERSION
    return payload


def iter_runs(store: RunStore, stages: Iterable[str] = ()) -> Iterable[RunState]:
    wanted = set(stages)
    for record in store.records():
        if wanted and record.stage not in wanted:
            continue
        try:
            yield store.load(record.run_id)
        except StoreError:
            continue
