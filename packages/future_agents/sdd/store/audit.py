"""Audit log — append-only JSONL of everything the system decided or changed.

Not observability (that is metrics); provenance. When someone asks 'why did an
agent touch this file', the answer has to exist after the process is gone.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from pydantic import BaseModel, Field

from future_agents.sdd.store.run_store import DEFAULT_ROOT


class AuditEvent(BaseModel):
    at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    actor: str  # worker id, agent id, or "human:<name>"
    action: str  # claimed | assigned | executed | gated | delivered | escalated
    subject: str = ""  # run id, task id, path
    detail: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class AuditLog:
    """Append-only. Never rewritten, never compacted in place."""

    def __init__(self, root: str | Path = DEFAULT_ROOT, name: str = "audit.jsonl") -> None:
        self.path = Path(root) / name
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self, actor: str, action: str, subject: str = "", detail: str = "", **data: Any
    ) -> AuditEvent:
        event = AuditEvent(actor=actor, action=action, subject=subject, detail=detail, data=data)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.model_dump(mode="json"), default=str) + "\n")
        return event

    def read(self, subject: Optional[str] = None, limit: int = 200) -> list[AuditEvent]:
        if not self.path.is_file():
            return []
        events: list[AuditEvent] = []
        for line in self.path.read_text(errors="ignore").splitlines():
            if not line.strip():
                continue
            try:
                event = AuditEvent.model_validate(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                continue
            if subject and event.subject != subject:
                continue
            events.append(event)
        return events[-limit:]

    def trail(self, subject: str) -> Iterable[str]:
        for event in self.read(subject=subject):
            yield f"{event.at.isoformat()}  {event.actor:24s} {event.action:12s} {event.detail}"
