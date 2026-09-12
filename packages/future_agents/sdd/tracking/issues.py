"""Work items → GitHub issues and sub-issues, ready to post.

The shape is GitHub's own: one **tracking issue** (the epic) whose body carries a
task list of its children, and **sub-issues** that name their parent. Task-list
lines are written as `- [ ] #123` once a child has a number and as
`- [ ] WI-004 — title` before that, which is exactly what GitHub renders as a
sub-issue reference; nothing here depends on a private API.

Bodies are written for the person who picks the issue up cold: what was asked
and by whom, why it is worth doing, what "done" means as checkboxes, where the
code goes and where it must not, what will be measured, and the ids that let any
of it be traced back. Everything is derived — there is no free-text field for a
model to fill with confident prose nobody checked.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from future_agents.sdd.models import (
    MetricSet,
    ObservabilityPlan,
    QAReport,
    Spec,
    WorkBreakdown,
    WorkItem,
    WorkItemKind,
)

#: GitHub rejects bodies over 65536 characters. Truncating in the renderer beats
#: discovering it in the poster's error handler.
MAX_BODY = 60000


class IssuePayload(BaseModel):
    """One issue, in the shape a poster hands to the GitHub API."""

    work_item_id: str
    title: str
    body: str
    labels: list[str] = Field(default_factory=list)
    assignees: list[str] = Field(default_factory=list)
    parent_work_item_id: str = ""
    parent_issue: str = ""  # "#123" once the parent exists
    number: str = ""  # filled in by the publisher after posting
    kind: str = ""

    def to_github(self) -> dict[str, object]:
        """The create-issue payload. `parent` is carried alongside, because the
        sub-issue link is a second call in GitHub's API, not a body field."""
        return {
            "title": self.title,
            "body": self.body[:MAX_BODY],
            "labels": list(self.labels),
            "assignees": list(self.assignees),
        }


