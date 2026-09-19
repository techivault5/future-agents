"""SQL guard — deterministic validation of generated and hand-edited SQL.

No model is involved. The guard parses the statement with sqlglot in the target
dialect and checks it against the catalog the asker is entitled to, then either
rejects it with a rule id the repair prompt can act on, or rewrites it into
something safe to run.

Two rules carry most of the weight:

    G06  every table resolves to a **base table** in the catalog. Views are
         rejected by name even when the user is entitled to them, because a
         view's definition is invisible to the planner: its filters, its grain
         and its own joins are all unknown, so nothing downstream can reason
         about whether the answer is right.

    G09  a row cap is always present, spelled the way the engine spells it —
         TOP (n) inside the projection for T-SQL, trailing LIMIT n elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from beta_queries import dialects

try:  # sqlglot is an optional extra, like anthropic elsewhere in this repo
    import sqlglot
    from sqlglot import exp

    HAS_SQLGLOT = True
except ImportError:  # pragma: no cover - exercised only in bare installs
    HAS_SQLGLOT = False

WRITE_NODES: tuple[str, ...] = (
    "Insert",
    "Update",
    "Delete",
    "Merge",
    "Drop",
    "Create",
    "Alter",
    "TruncateTable",
    "Grant",
    "Command",
)


@dataclass
class Finding:
    rule: str
    message: str
    severity: str = "reject"  # reject | rewrite | warn


@dataclass
class GuardResult:
    ok: bool
    sql: str
    findings: list[Finding] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    verdict: str = "allowed"  # allowed | rewritten | rejected

    @property
    def rejections(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "reject"]

    def first_rule(self) -> str | None:
        return self.rejections[0].rule if self.rejections else None


@dataclass
class GuardContext:
    """What the guard checks a statement against."""

    dialect: str
    # relname ("dbo.employee") -> is_view. Membership is the allow-list;
    # the flag is what enforces tables-only.
    tables: dict[str, bool]
    denied_columns: set[str] = field(default_factory=set)
    row_limit: int = 1000
    max_joins: int = 8
    required_filters: dict[str, str] = field(default_factory=dict)


def _relnames(node: "exp.Expression") -> list[tuple[str, "exp.Table"]]:
    out = []
    for tbl in node.find_all(exp.Table):
        parts = [p for p in (tbl.text("db"), tbl.text("this")) if p]
        out.append((".".join(parts), tbl))
    return out


def check(sql: str, ctx: GuardContext) -> GuardResult:
    """Validate and, where safe, rewrite. Never raises on malformed input."""
    if not HAS_SQLGLOT:
        raise RuntimeError(
            "sqlglot is required for the SQL guard: pip install -e '.[beta_queries]'"
        )

    d = dialects.get(ctx.dialect)
    findings: list[Finding] = []

    try:
        parsed = sqlglot.parse(sql, read=d.sqlglot)
    except Exception as err:  # sqlglot raises several unrelated types
        return GuardResult(
            ok=False,
            sql=sql,
            verdict="rejected",
            findings=[Finding("G00", f"could not parse as {d.name}: {err}")],
        )

    statements = [s for s in parsed if s is not None]
    if len(statements) != 1:
        return GuardResult(
            ok=False,
            sql=sql,
            verdict="rejected",
            findings=[Finding("G01", f"expected exactly one statement, found {len(statements)}")],
        )

    tree = statements[0]

    # G02 — the root must be a read.
    if not isinstance(tree, (exp.Select, exp.Subquery, exp.Union)) and not (
        isinstance(tree, exp.Expression) and tree.find(exp.Select)
    ):
        findings.append(Finding("G02", f"root is {type(tree).__name__}, expected SELECT"))

    # G03 — no write node anywhere, including inside a CTE.
    for name in WRITE_NODES:
        node_cls = getattr(exp, name, None)
        if node_cls is not None and tree.find(node_cls):
            findings.append(Finding("G03", f"statement contains {name}"))

    # G04 — engine-specific escapes.
    lowered = sql.lower()
    for token in d.forbidden_tokens:
        if token in lowered:
            findings.append(Finding("G04", f"forbidden construct for {d.name}: {token}"))

    # G05 — SELECT ... INTO creates a table.
    if tree.find(exp.Into):
        findings.append(Finding("G05", "SELECT ... INTO is not permitted"))

    # G06 — every table is an entitled *base* table.
    seen: list[str] = []
    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    for relname, _tbl in _relnames(tree):
        if not relname or relname.lower() in cte_names:
            continue
        seen.append(relname)
        key = next((k for k in ctx.tables if k.lower() == relname.lower()), None)
        if key is None:
            findings.append(Finding("G06", f"{relname} is not in the catalog for this datasource"))
        elif ctx.tables[key]:
            findings.append(
                Finding(
                    "G06",
                    f"{relname} is a view; query the underlying base tables instead "
                    "so filters, grain and joins stay visible to the planner",
                )
            )

    # G07 — denied columns anywhere in the statement.
    denied_lower = {c.lower() for c in ctx.denied_columns}
    for column in tree.find_all(exp.Column):
        if column.name and column.name.lower() in denied_lower:
            findings.append(Finding("G07", f"column {column.name} is masked or denied"))

    # G11/G12 — join sanity.
    joins = list(tree.find_all(exp.Join))
    if len(joins) > ctx.max_joins:
        findings.append(Finding("G12", f"{len(joins)} joins exceeds the cap of {ctx.max_joins}"))
    for join in joins:
        if not join.args.get("on") and not join.args.get("using"):
            kind = (join.side or join.kind or "").upper()
            if kind != "CROSS":
                findings.append(Finding("G11", "join without ON/USING (cartesian product)"))

    if any(f.severity == "reject" for f in findings):
        return GuardResult(ok=False, sql=sql, findings=findings, tables=seen, verdict="rejected")

    # ── rewrites ────────────────────────────────────────────────────────────
    rewritten = False

    # G09 — dialect-correct row cap. sqlglot renders TOP for T-SQL and a
    # trailing LIMIT elsewhere, so the AST call is the portable spelling.
    select = tree if isinstance(tree, exp.Select) else tree.find(exp.Select)
    if select is not None and ctx.row_limit:
        has_cap = bool(tree.args.get("limit") or select.args.get("limit"))
        if d.limit_style == "top":
            has_cap = has_cap or bool(select.args.get("limit") or select.args.get("top"))
        if not has_cap:
            tree = tree.limit(ctx.row_limit)
            findings.append(
                Finding("G09", f"row cap of {ctx.row_limit} injected", severity="rewrite")
            )
            rewritten = True

    out = tree.sql(dialect=d.sqlglot, pretty=True)
    return GuardResult(
        ok=True,
        sql=out,
        findings=findings,
        tables=seen,
        verdict="rewritten" if rewritten else "allowed",
    )
