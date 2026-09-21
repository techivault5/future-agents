"""Two explanations for every failure, and one of them is redacted.

A person who asks a question and gets `Invalid column name 'employe_id'` learns
nothing they can act on. A person who gets "something went wrong" learns less.
So every failure produces both:

    business   what happened, in the words of the job rather than the database,
               and what it means for the number they were expecting.
    technical  the engine's own message, verbatim, plus the SQL. The person who
               has to fix it needs the real string, not a paraphrase.

And an acknowledgement, because a failure the system is already working on is a
different thing from one nobody knows about.

**The technical layer is not always safe to show.** Three of six engines merge
"you may not see it" into "it does not exist", on purpose, so you cannot probe
for object existence. Relaying `Invalid object name 'payroll.dbo.exec_comp'`
verbatim to someone who is not entitled to that table undoes, in the
presentation layer, the metadata hiding the database does deliberately. So the
technical layer is redacted for permission failures and for not-found on
objects outside the asker's catalog, and shown in full only to operators or to
people entitled to the object.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml

    HAS_YAML = True
except ImportError:  # pragma: no cover
    HAS_YAML = False

from beta_queries.sql.healing import Diagnosis, plan_repair

REDACTED = (
    "The details of this failure are withheld because they would reveal "
    "whether an object you cannot access exists. Your data owner can see them."
)

# Kinds where the engine's own words may name something the asker is not
# entitled to know about.
_SENSITIVE = frozenset({"permission_denied", "unknown_table"})

# The engines that deliberately merge denied into not-found. On these, a
# not-found is never conclusive and its text is never safe to relay.
_MERGES_DENIED_INTO_NOT_FOUND = frozenset({"snowflake", "sqlserver", "mysql"})

DEFAULT_MESSAGES: dict[str, dict[str, str]] = {
    "unknown_column": {
        "business": "One of the fields this question needs isn't in that table any "
        "more — it looks like the table changed since I last read it.",
        "what_now": "I've raised this and I'm re-reading that database now. "
        "I'll tell you when it's ready to try again.",
    },
    "unknown_table": {
        "business": "I couldn't find the table this question needs. Either it has "
        "moved, or it isn't part of what you have access to.",
        "what_now": "I've raised this with whoever looks after that database.",
    },
    "permission_denied": {
        "business": "You don't have access to the data needed to answer that.",
        "what_now": "Your data owner has to grant it — I can't work around it, "
        "and I wouldn't want to.",
    },
    "timeout": {
        "business": "That question covers more data than we can read in one go, "
        "so it was stopped rather than left running.",
        "what_now": "Narrowing the period or adding a filter usually fixes it.",
    },
    "too_many_rows": {
        "business": "That would return more rows than this can show at once.",
        "what_now": "Add a filter, or ask for a total instead of a list.",
    },
    "connection": {
        "business": "I couldn't reach that database just now. This is an "
        "infrastructure problem, not a problem with your question.",
        "what_now": "It's usually brief — try again shortly.",
    },
    "missing_group_by": {
        "business": "I wrote the query in a way the database rejected — every "
        "column has to be either grouped or summarised.",
        "what_now": "I'm correcting it now.",
    },
    "type_mismatch": {
        "business": "I compared two fields the database considers different "
        "types, so it refused to run it.",
        "what_now": "I'm correcting it now.",
    },
    "date_format": {
        "business": "A date in that question wasn't in a form the database accepted.",
        "what_now": "I'm correcting it now.",
    },
    "division_by_zero": {
        "business": "The calculation divided by zero — usually because the group "
        "being divided by had no rows.",
        "what_now": "I'm correcting it to guard the denominator.",
    },
    "syntax": {
        "business": "I wrote a query the database couldn't parse.",
        "what_now": "I'm rewriting it once. If it fails again I'll show you what "
        "I tried rather than keep guessing.",
    },
    "unknown": {
        "business": "The database refused that query and the reason isn't one I recognise.",
        "what_now": "I've recorded it. The exact message is below for whoever "
        "looks after this database.",
    },
}


@dataclass
class ErrorReport:
    kind: str
    business: str
    technical: str
    what_now: str
    stage: str = "execute"
    retryable: bool = False
    needs_user: bool = False
    incident_id: str = ""
    redacted: bool = False
    suggestions: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "business": self.business,
            "technical": self.technical,
            "what_now": self.what_now,
            "stage": self.stage,
            "retryable": self.retryable,
            "needs_user": self.needs_user,
            "incident_id": self.incident_id,
            "redacted": self.redacted,
            "suggestions": self.suggestions,
        }


class ErrorMessages:
    """The wording, loaded from config so a product owner owns it."""

    def __init__(self, messages: dict[str, dict[str, str]] | None = None) -> None:
        self.messages = dict(DEFAULT_MESSAGES)
        for kind, spec in (messages or {}).items():
            self.messages[kind] = {**self.messages.get(kind, {}), **spec}

    @classmethod
    def from_file(cls, path: str | Path) -> ErrorMessages:
        if not HAS_YAML:  # pragma: no cover
            return cls()
        data = yaml.safe_load(Path(path).read_text()) or {}
        return cls(data.get("kinds") or {})

    def build(
        self,
        diagnosis: Diagnosis,
        sql: str = "",
        stage: str = "execute",
        dialect: str = "",
        entitled_objects: Sequence[str] = (),
        audience: str = "user",
        incident_id: str = "",
        suggestions: Sequence[str] = (),
    ) -> ErrorReport:
        """Both layers, with the technical one redacted where it would leak."""
        words = self.messages.get(diagnosis.kind, self.messages["unknown"])
        plan = plan_repair(diagnosis)

        redact = audience != "operator" and self._would_leak(diagnosis, dialect, entitled_objects)
        technical = REDACTED if redact else self._technical(diagnosis, sql)

        return ErrorReport(
            kind=diagnosis.kind,
            business=words.get("business", self.messages["unknown"]["business"]),
            technical=technical,
            what_now=words.get("what_now", ""),
            stage=stage,
            # A deterministic repair is not something the *user* retries; it is
            # something we do. `retryable` is about whether asking again could
            # possibly help.
            retryable=plan.action not in ("stop", "ask_user"),
            needs_user=diagnosis.needs_user,
            incident_id=incident_id,
            redacted=redact,
            suggestions=list(suggestions),
        )

    @staticmethod
    def _would_leak(diagnosis: Diagnosis, dialect: str, entitled_objects: Sequence[str]) -> bool:
        if diagnosis.kind not in _SENSITIVE:
            return False
        if diagnosis.kind == "permission_denied":
            return True
        # A not-found naming an object the asker *is* entitled to is safe: they
        # already know it exists. Naming one they are not is the leak.
        subject = (diagnosis.subject or "").lower()
        if subject and any(subject in o.lower() or o.lower() in subject for o in entitled_objects):
            return False
        return dialect in _MERGES_DENIED_INTO_NOT_FOUND or not subject

    @staticmethod
    def _technical(diagnosis: Diagnosis, sql: str) -> str:
        parts = [diagnosis.raw or diagnosis.hint]
        if sql:
            parts.append(f"\nSQL:\n{sql}")
        return "\n".join(p for p in parts if p)