class IssueBuilder:
    """Renders a breakdown as a tracking issue plus its sub-issues."""

    def __init__(
        self,
        spec: Optional[Spec] = None,
        observability: Optional[ObservabilityPlan] = None,
        metrics: Optional[MetricSet] = None,
        qa: Optional[QAReport] = None,
        docs_path: str = "",
    ) -> None:
        self.spec = spec
        self.observability = observability
        self.metrics = metrics
        self.qa = qa
        self.docs_path = docs_path

    def build(self, breakdown: WorkBreakdown) -> list[IssuePayload]:
        """Parents before children, so a publisher can post in list order."""
        payloads: list[IssuePayload] = []
        root = breakdown.root()
        if root is None:
            return payloads
        payloads.append(self._payload(root, breakdown))
        for item in _depth_first(breakdown, root.id):
            payloads.append(self._payload(item, breakdown))
        return payloads

    # ── One issue ─────────────────────────────────────────────────────────────

    def _payload(self, item: WorkItem, breakdown: WorkBreakdown) -> IssuePayload:
        body = (
            self._epic_body(item, breakdown)
            if item.kind is WorkItemKind.EPIC
            else self._item_body(item, breakdown)
        )
        parent = breakdown.by_id(item.parent_id) if item.parent_id else None
        return IssuePayload(
            work_item_id=item.id,
            title=item.render_title(),
            body=body,
            labels=list(item.labels),
            kind=item.kind.value,
            parent_work_item_id=parent.id if parent else "",
            parent_issue=parent.external_ref if parent else "",
        )

    def _epic_body(self, epic: WorkItem, breakdown: WorkBreakdown) -> str:
        lines = [
            "## Objective",
            "",
            epic.intent or epic.title,
            "",
        ]
        if epic.outcome:
            lines += [f"**So that** {epic.outcome}", ""]
        lines += self._provenance(epic)

        if self.spec is not None:
            lines += ["## Requirements", ""]
            for requirement in self.spec.requirements:
                lines.append(
                    f"- `{requirement.id}` **{requirement.priority.value}** — "
                    f"{requirement.statement}"
                )
            if self.spec.out_of_scope:
                lines += ["", "**Out of scope:** " + "; ".join(self.spec.out_of_scope)]
            if self.spec.assumptions:
                lines += ["", "**Assumed (unconfirmed):**"]
                lines += [f"- {a.statement} — _{a.basis}_" for a in self.spec.assumptions[:5]]
            lines.append("")

        lines += ["## Sub-issues", ""]
        lines += _task_list(breakdown, epic.id)
        lines.append("")

        if self.observability is not None and self.observability.slos:
            lines += ["## How we will know it works", ""]
            lines += [f"- `{slo.id}` {slo.render()}" for slo in self.observability.slos]
            lines += ["", f"Runbook: `{self.observability.runbook_path}`", ""]

        if self.metrics is not None and self.metrics.specs:
            # The epic's own numbers, then a count per family. Pasting every
            # child's metric here would bury the three that matter.
            own = MetricSet(specs=self.metrics.for_item(epic.id))
            lines += ["## Metrics", ""] + (own.table() if own.specs else []) + [""]
            families: dict[str, int] = {}
            for metric in self.metrics.specs:
                families[metric.kind.value] = families.get(metric.kind.value, 0) + 1
            rollup = ", ".join(f"{count} {kind}" for kind, count in sorted(families.items()))
            unbound = sum(1 for m in self.metrics.specs if m.source == "unbound")
            lines += [
                f"Across every sub-issue: {rollup}."
                + (f" {unbound} still need a data source." if unbound else ""),
                "",
            ]

        lines += self._done_block(epic)
        lines += self._qa_block()
        lines += self._footer(epic)
        return "\n".join(lines)

    def _item_body(self, item: WorkItem, breakdown: WorkBreakdown) -> str:
        parent = breakdown.by_id(item.parent_id)
        lines: list[str] = []
        if parent is not None:
            ref = parent.external_ref or parent.id
            lines += [f"Parent: {ref} — {parent.title}", ""]

        lines += ["## Intent", "", item.intent or item.title, ""]
        if item.outcome:
            lines += [f"**So that** {item.outcome}", ""]
        if item.description and item.description != item.intent:
            lines += [item.description, ""]

        criteria = self._criteria(item)
        if criteria:
            lines += ["## Acceptance criteria", ""] + criteria + [""]

        implementation = self._implementation(item)
        if implementation:
            lines += ["## Implementation", ""] + implementation + [""]

        children = breakdown.children(item.id)
        if children:
            lines += ["## Sub-issues", ""] + _task_list(breakdown, item.id) + [""]

        if item.task_ids:
            runs = ", ".join(f"`{t}`" for t in item.task_ids)
            lines += ["## Pipeline tasks", "", f"Runs as: {runs}", ""]

        telemetry = self._telemetry(item)
        if telemetry:
            lines += ["## Observability", ""] + telemetry + [""]

        item_metrics = self.metrics.for_item(item.id) if self.metrics else []
        if item_metrics:
            lines += ["## Metrics", ""]
            lines += [
                f"- `{m.id}` **{m.name}** — {m.question} "
                f"({m.kind.value}, source: {m.source or 'unbound'})"
                for m in item_metrics
            ]
            lines.append("")

        lines += self._done_block(item)
        lines += self._footer(item)
        return "\n".join(lines)

    # ── Blocks ────────────────────────────────────────────────────────────────

    def _provenance(self, item: WorkItem) -> list[str]:
        """Who asked, from where. An issue without this is an issue nobody owns."""
        rows = [
            "| | |",
            "|---|---|",
            f"| **Requested by** | {item.requested_by or 'unknown'} |",
            f"| **Source** | {item.source or 'chat'} |",
        ]
        if item.source_url:
            rows.append(f"| **Link** | {item.source_url} |")
        if item.component:
            rows.append(f"| **Component** | `{item.component}` |")
        rows.append(f"| **Risk** | {item.risk} |")
        if item.estimate:
            rows.append(f"| **Size** | {item.estimate} |")
        if self.docs_path:
            rows.append(f"| **Project doc** | `{self.docs_path}` |")
        return rows + [""]

    def _criteria(self, item: WorkItem) -> list[str]:
        """Given/When/Then as checkboxes — the definition, not a paraphrase."""
        if self.spec is None:
            return [f"- [ ] `{cid}`" for cid in item.criterion_ids]
        out: list[str] = []
        for criterion in self.spec.criteria():
            if criterion.id in item.criterion_ids:
                out.append(f"- [ ] `{criterion.id}` {criterion.render()}")
        return out

    def _implementation(self, item: WorkItem) -> list[str]:
        out: list[str] = []
        if item.target_paths:
            out.append("Goes in: " + ", ".join(f"`{p}`" for p in item.target_paths))
        if item.forbidden_paths:
            out.append("Must **not** go in: " + ", ".join(f"`{p}`" for p in item.forbidden_paths))
        if item.depends_on:
            out.append("Blocked by: " + ", ".join(item.depends_on))
        if item.capability_id:
            out.append(f"Delivers capability `{item.capability_id}`")
        return out

    def _telemetry(self, item: WorkItem) -> list[str]:
        out: list[str] = []
        if self.observability is None:
            return [f"- `{sid}`" for sid in item.signal_ids + item.slo_ids]
        for signal_id in item.signal_ids:
            signal = self.observability.signal(signal_id)
            if signal is not None:
                out.append(f"- {signal.render()}")
        for slo_id in item.slo_ids:
            slo = next((s for s in self.observability.slos if s.id == slo_id), None)
            if slo is not None:
                out.append(f"- {slo.render()}")
        return out

    @staticmethod
    def _done_block(item: WorkItem) -> list[str]:
        if not item.definition_of_done:
            return []
        return (
            ["## Definition of done", ""]
            + [f"- [ ] {line}" for line in item.definition_of_done]
            + [""]
        )

    def _qa_block(self) -> list[str]:
        if self.qa is None:
            return []
        lines = ["## QA", "", f"Verdict: **{self.qa.verdict.value.upper()}**"]
        if self.qa.simulated:
            lines.append("_Simulated run — nothing actually executed._")
        lines += [
            f"- MUST coverage: {self.qa.coverage:.0%}",
            f"- Instrumentation executed: {self.qa.observability_coverage:.0%}",
        ]
        blockers = [f for f in self.qa.findings if f.severity == "blocker"]
        if blockers:
            lines += ["", "Blockers:"] + [f"- {f.summary}" for f in blockers[:5]]
        return lines + [""]

    @staticmethod
    def _footer(item: WorkItem) -> list[str]:
        """Traceability, last, so it never crowds out what a human reads first."""
        bits = [f"`{item.id}`"]
        if item.requirement_ids:
            bits.append("requirements " + ", ".join(f"`{r}`" for r in item.requirement_ids))
        if item.criterion_ids:
            bits.append(f"{len(item.criterion_ids)} criteria")
        if item.task_ids:
            bits.append("tasks " + ", ".join(f"`{t}`" for t in item.task_ids))
        return [
            "---",
            "",
            "Traceability: " + " · ".join(bits),
            "",
            "_Opened by spec-driven delivery._",
        ]


def _task_list(breakdown: WorkBreakdown, parent_id: str) -> list[str]:
    """GitHub's sub-issue syntax: `- [ ] #123` once known, the id before that."""
    lines: list[str] = []
    for child in breakdown.children(parent_id):
        marker = "x" if child.status.value == "done" else " "
        ref = child.external_ref or f"`{child.id}`"
        lines.append(f"- [{marker}] {ref} — {child.render_title()}")
    return lines or ["_No sub-issues._"]


def _depth_first(breakdown: WorkBreakdown, parent_id: str) -> list[WorkItem]:
    out: list[WorkItem] = []
    for child in breakdown.children(parent_id):
        out.append(child)
        out.extend(_depth_first(breakdown, child.id))
    return out
