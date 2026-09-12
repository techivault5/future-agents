"""Untrusted text — everything that arrives from outside the system.

A ticket body, a Slack message, a retrieved document and a memory case are all
written by someone else. They are *data*, and the moment they are pasted into a
prompt they become an instruction channel. This module strips the phrasings that
try to use that channel, records what it removed, and never silently drops the
original — which stays on the objective's metadata for a human to read.

This is not a security boundary on its own. It is the cheap layer that stops the
obvious attempts; the real boundaries are the constitution gates, the sandbox
path fences and the fact that no stage lets model output decide structure.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

#: Phrasings whose only purpose is to redirect an agent reading the text.
INJECTION_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        r"(?i)\bignore (?:all |any )?(?:previous|prior|above|earlier) (?:instructions?|prompts?)\b",
        "instruction override",
    ),
    (r"(?i)\bdisregard (?:the )?(?:previous|above|system)\b", "instruction override"),
    (
        r"(?i)\byou are (?:now )?(?:a|an|the)\b.{0,60}\b(?:assistant|agent|model|ai)\b",
        "role reassignment",
    ),
    (r"(?i)^\s*(?:system|assistant|developer)\s*:", "fake role marker"),
    (r"(?i)<\/?(?:system|assistant|instructions?|tool_use)>", "fake role tag"),
    (r"(?i)\bnew (?:system )?(?:instructions?|rules?)\s*:", "instruction override"),
    (
        r"(?i)\b(?:reveal|print|show|output)\b.{0,40}"
        r"\b(?:system prompt|instructions|secrets?|api[ _-]?key|token|credential)",
        "secret exfiltration",
    ),
    (
        r"(?i)\b(?:do not|don'?t|never)\s+(?:tell|inform|ask|notify)\s+"
        r"(?:the )?(?:user|human|operator)\b",
        "human bypass",
    ),
    (
        r"(?i)\bwithout (?:asking|telling|informing) (?:the )?(?:user|human|anyone)\b",
        "human bypass",
    ),
    (
        r"(?i)\b(?:skip|bypass|disable|turn off)\b.{0,30}"
        r"\b(?:tests?|checks?|guardrails?|review|approval|ci)\b",
        "gate bypass",
    ),
    (r"(?i)\bcurl\b.{0,60}\|\s*(?:ba)?sh\b", "remote code execution"),
    (r"(?i)\brm\s+-rf\s+/", "destructive command"),
)

_REDACTION = "[removed: {reason}]"


class SanitizedText(BaseModel):
    """The safe text, plus exactly what was taken out and why."""

    text: str
    removed: list[str] = Field(default_factory=list)
    original_digest: str = ""

    @property
    def clean(self) -> bool:
        return not self.removed


def sanitize(text: str, *, max_chars: int = 20000) -> SanitizedText:
    """Neutralise instruction-shaped content and cap runaway length."""
    from future_agents.sdd.models import Evidence

    if not text:
        return SanitizedText(text="", original_digest="")

    digest = Evidence.digest(text)
    removed: list[str] = []
    cleaned = text

    for pattern, reason in INJECTION_PATTERNS:
        cleaned, count = re.subn(pattern, _REDACTION.format(reason=reason), cleaned, flags=re.M)
        if count:
            removed.append(f"{reason} ×{count}")

    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars] + f"\n[truncated at {max_chars} characters]"
        removed.append("oversized input truncated")

    return SanitizedText(text=cleaned, removed=removed, original_digest=digest)


def sanitize_many(values: list[str], *, max_chars: int = 20000) -> tuple[list[str], list[str]]:
    """Sanitise a list, returning the cleaned values and everything removed."""
    cleaned: list[str] = []
    removed: list[str] = []
    for value in values:
        result = sanitize(value, max_chars=max_chars)
        cleaned.append(result.text)
        removed.extend(result.removed)
    return cleaned, removed
