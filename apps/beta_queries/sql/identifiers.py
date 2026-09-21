"""Identifier resolution — the single biggest source of "it just doesn't work".

A model writes `report_id`. The column is actually `"report id"`, created quoted
on Snowflake, so it exists only in that exact spelling. The SQL parses, the
guard passes, and the database throws. Or the column is `Report ID` on Postgres
and the model writes `Report ID` unquoted, which Postgres folds to `report id`
— a different column that does not exist.

Nothing about this is the model's fault, and no amount of prompting fixes it
reliably. It is resolved deterministically, against the catalog, after
generation and before execution:

    written identifier -> catalog identifier -> correctly quoted for this engine

The case rules differ per engine and each difference bites:

    Snowflake    unquoted folds to UPPER; a quoted lower-case column is
                 unreachable unquoted, ever
    Postgres     unquoted folds to lower; `"Report ID"` needs quotes forever
    SQL Server   case-preserving, matched case-insensitively under the usual
                 CI collation (a CS collation changes this — see `collation`)
    MySQL        columns case-insensitive; TABLE names are case-sensitive on
                 Linux, which is why a query written on a Mac breaks in prod
    Databricks   case-insensitive, stored lower
    DuckDB       case-insensitive, case-preserving

Unresolvable is not a crash. It is a precise message naming the column and the
closest candidates, which is exactly what the repair loop needs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

try:
    import sqlglot
    from sqlglot import exp

    HAS_SQLGLOT = True
except ImportError:  # pragma: no cover - sqlglot is a declared dependency
    HAS_SQLGLOT = False

from beta_queries import dialects

# A bare identifier is safe only if it is all word characters, does not start
# with a digit, and is not a reserved word. Everything else gets quoted.
_BARE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")

# Not exhaustive — no such list is, across six engines — but it covers the
# words that actually collide with business column names. Anything missed is
# caught by the "folding would change it" rule below or by the engine itself.
# Words reserved in at least one of the six engines AND plausible as a business
# column name. Not the full ANSI list — quoting `status` or `region`, which no
# engine reserves, buys nothing and makes generated SQL look machine-written.
# Anything missed here is still caught by the engine; anything wrongly included
# costs a pair of quotes.
_RESERVED = frozenset(
    """
    user users order group key date time timestamp datetime interval
    year month day hour minute second zone
    table column view index schema database catalog public
    select from where having join inner outer left right full cross natural on
    using union all distinct except intersect as into
    insert update delete create drop alter truncate merge
    primary foreign references constraint unique check default null
    and or not in is like between exists any some case when then else end
    cast collate
    limit offset top range rows row window over partition
    with recursive grant revoke set values value
    current current_date current_time current_timestamp current_user session_user
    level lateral start asc desc position language authorization
    """.split()
)


@dataclass(frozen=True)
class CaseRules:
    """How one engine treats identifier case."""

    unquoted_fold: str  # "upper" | "lower" | "preserve"
    # Quoted identifiers are compared byte-for-byte on these engines.
    quoted_case_sensitive: bool
    # MySQL on Linux: table names come from the filesystem and are case-
    # sensitive even though column names are not.
    table_names_case_sensitive: bool = False

    def fold(self, ident: str) -> str:
        if self.unquoted_fold == "upper":
            return ident.upper()
        if self.unquoted_fold == "lower":
            return ident.lower()
        return ident


CASE_RULES: dict[str, CaseRules] = {
    "snowflake": CaseRules(unquoted_fold="upper", quoted_case_sensitive=True),
    "postgres": CaseRules(unquoted_fold="lower", quoted_case_sensitive=True),
    "databricks": CaseRules(unquoted_fold="lower", quoted_case_sensitive=False),
    "duckdb": CaseRules(unquoted_fold="preserve", quoted_case_sensitive=False),
    # Default SQL Server collations are case-insensitive. A CS collation makes
    # this wrong, which is why `Catalog.collation` can override it.
    "sqlserver": CaseRules(unquoted_fold="preserve", quoted_case_sensitive=False),
    "mysql": CaseRules(
        unquoted_fold="preserve",
        quoted_case_sensitive=False,
        table_names_case_sensitive=True,
    ),
}


def case_rules(dialect: str, collation: str | None = None) -> CaseRules:
    name = dialects.get(dialect).name if dialect not in CASE_RULES else dialect
    rules = CASE_RULES.get(name, CASE_RULES["postgres"])
    # An explicit case-sensitive collation overrides the engine default. Seen
    # in the wild on SQL Server estates migrated from Sybase.
    if collation and re.search(r"_CS_", collation, re.I):
        rules = CaseRules(
            unquoted_fold="preserve",
            quoted_case_sensitive=True,
            table_names_case_sensitive=rules.table_names_case_sensitive,
        )
    return rules


def loose(ident: str) -> str:
    """Fold to the form that ignores spacing, punctuation and case.

    `report id`, `Report_ID`, `REPORTID` and `report-id` all land here as
    `reportid`. This is how a person's phrasing is matched to a real column;
    it is never used to *emit* an identifier.
    """
    return re.sub(r"[^a-z0-9]", "", (ident or "").lower())


@dataclass
class Resolution:
    written: str
    resolved: str | None = None
    table: str | None = None
    how: str = ""  # exact | folded | loose | alias | ambiguous | missing
    candidates: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.resolved is not None

    @property
    def message(self) -> str:
        if self.ok:
            return ""
        if self.how == "ambiguous":
            return (
                f"{self.written!r} matches more than one column "
                f"({', '.join(self.candidates)}) — say which one"
            )
        near = f" Closest: {', '.join(self.candidates)}." if self.candidates else ""
        where = f" in {self.table}" if self.table else ""
        return f"no column {self.written!r}{where}.{near}"


class Catalog:
    """The identifiers this query is allowed to use, and their exact spelling."""

    def __init__(
        self,
        tables: Mapping[str, Sequence[str]],
        dialect: str = "postgres",
        collation: str | None = None,
    ) -> None:
        self.dialect = dialects.get(dialect).name
        self.rules = case_rules(dialect, collation)
        self.tables: dict[str, list[str]] = {t: list(c) for t, c in tables.items()}
        self._by_loose_table = {loose(t): t for t in self.tables}
        self._columns_by_loose: dict[str, dict[str, list[str]]] = {}
        for table, columns in self.tables.items():
            index: dict[str, list[str]] = {}
            for col in columns:
                index.setdefault(loose(col), []).append(col)
            self._columns_by_loose[table] = index

    # ── lookup ──────────────────────────────────────────────────────────────

    def resolve_table(self, written: str) -> Resolution:
        if written in self.tables:
            return Resolution(written, written, how="exact")
        folded = self.rules.fold(written)
        for table in self.tables:
            if self.rules.fold(table) == folded and not self.rules.table_names_case_sensitive:
                return Resolution(written, table, how="folded")
        match = self._by_loose_table.get(loose(written))
        if match:
            how = "loose"
            if self.rules.table_names_case_sensitive and match != written:
                # On MySQL/Linux this is a real failure, not a near miss.
                return Resolution(written, None, how="missing", candidates=[match])
            return Resolution(written, match, how=how)
        near = sorted(self.tables)[:4]
        return Resolution(written, None, how="missing", candidates=near)

    def resolve_column(self, written: str, table: str | None = None) -> Resolution:
        search = [table] if table and table in self.tables else list(self.tables)

        # 1. exact spelling, which is the only thing a quoted identifier can be
        for t in search:
            if written in self.tables[t]:
                return Resolution(written, written, t, "exact")

        # 2. the engine's own folding
        folded = self.rules.fold(written)
        for t in search:
            for col in self.tables[t]:
                if self.rules.fold(col) == folded:
                    return Resolution(written, col, t, "folded")

        # 3. how a person spells it: spacing and punctuation ignored
        hits: list[tuple[str, str]] = []
        key = loose(written)
        for t in search:
            for col in self._columns_by_loose[t].get(key, []):
                hits.append((t, col))
        if len(hits) == 1:
            return Resolution(written, hits[0][1], hits[0][0], "loose")
        if len(hits) > 1:
            return Resolution(
                written,
                None,
                table,
                "ambiguous",
                [f"{t}.{c}" for t, c in hits],
            )

        return Resolution(written, None, table, "missing", self._near(written, search))

    def _near(self, written: str, tables: Iterable[str]) -> list[str]:
        """Columns sharing a prefix or substring — enough to be a useful hint."""
        key = loose(written)
        out: list[str] = []
        for t in tables:
            for col in self.tables[t]:
                lc = loose(col)
                if lc.startswith(key[:4]) or key[:4] in lc or lc in key:
                    out.append(col)
        return sorted(set(out))[:4]

    # ── emission ────────────────────────────────────────────────────────────

    def needs_quoting(self, ident: str) -> bool:
        if not _BARE.match(ident):
            return True
        if ident.lower() in _RESERVED:
            return True
        # If writing it bare would fold it into a different string, the engine
        # would look up the folded name and not find this column.
        return self.rules.fold(ident) != ident

    def render(self, ident: str) -> str:
        """The identifier as this engine must see it — quoted only if needed."""
        if self.needs_quoting(ident):
            return dialects.get(self.dialect).quote_ident(ident)
        return ident

    def render_table(self, relname: str) -> str:
        return ".".join(self.render(part) for part in relname.split("."))


# ── rewriting generated SQL ──────────────────────────────────────────────────


@dataclass
class RewriteResult:
    sql: str
    fixes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    ambiguities: list[Resolution] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and not self.ambiguities


def _cte_names(tree: "exp.Expression") -> set[str]:
    """CTE names are tables the statement defines for itself, not catalog ones."""
    return {cte.alias.lower() for cte in tree.find_all(exp.CTE) if cte.alias}


def _alias_map(tree: "exp.Expression", catalog: Catalog) -> tuple[dict[str, str], list[str]]:
    """alias (and bare table name) -> catalog relname, for qualifying columns."""
    mapping: dict[str, str] = {}
    errors: list[str] = []
    ctes = _cte_names(tree)
    for node in tree.find_all(exp.Table):
        if node.name.lower() in ctes and not node.args.get("db"):
            continue
        parts = [p.name for p in (node.args.get("db"), node.this) if p is not None]
        written = ".".join(parts)
        resolved = catalog.resolve_table(written)
        if not resolved.ok:
            # A single-part name may just be missing its schema.
            single = [t for t in catalog.tables if t.split(".")[-1].lower() == written.lower()]
            if len(single) == 1:
                resolved = Resolution(written, single[0], how="loose")
            else:
                errors.append(resolved.message)
                continue
        target = resolved.resolved or written
        mapping[written.lower()] = target
        mapping[written.split(".")[-1].lower()] = target
        alias = node.alias
        if alias:
            mapping[alias.lower()] = target
    return mapping, errors


def _local_names(tree: "exp.Expression") -> set[str]:
    """Names the statement defines for itself: aliases, CTEs, derived columns.

    These are legitimate references that no catalog contains. Resolving them
    against the catalog turns correct SQL into a rejection, which is worse than
    the bug it was meant to catch.
    """
    names: set[str] = set()
    for node in tree.find_all(exp.Alias):
        if node.alias:
            names.add(node.alias.lower())
    for node in tree.find_all(exp.CTE):
        if node.alias:
            names.add(node.alias.lower())
            for projection in node.this.selects if node.this else []:
                if projection.alias_or_name:
                    names.add(projection.alias_or_name.lower())
        # A CTE may name its output columns explicitly: WITH c(a, b) AS (...)
        for column in node.args.get("columns") or []:
            names.add(column.name.lower())
    for node in tree.find_all(exp.Subquery):
        if node.alias:
            names.add(node.alias.lower())
    return names


def _set_identifier(node: "exp.Expression", key: str, name: str, catalog: Catalog) -> None:
    node.set(key, exp.to_identifier(name, quoted=catalog.needs_quoting(name)))


def rewrite_identifiers(sql: str, catalog: Catalog) -> RewriteResult:
    """Resolve every table and column in `sql` against the catalog.

    This runs after generation and before the guard. What comes out uses the
    catalog's exact spelling, quoted exactly as far as this engine requires and
    no further — so the SQL both executes and still reads like someone wrote it.
    """
    if not HAS_SQLGLOT:  # pragma: no cover
        return RewriteResult(sql, errors=["sqlglot is not installed"])

    read = dialects.get(catalog.dialect).sqlglot
    try:
        tree = sqlglot.parse_one(sql, read=read)
    except Exception as exc:  # noqa: BLE001 — a parse error is a result, not a crash
        repaired = repair_unparseable(sql, catalog)
        if repaired is None:
            return RewriteResult(sql, errors=[f"could not parse: {exc}"])
        try:
            tree = sqlglot.parse_one(repaired, read=read)
        except Exception as exc2:  # noqa: BLE001
            return RewriteResult(sql, errors=[f"could not parse: {exc2}"])
        result = rewrite_identifiers(repaired, catalog)
        result.fixes.insert(0, "quoted an identifier containing a space")
        return result

    aliases, errors = _alias_map(tree, catalog)
    local = _local_names(tree)
    # Columns qualified by a CTE or derived-table alias belong to that
    # subquery's projection, not to any catalog table. There is nothing to
    # resolve them against and nothing to correct.
    derived = _cte_names(tree) | {
        sub.alias.lower() for sub in tree.find_all(exp.Subquery) if sub.alias
    }
    fixes: list[str] = []
    ambiguities: list[Resolution] = []

    for node in tree.find_all(exp.Table):
        parts = [p.name for p in (node.args.get("db"), node.this) if p is not None]
        written = ".".join(parts)
        target = aliases.get(written.lower())
        if not target:
            continue  # a CTE, or a name already reported as an error
        schema, _, name = target.rpartition(".")
        if name != node.name:
            fixes.append(f"table {written} -> {target}")
        _set_identifier(node, "this", name, catalog)
        if schema:
            _set_identifier(node, "db", schema, catalog)

    # Columns are resolved last: they need the alias map to be complete first.
    single_table = next(iter(set(aliases.values()))) if len(set(aliases.values())) == 1 else None
    for node in tree.find_all(exp.Column):
        written = node.name
        if not written or written == "*":
            continue
        qualifier = node.table
        # A SELECT alias, a CTE column or a derived-table output is a valid
        # reference that is not in the catalog. `ORDER BY headcount` where the
        # projection said `COUNT(*) AS headcount` is correct SQL, and rejecting
        # it because no table has a `headcount` column fails good queries.
        if not qualifier and written.lower() in local:
            continue
        if qualifier and qualifier.lower() in derived:
            continue
        table = aliases.get(qualifier.lower()) if qualifier else single_table
        resolved = catalog.resolve_column(written, table)
        if resolved.how == "ambiguous":
            ambiguities.append(resolved)
            continue
        if not resolved.ok:
            errors.append(resolved.message)
            continue
        if resolved.resolved != written:
            fixes.append(f"column {written!r} -> {resolved.resolved!r} ({resolved.how})")
        _set_identifier(node, "this", resolved.resolved, catalog)

    return RewriteResult(
        sql=tree.sql(dialect=read, pretty=False),
        fixes=fixes,
        errors=errors,
        ambiguities=ambiguities,
    )


_WORD_RUN = re.compile(r"(?<![\w.\"'`\[])([A-Za-z_][\w]*(?:\s+[A-Za-z_][\w]*)+)(?![\w\"'`\]])")


def _repairable_runs(phrase: str) -> list[str]:
    """Maximal runs of non-keyword words inside a phrase, longest first.

    `SELECT report id` is one regex match, and rejecting it wholesale because
    it contains `SELECT` is why the naive version never fires: every candidate
    is adjacent to a keyword. The keywords are stripped and what is left is
    considered on its own.
    """
    words = phrase.split()
    runs: list[list[str]] = []
    current: list[str] = []
    for word in words:
        if word.lower() in _RESERVED:
            if len(current) > 1:
                runs.append(current)
            current = []
        else:
            current.append(word)
    if len(current) > 1:
        runs.append(current)

    out: list[str] = []
    for run in runs:
        # Longest first: `owner name` beats nothing, and a 3-word column name
        # must not be split into a 2-word one that happens to also match.
        for size in range(len(run), 1, -1):
            for i in range(len(run) - size + 1):
                out.append(" ".join(run[i : i + size]))
    return out


def repair_unparseable(sql: str, catalog: Catalog) -> str | None:
    """Quote bare multi-word identifiers so the statement parses.

    `SELECT report id FROM ...` is not valid SQL in any engine, so it never
    reaches the guard — it dies at the parser with a message about `id`. If a
    run of bare words matches a real column, quoting it is not a guess: the
    catalog says that column exists and nothing else could have been meant.
    """
    known = {loose(c) for cols in catalog.tables.values() for c in cols}
    if not known:
        return None

    changed = False

    def sub(match: "re.Match[str]") -> str:
        nonlocal changed
        phrase = match.group(1)
        for candidate in _repairable_runs(phrase):
            if loose(candidate) not in known:
                continue
            resolution = catalog.resolve_column(candidate)
            if not resolution.ok:
                continue
            changed = True
            return phrase.replace(candidate, catalog.render(resolution.resolved))
        return phrase

    repaired = _WORD_RUN.sub(sub, sql)
    return repaired if changed else None
