"""Policy compilation — row filters and masks, injected into the AST.

The guard decides whether a statement is *allowed*. This decides what it is
allowed to *see*, and it runs on every statement including one a user typed
into the editor themselves.

Three rules, and the second is the one that gets missed:

    every scope        a row filter injected only at the top level leaves a
                       subquery, a CTE and a derived table unfiltered — and a
                       correlated subquery is the obvious way to read around a
                       filter. Every SELECT scope gets its own injection.
    a mask is not a    an aggregate-only column may appear inside COUNT or AVG
    projection rule    and nowhere else. Checking only the select list misses
                       ORDER BY, HAVING and a CASE expression.
    fail closed        a policy that cannot be applied — an unparseable
                       predicate, a table with no alias to bind to — rejects
                       the statement. It never silently runs unfiltered.

Row filters are never rendered as removable chips. An RLS predicate is not the
user's to dismiss, and showing it as dismissible teaches the wrong thing about
the system.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

try:
    import sqlglot
    from sqlglot import exp

    HAS_SQLGLOT = True
except ImportError:  # pragma: no cover - sqlglot is a declared dependency
    HAS_SQLGLOT = False

from beta_queries import dialects
from beta_queries.entitlements.resolver import GrantSet, Mask

# How each engine spells a one-way hash, for `strategy="hash"`.
_HASH = {
    "postgres": "MD5({expr})",
    "duckdb": "MD5({expr})",
    "mysql": "SHA2({expr}, 256)",
    "sqlserver": "CONVERT(VARCHAR(64), HASHBYTES('SHA2_256', {expr}), 2)",
    "snowflake": "SHA2({expr}, 256)",
    "databricks": "SHA2({expr}, 256)",
}


@dataclass
class CompileResult:
    sql: str
    filters_applied: list[str] = field(default_factory=list)
    masks_applied: list[str] = field(default_factory=list)
    assumptions_applied: list[str] = field(default_factory=list)
    rejections: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.rejections


def _relname(node: "exp.Table") -> str:
    parts = [p.name for p in (node.args.get("db"), node.this) if p is not None]
    return ".".join(parts)


def _fqn_for(relname: str, grants: GrantSet, datasource: str) -> str | None:
    """Map `schema.table` as written back to the fqn the policy is keyed on."""
    candidate = f"{datasource}.{relname}"
    if candidate in grants.tables:
        return candidate
    bare = relname.split(".")[-1].lower()
    matches = [t for t in grants.tables if t.split(".")[-1].lower() == bare]
    return matches[0] if len(matches) == 1 else None


def _scopes(tree: "exp.Expression") -> list["exp.Select"]:
    """Every SELECT in the statement, including CTEs and derived tables.

    This is the whole reason the compiler walks rather than string-appends: a
    filter on the outer query does nothing about a subquery that reads the
    same table.
    """
    return list(tree.find_all(exp.Select))


def _inside_aggregate(node: "exp.Expression") -> bool:
    parent = node.parent
    while parent is not None:
        if isinstance(parent, exp.AggFunc):
            return True
        parent = parent.parent
    return False


def compile_policies(
    sql: str,
    grants: GrantSet,
    datasource: str,
    dialect: str,
    assumptions: Sequence[tuple[str, str, str]] = (),
) -> CompileResult:
    """Inject row filters, apply masks, and enforce catalog defaults.

    `assumptions` are the catalog's default filters — "active employees only",
    "not soft-deleted". They are injected here rather than left to the model
    for the same reason row filters are: a model that forgets one produces a
    number that is plausible, confidently delivered, and wrong. The difference
    is that an assumption is *removable* — it is reported so the UI can show it
    as a dismissible chip, where a policy filter never is.
    """
    if not HAS_SQLGLOT:  # pragma: no cover
        return CompileResult(sql, rejections=["sqlglot is not installed"])

    d = dialects.get(dialect)
    try:
        tree = sqlglot.parse_one(sql, read=d.sqlglot)
    except Exception as exc:  # noqa: BLE001 — a parse failure is a rejection
        return CompileResult(sql, rejections=[f"could not parse for policy: {exc}"])

    result = CompileResult(sql=sql)

    for scope in _scopes(tree):
        # alias (or bare name) -> fqn, for this scope only. A CTE's alias must
        # not pick up a policy meant for a real table of the same name.
        bindings: dict[str, str] = {}
        for table in scope.find_all(exp.Table):
            if table.parent_select is not scope:
                continue
            relname = _relname(table)
            fqn = _fqn_for(relname, grants, datasource)
            if fqn is None:
                continue
            alias = table.alias or relname.split(".")[-1]
            bindings[alias] = fqn

        for alias, fqn in bindings.items():
            for row_filter in grants.filters_for(fqn):
                if not _inject(scope, row_filter.expression, alias, d, fqn, result):
                    continue
                result.filters_applied.append(
                    f"{fqn}: {row_filter.expression.replace('{alias}', alias)}"
                )
            for target, expression, rationale in assumptions:
                if target != fqn:
                    continue
                if not _inject(scope, expression, alias, d, fqn, result):
                    continue
                result.assumptions_applied.append(rationale or expression.replace("{alias}", alias))

    # Masks are applied across the whole tree: a masked column is masked
    # wherever it appears, not only in the scope that joined its table.
    all_bindings: dict[str, str] = {}
    for table in tree.find_all(exp.Table):
        relname = _relname(table)
        fqn = _fqn_for(relname, grants, datasource)
        if fqn:
            all_bindings[(table.alias or relname.split(".")[-1]).lower()] = fqn

    single = (
        next(iter(set(all_bindings.values()))) if len(set(all_bindings.values())) == 1 else None
    )

    for column in list(tree.find_all(exp.Column)):
        qualifier = (column.table or "").lower()
        fqn = all_bindings.get(qualifier) if qualifier else single
        if not fqn:
            continue

        if f"{fqn}.{column.name}" in grants.denied_columns:
            result.rejections.append(f"{column.name} is not readable by this user")
            continue

        mask = next(
            (m for m in grants.masks_for(fqn) if m.column.lower() == column.name.lower()),
            None,
        )
        if mask is None:
            continue
        _apply_mask(column, mask, d, result)

    if result.rejections:
        return result

    result.sql = tree.sql(dialect=d.sqlglot, pretty=False)
    return result


def _inject(
    scope: "exp.Select",
    expression: str,
    alias: str,
    d: dialects.Dialect,
    fqn: str,
    result: CompileResult,
) -> bool:
    """AND one predicate into one scope. A predicate that will not parse is a
    rejection, never a silent omission — omitting it is how the filter stops
    applying without anyone noticing."""
    rendered = expression.replace("{alias}", alias)
    try:
        predicate = sqlglot.parse_one(rendered, read=d.sqlglot)
    except Exception as exc:  # noqa: BLE001
        result.rejections.append(f"filter for {fqn} is not valid {d.name}: {exc}")
        return False
    scope.where(predicate, copy=False)
    return True


def _inject(
    scope: "exp.Select",
    expression: str,
    alias: str,
    d: dialects.Dialect,
    fqn: str,
    result: CompileResult,
) -> bool:
    """AND one predicate into one scope.

    A predicate that will not parse is a rejection, never a silent omission —
    omitting it is how a filter stops applying without anybody noticing.
    """
    rendered = expression.replace("{alias}", alias)
    try:
        predicate = sqlglot.parse_one(rendered, read=d.sqlglot)
    except Exception as exc:  # noqa: BLE001
        result.rejections.append(f"filter for {fqn} is not valid {d.name}: {exc}")
        return False
    scope.where(predicate, copy=False)
    return True


def _apply_mask(
    column: "exp.Column", mask: Mask, d: dialects.Dialect, result: CompileResult
) -> None:
    """Note the two dialect names. The hash templates are keyed on our engine
    name; sqlglot wants its own (`sqlserver` vs `tsql`). Conflating them is a
    ValueError at the worst possible moment, so both are carried explicitly."""
    label = f"{mask.table}.{mask.column} ({mask.strategy})"

    if mask.aggregate_only:
        # Checked over the whole expression tree, not just the select list:
        # ORDER BY, HAVING and a CASE arm are all ways to read a value out.
        if _inside_aggregate(column):
            if label not in result.masks_applied:
                result.masks_applied.append(label)
            return
        result.rejections.append(f"{mask.column} can be aggregated but not listed row by row")
        return

    if mask.strategy == "hash":
        template = _HASH.get(d.name, "MD5({expr})")
        rendered = template.format(expr=column.sql(dialect=d.sqlglot))
        column.replace(sqlglot.parse_one(rendered, read=d.sqlglot))
    elif mask.strategy == "partial":
        # Last four characters only — enough to recognise a record, not enough
        # to be the record.
        column.replace(
            sqlglot.parse_one(f"RIGHT({column.sql(dialect=d.sqlglot)}, 4)", read=d.sqlglot)
        )
    else:  # redact
        column.replace(exp.Null())

    if label not in result.masks_applied:
        result.masks_applied.append(label)
