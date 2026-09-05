"""Shared extraction rules — how prose becomes requirements, criteria and components.

Kept in one place so the PM and Architect stages read the same phrasing the same
way."""

from __future__ import annotations

import re
from typing import Optional

from future_agents.sdd.models import (
    AcceptanceCriterion,
    ClarificationResult,
    Component,
    Objective,
    Priority,
    Spec,
)

_ACTION = re.compile(
    r"\b(must|shall|should|needs? (?:to|a|the)?|we (?:need|want)|require[sd]?|"
    r"action item|todo|will)\b",
    re.IGNORECASE,
)


_IMPERATIVE = re.compile(
    r"^(add|build|create|send|expose|ensure|support|generate|remove|update|migrate|"
    r"integrate|alert|flag|show|display|store|track|schedule|deliver|replace|enable|"
    r"restrict|log|export|import|sync|notify|document)\b",
    re.IGNORECASE,
)


_MUST = re.compile(r"\b(must|shall|required|blocker|critical)\b", re.IGNORECASE)


_COULD = re.compile(r"\b(could|nice to have|maybe|optional|stretch)\b", re.IGNORECASE)


# Scope declarations only. The bare verb "exclude" is domain language — a ticket
# about excluding refunds from a total is not a ticket about scope.
_OUT_OF_SCOPE = re.compile(
    r"\b(out[- ]of[- ]scope|not in scope|won'?t (?:do|cover|ship)|non[- ]goals?|"
    r"explicitly excluded|excluded from (?:this|the) (?:scope|phase|release|ticket|change)|"
    r"later phase|future phase|out of this (?:phase|release))\b",
    re.IGNORECASE,
)


_SO_THAT = re.compile(r"\bso that\b(.+)$", re.IGNORECASE)


_METRIC = re.compile(
    r"[^.\n]*?\d+\s*(?:%|percent|ms|sec|min|hours?|days?|rps|qps|users?|records?)[^.\n]*",
    re.IGNORECASE,
)


_SPEAKER = re.compile(r"^\s*(?:[-*]\s*)?(?:\[[\d:]+\]\s*)?([A-Z][\w .'-]{1,30}):\s*(.+)$")


_DOMAINS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("auth", ("login", "auth", "sso", "permission", "role", "token", "session")),
    ("api", ("api", "endpoint", "rest", "graphql", "webhook", "request")),
    ("data", ("data", "database", "schema", "etl", "pipeline", "warehouse", "record")),
    ("ui", ("ui", "screen", "page", "dashboard", "button", "form", "view")),
    ("notification", ("notify", "notification", "email", "alert", "slack", "message")),
    ("reporting", ("report", "export", "metric", "analytics", "chart")),
    ("infra", ("deploy", "pipeline", "ci", "cd", "infrastructure", "terraform", "container")),
)


def _candidate_lines(objective: Objective) -> list[tuple[str, bool]]:
    """Lines worth reading, each flagged as speaker-attributed or not."""
    lines: list[tuple[str, bool]] = [(objective.statement, False)]
    for block in [objective.context, *objective.raw_inputs]:
        for raw in block.splitlines():
            line = raw.strip()
            if len(line) < 8:
                continue
            speaker = _SPEAKER.match(line)
            lines.append((speaker.group(2).strip(), True) if speaker else (line, False))
    return [(text, attributed) for text, attributed in lines if text]


def _dedupe_lines(lines: list[str], similarity: float = 0.7) -> list[str]:
    """Drop exact repeats and near-repeats — a transcript restates the ask often."""
    seen: set[str] = set()
    kept_tokens: list[set[str]] = []
    out: list[str] = []
    for line in lines:
        key = re.sub(r"\W+", "", line.lower())
        if not key or key in seen:
            continue
        tokens = {w for w in re.findall(r"[a-z]{3,}", line.lower())}
        if tokens and any(
            len(tokens & prior) / len(tokens | prior) >= similarity for prior in kept_tokens
        ):
            continue
        seen.add(key)
        kept_tokens.append(tokens)
        out.append(line)
    return out


def _clean(line: str) -> str:
    return re.sub(r"^[-*\d.)\s]+", "", line).strip()


def _priority(statement: str) -> Priority:
    if _COULD.search(statement):
        return Priority.COULD
    if _MUST.search(statement):
        return Priority.MUST
    return Priority.SHOULD if re.search(r"\bshould\b", statement, re.I) else Priority.MUST


def _rationale(statement: str) -> str:
    match = _SO_THAT.search(statement)
    return match.group(1).strip().rstrip(".") if match else ""


def _criterion(req_id: str, statement: str, objective: Objective) -> AcceptanceCriterion:
    outcome = _rationale(statement) or _clean(statement)
    given = (
        objective.context.strip().splitlines()[0]
        if objective.context.strip()
        else "the system is in its normal state"
    )
    return AcceptanceCriterion(
        id=f"{req_id}-AC-001",
        given=_short(given, 120),
        when=_short(_clean(statement), 120),
        then=_short(outcome, 120),
    )


def _metrics(objective: Objective, answers: str) -> list[str]:
    blob = "\n".join([text for text, _ in _candidate_lines(objective)] + [answers])
    return _dedupe_lines([m.group(0).strip() for m in _METRIC.finditer(blob)])[:5]


def _answer_context(clarification: Optional[ClarificationResult]) -> str:
    if not clarification:
        return ""
    return "\n".join(f"{q.text} → {q.answer}" for q in clarification.questions if q.answered)


def _components(spec: Spec) -> list[Component]:
    buckets: dict[str, list[str]] = {}
    for requirement in spec.requirements:
        name = _domain(requirement.statement)
        buckets.setdefault(name, []).append(requirement.id)
    return [
        Component(
            name=name,
            responsibility=f"satisfies {', '.join(req_ids)}",
            requirement_ids=req_ids,
        )
        for name, req_ids in sorted(buckets.items())
    ]


def _domain(statement: str) -> str:
    low = statement.lower()
    for name, keywords in _DOMAINS:
        if any(re.search(rf"\b{re.escape(k)}\b", low) for k in keywords):
            return name
    return "core"


def _title(statement: str) -> str:
    return _short(_clean(statement), 72)


def _short(text: str, limit: int = 48) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
