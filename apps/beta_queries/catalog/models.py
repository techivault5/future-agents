"""Catalog data model — what the crawler produces and the planner consumes.

Deliberately plain dataclasses: the catalog is serialised to Redis and to the
semantic index, diffed between crawls, and rendered into prompts. Anything with
behaviour attached makes those three jobs harder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

# Physical type names vary wildly across the five engines (NUMBER, numeric,
# bigint, DECIMAL(18,2), tinyint(1)...). Everything downstream — flag detection,
# value indexing, filter synthesis — reasons about the logical class instead.
_LOGICAL_TYPES: dict[str, tuple[str, ...]] = {
    "boolean": ("bool", "boolean", "bit"),
    "integer": (
        "int",
        "integer",
        "bigint",
        "smallint",
        "tinyint",
        "number",
        "long",
        "serial",
        "numeric(38,0)",
    ),
    "decimal": ("decimal", "numeric", "float", "double", "real", "money"),
    "date": ("date",),
    "timestamp": (
        "timestamp",
        "datetime",
        "datetime2",
        "smalldatetime",
        "timestamptz",
        "timestamp_ntz",
        "timestamp_tz",
        "timestamp_ltz",
    ),
    "string": ("char", "varchar", "nvarchar", "nchar", "text", "string", "clob", "ntext"),
    "binary": ("binary", "varbinary", "blob", "bytea"),
}


def logical_type(physical: str) -> str:
    """Map an engine-specific type name onto a small logical vocabulary."""
    p = (physical or "").strip().lower()
    # tinyint(1) is MySQL's boolean; bit(1) is its other one.
    if p.startswith("tinyint(1)") or p.startswith("bit(1)"):
        return "boolean"
    base = p.split("(")[0].strip()
    for logical, names in _LOGICAL_TYPES.items():
        if base in names:
            return logical
    for logical, names in _LOGICAL_TYPES.items():
        if any(base.startswith(n) for n in names):
            return logical
    return "other"


@dataclass
class Column:
    name: str
    ordinal: int
    data_type: str
    nullable: bool
    comment: str | None = None
    # Populated by the profiler, not the structural crawl.
    distinct_count: int | None = None
    null_fraction: float | None = None
    sample_values: list[str] = field(default_factory=list)
    is_pii: bool = False
    mask_policy: str | None = None

    @property
    def logical(self) -> str:
        return logical_type(self.data_type)

    @property
    def is_low_cardinality(self) -> bool:
        return self.distinct_count is not None and self.distinct_count <= 5000


@dataclass
class Table:
    datasource_id: str
    schema: str
    name: str
    columns: list[Column] = field(default_factory=list)
    comment: str | None = None
    row_estimate: int | None = None
    # Set by the crawler. Views never reach the planner, but recording that we
    # saw one is what lets the catalog explain why a familiar name is missing.
    is_view: bool = False
    grain: str | None = None
    default_filters: list[DefaultFilter] = field(default_factory=list)

    @property
    def fqn(self) -> str:
        return f"{self.datasource_id}.{self.schema}.{self.name}"

    @property
    def relname(self) -> str:
        return f"{self.schema}.{self.name}"

    def column(self, name: str) -> Column | None:
        lowered = name.lower()
        return next((c for c in self.columns if c.name.lower() == lowered), None)


@dataclass
class JoinEdge:
    """A join the planner is allowed to use.

    `source` records how we know about it, because the three origins do not
    deserve equal trust: a declared FK is a fact, an inferred edge is a guess
    that happens to be right most of the time, and a learned edge is evidence
    that people keep joining these two tables successfully.
    """

    left_table: str  # fqn
    left_column: str
    right_table: str  # fqn
    right_column: str
    cardinality: str = "n:1"
    source: str = "declared"  # declared | inferred | learned
    confidence: float = 1.0

    def key(self) -> tuple[str, str, str, str]:
        return (self.left_table, self.left_column, self.right_table, self.right_column)


@dataclass
class DefaultFilter:
    """A predicate applied unless the user says otherwise, shown as a chip.

    `rationale` is user-facing — it is the text on the chip's tooltip, and the
    reason a number is smaller than someone expected.
    """

    id: str
    table: str  # fqn
    column: str
    expression: str  # rendered against the table alias at plan time
    rationale: str
    kind: str  # active_flag | soft_delete | scd_current | status_enum
    confidence: float
    editable: bool = True


@dataclass
class Datasource:
    id: str
    dialect: str
    description: str = ""
    tables: list[Table] = field(default_factory=list)
    joins: list[JoinEdge] = field(default_factory=list)
    crawled_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: int = 1

    def table(self, relname: str) -> Table | None:
        lowered = relname.lower()
        return next((t for t in self.tables if t.relname.lower() == lowered), None)

    @property
    def base_tables(self) -> list[Table]:
        return [t for t in self.tables if not t.is_view]
