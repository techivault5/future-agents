"""Posting the issues — the seam a real GitHub client plugs into.

Nothing here talks to GitHub. `Publisher` is one method wide on purpose: a team
posts with whatever client, token scope and rate-limit policy they already
trust, and this package stays testable, offline and unable to create anything by
accident.

Two behaviours the ordering exists to guarantee:

* **Parents first.** A sub-issue that names `#123` needs `#123` to exist, so the
  epic is posted before its children and every child body is re-rendered with
  the number it now knows.
* **Parents again, afterwards.** The epic's task list is only complete once its
  children have numbers, so the publisher updates it — `update` is optional, and
  a publisher that cannot update simply leaves the placeholder ids, which still
  read correctly.

`DryRunPublisher` is the default everywhere. Publishing to a real tracker is an
outward-facing action, and this system does not take those on its own.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional, Protocol

from pydantic import BaseModel, Field

from future_agents.sdd.models import WorkBreakdown
from future_agents.sdd.tracking.issues import IssueBuilder, IssuePayload


class Publisher(Protocol):
    """What a poster must implement. Return the issue reference, e.g. "#123"."""

    def create(self, payload: IssuePayload) -> str:  # pragma: no cover - protocol
        ...


class SupportsUpdate(Protocol):
    def update(self, ref: str, payload: IssuePayload) -> None:  # pragma: no cover - protocol
        ...


class PublishReport(BaseModel):
    """What was posted, what it became, and what refused to go."""

    created: dict[str, str] = Field(default_factory=dict)  # work item id → issue ref
    updated: list[str] = Field(default_factory=list)
    failed: dict[str, str] = Field(default_factory=dict)  # work item id → reason
    dry_run: bool = True

    def summary(self) -> str:
        mode = "dry run" if self.dry_run else "posted"
        return (
            f"{mode}: {len(self.created)} issue(s), {len(self.updated)} updated, "
            f"{len(self.failed)} failed"
        )


class DryRunPublisher:
    """Assigns predictable fake references. The default, deliberately."""

    def __init__(self) -> None:
        self._n = 0
        self.payloads: list[IssuePayload] = []

    def create(self, payload: IssuePayload) -> str:
        self._n += 1
        self.payloads.append(payload)
        return f"#DRY-{self._n}"

    def update(self, ref: str, payload: IssuePayload) -> None:
        self.payloads.append(payload)


class JsonlPublisher:
    """Writes one JSON object per issue for an external poster to consume.

    The handoff for "I'll do the posting myself": each line is exactly what the
    create-issue call needs, plus the parent link, in parent-first order.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("")
        self._n = 0

    def create(self, payload: IssuePayload) -> str:
        self._n += 1
        ref = f"#PENDING-{self._n}"
        record = {
            "work_item_id": payload.work_item_id,
            "parent_work_item_id": payload.parent_work_item_id,
            "parent_issue": payload.parent_issue,
            "kind": payload.kind,
            **payload.to_github(),
        }
        with self.path.open("a") as handle:
            handle.write(json.dumps(record) + "\n")
        return ref


def publish_breakdown(
    breakdown: WorkBreakdown,
    builder: IssueBuilder,
    publisher: Optional[Publisher] = None,
    *,
    on_event: Optional[Callable[[str], None]] = None,
) -> PublishReport:
    """Post the tree, parents first, back-filling references as they appear."""
    poster = publisher or DryRunPublisher()
    report = PublishReport(dry_run=isinstance(poster, DryRunPublisher))

    root = breakdown.root()
    if root is None:
        return report

    ordered = [root] + _descendants(breakdown, root.id)
    for item in ordered:
        payload = builder.build(breakdown)  # re-rendered so parent refs are current
        current = next((p for p in payload if p.work_item_id == item.id), None)
        if current is None:
            report.failed[item.id] = "no payload rendered"
            continue
        try:
            ref = poster.create(current)
        except Exception as exc:  # noqa: BLE001 - a poster's failure is data, not a crash
            report.failed[item.id] = str(exc)
            continue
        item.external_ref = ref
        current.number = ref
        report.created[item.id] = ref
        if on_event:
            on_event(f"{item.id} → {ref} ({item.kind.value})")

    # The epic's task list only becomes complete once its children have numbers.
    if hasattr(poster, "update") and report.created:
        refreshed = {p.work_item_id: p for p in builder.build(breakdown)}
        for item in ordered:
            ref = report.created.get(item.id)
            payload = refreshed.get(item.id)
            if not ref or payload is None or not breakdown.children(item.id):
                continue
            try:
                poster.update(ref, payload)  # type: ignore[attr-defined]
                report.updated.append(item.id)
            except Exception as exc:  # noqa: BLE001
                report.failed[item.id] = f"update failed: {exc}"
    return report


def _descendants(breakdown: WorkBreakdown, parent_id: str) -> list:
    out = []
    for child in breakdown.children(parent_id):
        out.append(child)
        out.extend(_descendants(breakdown, child.id))
    return out
