"""Semantics — the two judgements that decide whether an answer is right.

**Which records count.** "How many people are in India" almost never means every
row in `employee`. It means current rows: not soft-deleted, not terminated, not
the superseded half of an SCD2 pair. Getting this wrong produces a number that
is plausible, confidently delivered, and wrong — the worst failure this system
has. So flags are detected from the catalog, turned into predicates, and shown
to the user as a chip rather than applied invisibly.

**Which column.** "Employees by date" has five candidate date columns in a
typical warehouse table, and `load_date` is not the one anyone means. The
ranking here is mostly about *demoting* the ETL and audit columns that match a
term lexically but never match it semantically.

Everything is a pure function over catalog dataclasses, so it is testable with
no database and no model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from beta_queries.catalog.models import Column, DefaultFilter, Table

# ── flag detection ───────────────────────────────────────────────────────────

_ACTIVE_TRUE = re.compile(
    r"^(is_?active|active|is_?enabled|enabled|is_?current|current_?(flag|ind|record)?"
    r"|is_?latest|latest_?flag|curr_?flag|current_?row)$"
)
_DELETED_TRUE = re.compile(
    r"^(is_?deleted|deleted|is_?removed|removed|is_?archived|archived"
    r"|soft_?delete[d]?|is_?void|voided)$"
)
_DELETED_AT = re.compile(r"^(deleted_?at|deleted_?date|removed_?at|archived_?at|void_?date)$")
_SCD_END = re.compile(
    r"^(valid_?to|valid_?until|end_?date|effective_?end_?date|expiry_?date|expire[sd]?_?(at|date)?"
    r"|dbt_valid_to|__end_at|end_?ts|eff_?end_?dt)$"
)
_STATUS = re.compile(
    r"^(\w*_)?(status|state|record_?status|row_?status|lifecycle_?state|disposition)$"
)

# Values that mean "this row counts", lower-cased.
_LIVE_VALUES = {
    "active",
    "a",
    "y",
    "yes",
    "true",
    "t",
    "1",
    "current",
    "open",
    "live",
    "enabled",
    "valid",
    "in force",
    "in_force",
    "effective",
}
# Sentinel end-dates that mean "still current" rather than "ended".
_SENTINELS = ("9999-12-31", "9999-12-30", "2999-12-31", "9999")


def _bool_true(dialect: str, column: Column) -> str:
    """How this engine spells a true boolean for this column's physical type."""
    # bit/tinyint compare to 1 everywhere; real booleans compare to TRUE except
    # on engines that have no boolean literal for a bit column.
    if column.logical == "boolean":
        phys = (column.data_type or "").lower()
        if phys.startswith("bit") or phys.startswith("tinyint") or dialect == "sqlserver":
            return "1"
        return "TRUE"
    return "1"


def _pick_live_value(column: Column) -> str | None:
    """From sampled distinct values, the one that means 'counts'."""
    for value in column.sample_values:
        if value is not None and str(value).strip().lower() in _LIVE_VALUES:
            return str(value)
    return None


