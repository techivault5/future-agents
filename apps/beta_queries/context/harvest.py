"""Read back what a turn actually asked, so the next turn can build on it.

A follow-up — "and in Germany?", "add a filter for active only" — is rewritten
into a standalone question from the conversation context. That only works if
the context knows what the last question *was*: its metric, its grain, and the
filters the user set. Nothing else in the pipeline records them, so they are
recovered here from the SQL that was about to run.

**Harvest before policy compilation, never after.** `compile_policies` injects
row-level security predicates into the same WHERE clause. Harvested from the
final SQL, an RLS predicate would become a removable chip in the context
panel — disclosing a filter the asker was never told about and inviting
"remove that filter", which the rewrite layer would honour. Taking the model's
own SQL, after identifier resolution and the guard but before policy, makes
that impossible by construction rather than by remembering to subtract.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from beta_queries import dialects

try:
    import sqlglot
    from sqlglot import exp

    _HAVE_SQLGLOT = True
except ImportError:  # pragma: no cover - sqlglot is a declared dependency
    _HAVE_SQLGLOT = False

# Aggregates whose alias names the thing being counted or measured. The alias
# is what the user called it, which is what they will say next turn.
_AGGREGATES = ("count", "sum", "avg", "min", "max", "median")


@dataclass
class Harvest:
    metric: str | None = None
    grain: str | None = None
    filters: list[tuple[str, Any]] = field(default_factory=list)


def _literal(node: Any, params: Mapping[str, Any]) -> Any | None:
    """The value on the right of a predicate, or None if it is not a value.

    A placeholder carries no value of its own — it is resolved through the
    plan's params, which is the only place the bound value exists.
    """
    if isinstance(node, exp.Literal):
        return node.this if node.is_string else node.name
    if isinstance(node, exp.Placeholder):
        name = node.name or (node.this if isinstance(node.this, str) else "")
        return params.get(str(name).lstrip(":@$"))
    if isinstance(node, exp.Parameter):
        return params.get(str(node.name).lstrip(":@$"))
    if isinstance(node, exp.Boolean):
        return node.this
    return None


def _column_name(node: Any) -> str | None:
    return node.name if isinstance(node, exp.Column) else None


def harvest(sql: str, dialect: str, params: Mapping[str, Any] | None = None) -> Harvest:
    """What this query measures, how it is grouped, and what the user filtered on."""
    out = Harvest()
    if not _HAVE_SQLGLOT or not sql.strip():
        return out
    bound = dict(params or {})
    try:
        tree = sqlglot.parse_one(sql, read=dialects.get(dialect).sqlglot)
    except Exception:
        # A query we cannot parse still ran; losing the context is survivable,
        # losing the answer is not.
        return out
    if not isinstance(tree, exp.Select):
        return out

    for projection in tree.expressions:
        inner = projection.this if isinstance(projection, exp.Alias) else projection
        if inner.key.lower() in _AGGREGATES:
            out.metric = projection.alias_or_name or inner.key.lower()
            break

    group = tree.args.get("group")
    if group is not None and group.expressions:
        names = [_column_name(e) or e.sql() for e in group.expressions]
        out.grain = ", ".join(n for n in names if n)

    where = tree.args.get("where")
    if where is None:
        return out
    # Only this SELECT's own predicates. A correlated subquery's WHERE belongs
    # to the subquery, and surfacing it as a chip the user can edit would let
    # an edit land somewhere they never looked.
    for eq in where.find_all(exp.EQ):
        if eq.find_ancestor(exp.Subquery) is not None:
            continue
        column, value = _column_name(eq.this), _literal(eq.expression, bound)
        if column is None:
            column, value = _column_name(eq.expression), _literal(eq.this, bound)
        if column is not None and value is not None:
            out.filters.append((column, value))
    return out
