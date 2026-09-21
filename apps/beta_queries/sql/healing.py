"""Auto-healing — classify the failure, fix it, and never make it twice.

A text-to-SQL system that retries by asking the model to "try again" gets a
different wrong answer and burns the latency budget doing it. Retrying is only
useful if something was *learned*, so every failure goes through three steps:

    classify   vendor error text -> one of a dozen known kinds. Six engines
               phrase the same failure six ways; the kind is what matters.
    repair     deterministic where the fix is knowable (a misspelled column is
               a catalog lookup, not a judgement), model-assisted where it is
               not, and refused where retrying cannot help.
    remember   a repair that worked is stored against the failure's signature,
               so the same shape of mistake is corrected *before* execution
               next time rather than after it.

The third step is what makes the system get better instead of merely
surviving. A signature deliberately excludes the literal values, so
`employee_i` and `custome_id` — both typos of a real column on the same table —
share one lesson.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Callable

# ── the taxonomy ─────────────────────────────────────────────────────────────
#
# Each kind maps to what can be done about it, which is the only reason to
# classify at all:
#
#   deterministic  the catalog or the AST already knows the answer
#   model          needs a rewrite; worth exactly one attempt
#   user           only the asker can resolve it
#   terminal       retrying cannot help; say so plainly

KIND_STRATEGY = {
    "unknown_column": "deterministic",
    "unknown_table": "deterministic",
    "ambiguous_column": "deterministic",
    "missing_group_by": "deterministic",
    "identifier_case": "deterministic",
    "quoting": "deterministic",
    "type_mismatch": "model",
    "date_format": "model",
    "aggregate_misuse": "model",
    "division_by_zero": "model",
    "syntax": "model",
    "too_many_rows": "user",
    "ambiguous_intent": "user",
    "permission_denied": "terminal",
    "timeout": "terminal",
    "connection": "terminal",
    "unknown": "model",
}

# Six engines, one failure, six phrasings. Ordered: the more specific patterns
# must be tried before the generic ones or everything reads as `syntax`.
_PATTERNS: tuple[tuple[str, str], ...] = (
    # unknown column
    ("unknown_column", r"invalid column name '([^']+)'"),  # SQL Server
    ("unknown_column", r"column \"?([\w .]+)\"? does not exist"),  # Postgres
    ("unknown_column", r"unknown column '([^']+)' in"),  # MySQL
    ("unknown_column", r"invalid identifier '([^']+)'"),  # Snowflake
    ("unknown_column", r"cannot resolve '([^']+)' given input columns"),  # Databricks
    ("unknown_column", r"referenced column \"([^\"]+)\" not found"),  # DuckDB
    ("unknown_column", r"no such column:? ([\w.\"]+)"),
    # unknown table / object
    ("unknown_table", r"invalid object name '([^']+)'"),  # SQL Server
    ("unknown_table", r"relation \"?([\w .]+)\"? does not exist"),  # Postgres
    ("unknown_table", r"table '([^']+)' doesn't exist"),  # MySQL
    ("unknown_table", r"object '([^']+)' does not exist or not authorized"),  # Snowflake
    ("unknown_table", r"table or view not found:? ([\w.`]+)"),  # Databricks
    ("unknown_table", r"table with name ([\w.\"]+) does not exist"),  # DuckDB
    # ambiguity
    ("ambiguous_column", r"ambiguous column (?:name|reference)?:? ?'?\"?([\w.]+)"),
    ("ambiguous_column", r"column reference \"?([\w.]+)\"? is ambiguous"),
    # grouping
    ("missing_group_by", r"column \"?([\w.]+)\"? must appear in the group by clause"),
    (
        "missing_group_by",
        r"is invalid in the select list because it is not contained "
        r"in either an aggregate function or the group by",
    ),
    ("missing_group_by", r"grouping error|not a valid group by expression"),
    ("missing_group_by", r"expression '([\w.]+)' is neither present in the group by"),
    # case and quoting
    ("identifier_case", r"invalid identifier.*case|case.?sensitiv"),
    ("quoting", r"unterminated quoted (?:string|identifier)|unclosed quote"),
    # types and dates
    (
        "type_mismatch",
        r"cannot (?:be )?(?:cast|convert|coerce)|operator does not exist|"
        r"data type mismatch|incompatible types|conversion failed when",
    ),
    (
        "date_format",
        r"date.?format|not a valid date|could not convert string to date|"
        r"timestamp format|out.?of.?range value for|"
        r"incorrect (?:datetime|date|time|timestamp) value",
    ),
    (
        "aggregate_misuse",
        r"aggregate function (?:calls )?cannot be nested|"
        r"aggregates? not allowed in where",
    ),
    ("division_by_zero", r"divi(?:sion|de) by zero"),
    # capacity and access
    (
        "too_many_rows",
        r"result set too large|exceeds the maximum|too many rows|"
        r"memory limit exceeded|spill(?:ed)? to disk",
    ),
    (
        "permission_denied",
        r"permission\s+\w*\s*(?:was\s+)?denied|denied\s+on\s+the\s+object|"
        r"access\s+\w*\s*denied|not authorized|insufficient privileges|"
        r"do(?:es)? not have (?:the )?(?:select|read) permission",
    ),
    ("timeout", r"timeout|timed out|cancell?ed by|query exceeded|statement timeout"),
    (
        "connection",
        r"connection (?:refused|reset|closed|lost)|could not connect|"
        r"no such host|ssl handshake|login failed",
    ),
    # last, because everything unrecognised looks like syntax
    (
        "syntax",
        r"syntax error|incorrect syntax|parse error|unexpected token|"
        r"sql compilation error|mismatched input",
    ),
)

_COMPILED = tuple((kind, re.compile(pattern, re.I | re.S)) for kind, pattern in _PATTERNS)

# Values change between runs; the shape of the mistake does not. Stripping them
# is what lets one lesson cover every typo of the same column.
_NOISE = (
    (re.compile(r"'[^']*'"), "'?'"),
    (re.compile(r'"[^"]*"'), '"?"'),
    (re.compile(r"\b\d+\b"), "N"),
    (re.compile(r"line \d+, ?(?:col(?:umn)? )?\d+", re.I), "at ?"),
    (re.compile(r"\s+"), " "),
)


@dataclass
class Diagnosis:
    kind: str
    strategy: str
    subject: str | None = None  # the identifier the engine complained about
    signature: str = ""
    raw: str = ""
    hint: str = ""

    @property
    def retryable(self) -> bool:
        return self.strategy in ("deterministic", "model")

    @property
    def needs_user(self) -> bool:
        return self.strategy == "user"


_HINTS = {
    "unknown_column": "resolve the column against the catalog before retrying",
    "unknown_table": "the table is not in the entitled catalog, or is a view",
    "ambiguous_column": "qualify the column with its table alias",
    "missing_group_by": "every non-aggregated select expression must be grouped",
    "identifier_case": "quote the identifier with the catalog's exact spelling",
    "quoting": "an identifier or literal was left unterminated",
    "type_mismatch": "cast one side explicitly rather than relying on coercion",
    "date_format": "bind dates as parameters, never as formatted strings",
    "aggregate_misuse": "move the aggregate into HAVING, or into a subquery",
    "division_by_zero": "guard the denominator with NULLIF",
    "too_many_rows": "add a filter or a row cap; the result exceeded the limit",
    "permission_denied": "the asker cannot read this object — do not retry",
    "timeout": "narrow the period or the filter; retrying as-is will time out again",
    "connection": "an infrastructure failure, not a query failure",
    "ambiguous_intent": "ask the user which of the candidates they meant",
}


def signature(message: str, dialect: str = "") -> str:
    """A stable fingerprint for this *shape* of failure."""
    text = (message or "").lower()
    for pattern, replacement in _NOISE:
        text = pattern.sub(replacement, text)
    return hashlib.sha256(f"{dialect}|{text.strip()[:400]}".encode()).hexdigest()[:16]


def diagnose(message: str, dialect: str = "") -> Diagnosis:
    """Classify a database error. Never raises; unknown is a valid answer."""
    raw = (message or "").strip()
    for kind, pattern in _COMPILED:
        match = pattern.search(raw)
        if not match:
            continue
        subject = None
        if match.groups():
            subject = (match.group(1) or "").strip().strip("\"'`[]")
        return Diagnosis(
            kind=kind,
            strategy=KIND_STRATEGY.get(kind, "model"),
            subject=subject or None,
            signature=signature(raw, dialect),
            raw=raw,
            hint=_HINTS.get(kind, ""),
        )
    return Diagnosis(
        kind="unknown",
        strategy=KIND_STRATEGY["unknown"],
        signature=signature(raw, dialect),
        raw=raw,
        hint="unrecognised engine error — one model repair attempt, then stop",
    )


# ── learning from it ─────────────────────────────────────────────────────────


@dataclass
class Lesson:
    signature: str
    kind: str
    dialect: str
    fix: str  # a short instruction, replayed into the prompt next time
    occurrences: int = 1
    repaired: int = 0

    @property
    def reliable(self) -> bool:
        """Worth applying pre-emptively rather than waiting to fail again."""
        return self.repaired >= 2 and self.repaired >= self.occurrences * 0.6


@dataclass
class HealingMemory:
    """What the system has learned about how this estate fails.

    Deliberately small and textual: the lessons are replayed into the prompt as
    a handful of lines, so they are inspectable, editable and deletable by a
    human. A learned behaviour nobody can read is a learned behaviour nobody
    can correct.
    """

    lessons: dict[str, Lesson] = field(default_factory=dict)
    max_lessons: int = 500

    def observe(self, diagnosis: Diagnosis, dialect: str = "") -> Lesson:
        lesson = self.lessons.get(diagnosis.signature)
        if lesson:
            lesson.occurrences += 1
            return lesson
        lesson = Lesson(
            signature=diagnosis.signature,
            kind=diagnosis.kind,
            dialect=dialect,
            fix=diagnosis.hint,
        )
        self.lessons[diagnosis.signature] = lesson
        self._trim()
        return lesson

    def record_repair(self, diagnosis: Diagnosis, fix: str, dialect: str = "") -> Lesson:
        """A repair that actually executed. This is the only thing that teaches.

        Deliberately does not count another occurrence: the failure was already
        counted when it happened, and counting it twice makes a lesson that
        always works look like one that works half the time.
        """
        lesson = self.lessons.get(diagnosis.signature)
        if lesson is None:
            lesson = Lesson(
                signature=diagnosis.signature,
                kind=diagnosis.kind,
                dialect=dialect,
                fix=diagnosis.hint,
                occurrences=1,
            )
            self.lessons[diagnosis.signature] = lesson
            self._trim()
        lesson.repaired += 1
        if fix:
            lesson.fix = fix
        return lesson

    def guidance(self, dialect: str, kinds: set[str] | None = None, limit: int = 8) -> list[str]:
        """The lines to prepend to the next prompt for this engine."""
        pool = [
            lesson
            for lesson in self.lessons.values()
            if lesson.reliable
            and (not lesson.dialect or lesson.dialect == dialect)
            and (kinds is None or lesson.kind in kinds)
        ]
        pool.sort(key=lambda lesson: -lesson.repaired)
        return [f"{lesson.kind}: {lesson.fix}" for lesson in pool[:limit]]

    def _trim(self) -> None:
        while len(self.lessons) > self.max_lessons:
            weakest = min(
                self.lessons.values(), key=lambda lesson: (lesson.repaired, lesson.occurrences)
            )
            self.lessons.pop(weakest.signature, None)


# ── the repair decision ──────────────────────────────────────────────────────


@dataclass
class RepairPlan:
    action: str  # rewrite_identifiers | qualify | add_group_by | ask_model | ask_user | stop
    diagnosis: Diagnosis
    detail: str = ""
    attempts_allowed: int = 1


def plan_repair(
    diagnosis: Diagnosis,
    attempt: int = 0,
    max_model_attempts: int = 1,
) -> RepairPlan:
    """Decide what to do about a failure. One model attempt, then stop.

    A second model attempt on the same statement has, in practice, about the
    same success rate as the first and costs another 900 ms — so the budget
    buys one, and after that the honest answer is the error and the SQL.
    """
    if diagnosis.strategy == "terminal":
        return RepairPlan("stop", diagnosis, diagnosis.hint, 0)
    if diagnosis.strategy == "user":
        return RepairPlan("ask_user", diagnosis, diagnosis.hint, 0)

    if diagnosis.kind in ("unknown_column", "unknown_table", "identifier_case", "quoting"):
        return RepairPlan(
            "rewrite_identifiers",
            diagnosis,
            f"re-resolve {diagnosis.subject!r} against the catalog"
            if diagnosis.subject
            else diagnosis.hint,
        )
    if diagnosis.kind == "ambiguous_column":
        return RepairPlan(
            "qualify",
            diagnosis,
            f"qualify {diagnosis.subject!r} with its table alias"
            if diagnosis.subject
            else diagnosis.hint,
        )
    if diagnosis.kind == "missing_group_by":
        return RepairPlan("add_group_by", diagnosis, diagnosis.hint)

    if attempt >= max_model_attempts:
        return RepairPlan(
            "stop", diagnosis, "one repair attempt already made — returning the error", 0
        )
    return RepairPlan("ask_model", diagnosis, diagnosis.hint)


def heal(
    error: str,
    dialect: str,
    memory: HealingMemory | None = None,
    attempt: int = 0,
    repair: Callable[[RepairPlan], Any] | None = None,
) -> tuple[RepairPlan, Any]:
    """Diagnose, remember, plan — and run the repair if one was supplied."""
    diagnosis = diagnose(error, dialect)
    if memory is not None:
        memory.observe(diagnosis, dialect)
    plan = plan_repair(diagnosis, attempt)
    result = repair(plan) if repair and plan.action not in ("stop", "ask_user") else None
    return plan, result
