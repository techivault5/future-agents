"""Intake adapters — any ticket, from any system, becomes one Objective.

Each adapter takes the payload a tracker already produces (a GitHub webhook, a
Jira issue, a Linear issue, a Slack message, a meeting transcript) and maps it
onto the pipeline's only un-derived artifact. Three things every adapter does:

* carry an `ExternalRef`, so the same ticket never starts two runs,
* sanitise the human text, because it arrived from outside,
* keep the original payload on `metadata` — the record must stay complete.

Adapters take payloads rather than fetching them: the network client, its auth
and its rate limits belong to the caller, and that keeps intake testable.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional, Protocol, runtime_checkable

from future_agents.sdd.intake.sanitize import sanitize, sanitize_many
from future_agents.sdd.models import ExternalRef, IntakeSource, Objective

# Labels a tracker uses that mean something to the pipeline.
_PRIORITY_LABELS = {"p0", "p1", "critical", "urgent", "blocker"}
_CONSTRAINT_HINTS = ("no-", "must-", "without-", "keep-", "requires-")
_ACCEPTANCE_HEADINGS = re.compile(
    r"(?im)^\s*#{0,4}\s*(acceptance criteria|definition of done|dod|success criteria)\s*:?\s*$"
)
_SECTION = re.compile(r"(?im)^\s*#{1,4}\s+(.+?)\s*$")


@runtime_checkable
class IntakeAdapter(Protocol):
    """Anything that turns a payload into an Objective."""

    system: str

    def matches(self, payload: dict[str, Any]) -> bool: ...  # pragma: no cover - protocol

    def to_objective(self, payload: dict[str, Any]) -> Objective: ...  # pragma: no cover


class _BaseAdapter:
    system = "generic"
    source = IntakeSource.TICKET

    def matches(self, payload: dict[str, Any]) -> bool:  # pragma: no cover - overridden
        return False

    # ── Shared mapping ────────────────────────────────────────────────────────

    def _build(
        self,
        *,
        title: str,
        body: str,
        ref: ExternalRef,
        submitted_by: str,
        payload: dict[str, Any],
        deadline: Optional[str] = None,
        extra_inputs: Optional[list[str]] = None,
    ) -> Objective:
        clean_title = sanitize(title, max_chars=400)
        clean_body = sanitize(body)
        inputs, removed_inputs = sanitize_many(extra_inputs or [])
        removed = [*clean_title.removed, *clean_body.removed, *removed_inputs]

        acceptance = _acceptance_lines(clean_body.text)
        raw_inputs = [line for line in _body_lines(clean_body.text) if line]
        raw_inputs.extend(inputs)

        objective = Objective(
            statement=clean_title.text.strip() or _first_line(clean_body.text),
            context=_context_of(clean_body.text),
            source=self.source,
            submitted_by=submitted_by or ref.author or "unknown",
            raw_inputs=raw_inputs + acceptance,
            constraints=_constraints_from_labels(ref.labels),
            deadline=deadline,
            external=ref,
            untrusted=True,
            metadata={
                "adapter": self.system,
                "removed_by_sanitizer": removed,
                "body_digest": clean_body.original_digest,
                "raw_payload": json.dumps(payload, default=str)[:8000],
            },
        )
        return objective


class GitHubIssueAdapter(_BaseAdapter):
    """GitHub issue or issue-comment webhook payloads, and plain issue JSON."""

    system = "github"

    def matches(self, payload: dict[str, Any]) -> bool:
        issue = payload.get("issue") or payload
        return "github.com" in str(issue.get("html_url", ""))

    def to_objective(self, payload: dict[str, Any]) -> Objective:
        issue = payload.get("issue") or payload
        repo = payload.get("repository", {}).get("full_name", "")
        number = issue.get("number", "")
        labels = [
            label.get("name", "") if isinstance(label, dict) else str(label)
            for label in issue.get("labels", [])
        ]
        ref = ExternalRef(
            system=self.system,
            id=f"{repo}#{number}" if repo else str(number),
            url=issue.get("html_url", ""),
            author=(issue.get("user") or {}).get("login", ""),
            labels=[label for label in labels if label],
        )
        comments = [c.get("body", "") for c in payload.get("comments", []) if isinstance(c, dict)]
        return self._build(
            title=issue.get("title", ""),
            body=issue.get("body") or "",
            ref=ref,
            submitted_by=ref.author,
            payload=payload,
            deadline=(issue.get("milestone") or {}).get("due_on"),
            extra_inputs=comments,
        )


class JiraAdapter(_BaseAdapter):
    """Jira issue JSON (`fields` shaped), including webhook envelopes."""

    system = "jira"

    def matches(self, payload: dict[str, Any]) -> bool:
        issue = payload.get("issue") or payload
        return "fields" in issue and "key" in issue

    def to_objective(self, payload: dict[str, Any]) -> Objective:
        issue = payload.get("issue") or payload
        fields = issue.get("fields", {})
        reporter = (fields.get("reporter") or {}).get("displayName", "")
        ref = ExternalRef(
            system=self.system,
            id=issue.get("key", ""),
            url=issue.get("self", ""),
            author=reporter,
            labels=list(fields.get("labels", []))
            + ([fields.get("priority", {}).get("name", "")] if fields.get("priority") else []),
        )
        description = fields.get("description") or ""
        if isinstance(description, dict):  # Atlassian document format
            description = _flatten_adf(description)
        comments = [
            c.get("body", "")
            for c in (fields.get("comment", {}) or {}).get("comments", [])
            if isinstance(c, dict)
        ]
        return self._build(
            title=fields.get("summary", ""),
            body=str(description),
            ref=ref,
            submitted_by=reporter,
            payload=payload,
            deadline=fields.get("duedate"),
            extra_inputs=[str(c) for c in comments],
        )


class LinearAdapter(_BaseAdapter):
    """Linear issue payloads."""

    system = "linear"

    def matches(self, payload: dict[str, Any]) -> bool:
        data = payload.get("data") or payload
        return "identifier" in data and "title" in data

    def to_objective(self, payload: dict[str, Any]) -> Objective:
        data = payload.get("data") or payload
        creator = (data.get("creator") or {}).get("name", "")
        ref = ExternalRef(
            system=self.system,
            id=data.get("identifier", ""),
            url=data.get("url", ""),
            author=creator,
            labels=[
                label.get("name", "") for label in data.get("labels", []) if isinstance(label, dict)
            ],
        )
        return self._build(
            title=data.get("title", ""),
            body=data.get("description") or "",
            ref=ref,
            submitted_by=creator,
            payload=payload,
            deadline=data.get("dueDate"),
        )


class SlackAdapter(_BaseAdapter):
    """A Slack message (or a thread) asking for work."""

    system = "slack"
    source = IntakeSource.CHAT

    def matches(self, payload: dict[str, Any]) -> bool:
        event = payload.get("event") or payload
        return "text" in event and ("ts" in event or "channel" in event)

    def to_objective(self, payload: dict[str, Any]) -> Objective:
        event = payload.get("event") or payload
        ref = ExternalRef(
            system=self.system,
            id=f"{event.get('channel', 'channel')}:{event.get('ts', '')}",
            url=event.get("permalink", ""),
            author=event.get("user_name") or event.get("user", ""),
        )
        thread = [m.get("text", "") for m in payload.get("thread", []) if isinstance(m, dict)]
        return self._build(
            title=_first_line(event.get("text", "")),
            body=event.get("text", ""),
            ref=ref,
            submitted_by=ref.author,
            payload=payload,
            extra_inputs=thread,
        )


class TranscriptAdapter(_BaseAdapter):
    """A meeting transcript, with or without speaker attribution."""

    system = "transcript"
    source = IntakeSource.MEETING

    def matches(self, payload: dict[str, Any]) -> bool:
        return "transcript" in payload or payload.get("kind") == "meeting"

    def to_objective(self, payload: dict[str, Any]) -> Objective:
        transcript = payload.get("transcript") or payload.get("text", "")
        ref = ExternalRef(
            system=self.system,
            id=payload.get("id", "") or payload.get("meeting_id", ""),
            url=payload.get("url", ""),
            author=payload.get("organizer", ""),
        )
        return self._build(
            title=payload.get("title", "") or payload.get("subject", ""),
            body=str(transcript),
            ref=ref,
            submitted_by=payload.get("organizer", ""),
            payload=payload,
            deadline=payload.get("deadline"),
        )


class GenericTicketAdapter(_BaseAdapter):
    """Anything with a title and a description. The fallback that always works."""

    system = "webhook"

    def matches(self, payload: dict[str, Any]) -> bool:
        return bool(payload.get("title") or payload.get("summary") or payload.get("statement"))

    def to_objective(self, payload: dict[str, Any]) -> Objective:
        ref = ExternalRef(
            system=payload.get("system", self.system),
            id=str(payload.get("id", "")),
            url=payload.get("url", ""),
            author=payload.get("author", ""),
            labels=[str(label) for label in payload.get("labels", [])],
        )
        return self._build(
            title=payload.get("title") or payload.get("summary") or payload.get("statement", ""),
            body=payload.get("description") or payload.get("body", ""),
            ref=ref,
            submitted_by=payload.get("author", ""),
            payload=payload,
            deadline=payload.get("deadline"),
        )


ADAPTERS: tuple[_BaseAdapter, ...] = (
    GitHubIssueAdapter(),
    JiraAdapter(),
    LinearAdapter(),
    TranscriptAdapter(),
    SlackAdapter(),
    GenericTicketAdapter(),
)


def detect_adapter(payload: dict[str, Any]) -> _BaseAdapter:
    """First adapter that recognises the payload; the generic one always does."""
    for adapter in ADAPTERS:
        try:
            if adapter.matches(payload):
                return adapter
        except (AttributeError, TypeError):
            continue
    return ADAPTERS[-1]


def objective_from_payload(payload: dict[str, Any], system: str = "") -> Objective:
    """Turn any supported ticket payload into an Objective."""
    if system:
        adapter = next((a for a in ADAPTERS if a.system == system), ADAPTERS[-1])
    else:
        adapter = detect_adapter(payload)
    return adapter.to_objective(payload)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _body_lines(body: str) -> list[str]:
    return [line.strip() for line in body.splitlines() if len(line.strip()) > 7]


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:200]
    return ""


def _context_of(body: str) -> str:
    """The prose before the first heading — the 'why' a ticket opens with."""
    lines: list[str] = []
    for line in body.splitlines():
        if _SECTION.match(line):
            break
        lines.append(line)
    return "\n".join(lines).strip()[:2000]


def _acceptance_lines(body: str) -> list[str]:
    """Bullets under an 'acceptance criteria' heading become requirements."""
    match = _ACCEPTANCE_HEADINGS.search(body)
    if not match:
        return []
    out: list[str] = []
    for line in body[match.end() :].splitlines():
        stripped = line.strip()
        if _SECTION.match(line):
            break
        if stripped.startswith(("-", "*", "•")) or re.match(r"^\d+[.)]", stripped):
            cleaned = re.sub(r"^[-*•\d.)\s\[\]x ]+", "", stripped).strip()
            if len(cleaned) > 5:
                out.append(f"must {cleaned}" if not _has_modal(cleaned) else cleaned)
    return out


def _has_modal(text: str) -> bool:
    return bool(re.search(r"(?i)\b(must|should|shall|will|needs? to)\b", text))


def _constraints_from_labels(labels: list[str]) -> list[str]:
    constraints: list[str] = []
    for label in labels:
        low = label.lower().strip()
        if not low:
            continue
        if low in _PRIORITY_LABELS:
            constraints.append(f"priority label '{label}' — treat as time-critical")
        elif low.startswith(_CONSTRAINT_HINTS):
            constraints.append(label.replace("-", " "))
    return constraints


def _flatten_adf(node: Any) -> str:
    """Atlassian document format → plain text."""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(_flatten_adf(item) for item in node)
    if isinstance(node, dict):
        text = node.get("text", "")
        children = _flatten_adf(node.get("content", []))
        return "\n".join(part for part in (text, children) if part)
    return ""