def detect_default_filters(
    table: Table, dialect: str = "postgres", alias: str = "{alias}"
) -> list[DefaultFilter]:
    """Propose the predicates that restrict a table to records that count.

    Returns them ordered most-confident first. The caller decides whether to
    apply all of them, the top one, or none; `confidence` is what that decision
    should be made on, and `rationale` is what the user is shown.
    """
    found: list[DefaultFilter] = []

    for col in table.columns:
        cname = col.name.lower()
        ref = f"{alias}.{col.name}"

        if _ACTIVE_TRUE.match(cname) and col.logical in ("boolean", "integer"):
            found.append(
                DefaultFilter(
                    id=f"{table.relname}.{cname}.active",
                    table=table.fqn,
                    column=col.name,
                    expression=f"{ref} = {_bool_true(dialect, col)}",
                    rationale=f"Current records only ({col.name})",
                    kind="active_flag",
                    confidence=0.93,
                )
            )

        elif _DELETED_TRUE.match(cname) and col.logical in ("boolean", "integer"):
            false_lit = "0" if _bool_true(dialect, col) == "1" else "FALSE"
            found.append(
                DefaultFilter(
                    id=f"{table.relname}.{cname}.not_deleted",
                    table=table.fqn,
                    column=col.name,
                    expression=f"{ref} = {false_lit}",
                    rationale=f"Excludes soft-deleted rows ({col.name})",
                    kind="soft_delete",
                    confidence=0.95,
                )
            )

        elif _DELETED_AT.match(cname) and col.logical in ("date", "timestamp"):
            found.append(
                DefaultFilter(
                    id=f"{table.relname}.{cname}.not_deleted",
                    table=table.fqn,
                    column=col.name,
                    expression=f"{ref} IS NULL",
                    rationale=f"Excludes deleted rows ({col.name} is set on delete)",
                    kind="soft_delete",
                    confidence=0.9,
                )
            )

        elif _SCD_END.match(cname) and col.logical in ("date", "timestamp"):
            # Two conventions for "still current": NULL, or a far-future
            # sentinel. Sampled values tell us which one this table uses; with
            # no samples, accept both rather than guess and silently halve the
            # row count.
            sentinel = next(
                (
                    v
                    for v in col.sample_values
                    if v and any(str(v).startswith(s) for s in _SENTINELS)
                ),
                None,
            )
            if sentinel:
                expr = f"({ref} IS NULL OR {ref} >= DATE '{str(sentinel)[:10]}')"
                why = f"Current version only ({col.name} null or {str(sentinel)[:10]})"
                conf = 0.9
            elif col.nullable:
                expr = f"{ref} IS NULL"
                why = f"Current version only ({col.name} is null while current)"
                conf = 0.88
            else:
                expr = f"{ref} > CURRENT_DATE"
                why = f"Current version only ({col.name} in the future)"
                conf = 0.7
            found.append(
                DefaultFilter(
                    id=f"{table.relname}.{cname}.scd_current",
                    table=table.fqn,
                    column=col.name,
                    expression=expr,
                    rationale=why,
                    kind="scd_current",
                    confidence=conf,
                )
            )

        elif _STATUS.match(cname) and col.logical == "string":
            live = _pick_live_value(col)
            if live:
                found.append(
                    DefaultFilter(
                        id=f"{table.relname}.{cname}.status",
                        table=table.fqn,
                        column=col.name,
                        expression=f"{ref} = '{live}'",
                        rationale=f"{col.name} = {live} only",
                        kind="status_enum",
                        confidence=0.85,
                    )
                )
            elif col.is_low_cardinality:
                # We know it is a status column and we know it is small, but we
                # have not sampled a value that reads as "live". Saying so beats
                # inventing a literal.
                found.append(
                    DefaultFilter(
                        id=f"{table.relname}.{cname}.status_unknown",
                        table=table.fqn,
                        column=col.name,
                        expression="",
                        rationale=f"{col.name} looks like a status column but no "
                        f"value reads as active — confirm which value to keep",
                        kind="status_enum",
                        confidence=0.3,
                    )
                )

    found.sort(key=lambda f: f.confidence, reverse=True)
    return found


# ── column disambiguation ────────────────────────────────────────────────────

# Columns that match business terms lexically and never mean them. This list is
# the single highest-value thing in the module: "date" matching `load_date` is
# the most common wrong answer a text-to-SQL system gives.
_AUDIT_PATTERNS = (
    "load_",
    "_load",
    "etl_",
    "_etl",
    "dw_",
    "_dw",
    "dbt_",
    "__",
    "batch_",
    "_batch",
    "ingest",
    "inserted_",
    "insert_ts",
    "created_by",
    "updated_by",
    "modified_by",
    "_audit",
    "audit_",
    "rowversion",
    "row_version",
    "src_",
    "source_system",
    "_hash",
    "checksum",
    "_seq",
    "sys_",
    "_partition",
    "file_name",
    "_filename",
    "record_source",
)
_TECHNICAL_SUFFIXES = ("_key", "_sk", "_id", "_guid", "_uuid")

_INTENT_TYPES = {
    "time": ("date", "timestamp"),
    "measure": ("integer", "decimal"),
    "label": ("string",),
    "flag": ("boolean",),
}


@dataclass
class ScoredColumn:
    column: Column
    score: float
    reasons: list[str]

    @property
    def name(self) -> str:
        return self.column.name


def _is_audit(name: str) -> bool:
    lowered = name.lower()
    return any(p in lowered for p in _AUDIT_PATTERNS)


def rank_columns(
    term: str,
    table: Table,
    intent: str | None = None,
    synonyms: dict[str, list[str]] | None = None,
    usage: dict[str, int] | None = None,
) -> list[ScoredColumn]:
    """Rank a table's columns as candidates for a term in the question.

    `intent` is one of time / measure / label / flag, from NLP preprocessing.
    `usage` counts how often each column appeared in a query that the asker
    accepted — the learned signal that eventually beats every heuristic here.
    """
    term_l = term.strip().lower()
    term_parts = [p for p in re.split(r"[\s_]+", term_l) if p]
    syn = {s.lower() for s in (synonyms or {}).get(term_l, [])}
    usage = usage or {}
    scored: list[ScoredColumn] = []

    for col in table.columns:
        name_l = col.name.lower()
        why: list[str] = []
        score = 0.0

        if name_l == term_l:
            score += 100
            why.append("exact name match")
        elif name_l.replace("_", "") == term_l.replace("_", ""):
            score += 90
            why.append("name match ignoring underscores")
        elif name_l.startswith(term_l) or name_l.endswith(term_l):
            score += 45
            why.append("name starts/ends with the term")
        elif term_l in name_l:
            score += 28
            why.append("name contains the term")
        elif term_parts and all(p in name_l for p in term_parts):
            score += 22
            why.append("name contains every word of the term")

        if name_l in syn:
            score += 55
            why.append("declared synonym")

        if col.comment and term_l in col.comment.lower():
            score += 18
            why.append("description mentions the term")

        if intent and col.logical in _INTENT_TYPES.get(intent, ()):
            score += 20
            why.append(f"type fits a {intent} filter")
        elif intent and intent in _INTENT_TYPES and col.logical not in _INTENT_TYPES[intent]:
            score -= 15
            why.append(f"type does not fit a {intent} filter")

        if _is_audit(name_l):
            score -= 60
            why.append("looks like an ETL/audit column")

        # A surrogate key rarely answers a question phrased in business terms,
        # unless the term itself names a key.
        if name_l.endswith(_TECHNICAL_SUFFIXES) and not term_l.endswith(_TECHNICAL_SUFFIXES):
            score -= 12
            why.append("surrogate/technical key")

        if col.is_pii:
            score -= 8
            why.append("PII — prefer an aggregate")

        hits = usage.get(col.name, 0) or usage.get(name_l, 0)
        if hits:
            bump = min(30.0, 6.0 * (hits**0.5))
            score += bump
            why.append(f"used successfully {hits}x before")

        if score > 0:
            scored.append(ScoredColumn(column=col, score=round(score, 2), reasons=why))

    scored.sort(key=lambda s: (-s.score, s.column.ordinal))
    return scored


def is_ambiguous(ranked: list[ScoredColumn], margin: float = 15.0) -> bool:
    """True when the top two candidates are too close to pick between.

    This is the trigger for asking the user rather than guessing — and the
    margin is deliberately generous, because a wrong column is expensive and a
    one-click clarification is cheap.
    """
    return len(ranked) >= 2 and (ranked[0].score - ranked[1].score) < margin
