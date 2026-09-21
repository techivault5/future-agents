"""Execution — read-only, as the asker, bounded in time and rows.

Three properties, and all three are enforced here rather than trusted:

    as the asker      the connection carries the user's principal, not the
                      application's. Row-level security is enforced by the
                      database, which is the only enforcement that survives a
                      bug in our own code.
    read-only         the session is set read-only where the engine supports
                      it, on top of a read-only grant. The guard already
                      rejects anything but a SELECT; this is the second lock
                      on the same door.
    bounded           a statement timeout and a hard row cap. Execution time is
                      excluded from the 2s budget, which makes it exactly the
                      thing that will run away if nothing stops it.

Failure is a *result*, not an exception: `ExecutionError` carries the engine's
verbatim message, which is the input to the whole error and healing layer. A
paraphrased database error is useless to the person who has to fix it.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from beta_queries import dialects

DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_ROW_LIMIT = 1000

# Named placeholders as the compiler emits them: @p0 (T-SQL), :p0, $p0.
_NAMED = re.compile(r"(?<![:\w])[@:$]([a-zA-Z_]\w*)")


@dataclass
class ExecutionResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]
    ms: int
    truncated: bool = False
    row_limit: int = DEFAULT_ROW_LIMIT

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def dicts(self) -> list[dict[str, Any]]:
        return [dict(zip(self.columns, row)) for row in self.rows]

    def first(self) -> dict[str, Any] | None:
        """The single row an aggregate answer renders from."""
        return self.dicts()[0] if self.rows else None


@dataclass
class ExecutionError(Exception):
    """A database failure, carried rather than raised through the stack.

    `message` is verbatim on purpose. `diagnose()` reads it, the technical half
    of the error report shows it, and the healing signature is computed from
    it — all three break if it is cleaned up on the way past.
    """

    message: str
    dialect: str = ""
    sql: str = ""
    sqlstate: str = ""
    ms: int = 0
    # Set when we cancelled it rather than the engine rejecting it, because
    # "you ran out of time" and "your query is wrong" are different answers.
    timed_out: bool = False

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


@dataclass
class ExecutionRequest:
    sql: str
    dialect: str
    params: dict[str, Any] = field(default_factory=dict)
    row_limit: int = DEFAULT_ROW_LIMIT
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS


def bind(sql: str, params: dict[str, Any], dialect: str) -> tuple[str, Any]:
    """Rewrite named placeholders into the driver's own style.

    The compiler emits `@p0`-style names because they are readable in the
    editor and stable across engines. Drivers want `?`, `%s` or `:1`, in
    positional order — and getting this wrong turns every bound literal into a
    syntax error, which is why it is one function with one test per style.

    Values are never interpolated. A parameter that is missing raises rather
    than binding NULL, because a silently-NULL filter returns the wrong number
    rather than failing.
    """
    style = dialects.get(dialect).param_style
    if style == "pyformat" and not params:
        # A bare `%` in a LIKE pattern is a format spec to these drivers.
        return sql.replace("%", "%%"), ()

    ordered: list[Any] = []
    missing: list[str] = []

    def replace(match: "re.Match[str]") -> str:
        name = match.group(1)
        if name not in params:
            missing.append(name)
            return match.group(0)
        ordered.append(params[name])
        if style == "pyformat":
            return "%s"
        if style == "numeric":
            return f":{len(ordered)}"
        return "?"

    if style == "pyformat":
        sql = sql.replace("%", "%%")
    rewritten = _NAMED.sub(replace, sql)

    if missing:
        raise ExecutionError(
            message=f"query references unbound parameter(s): {', '.join(sorted(set(missing)))}",
            dialect=dialect,
            sql=sql,
        )
    return rewritten, tuple(ordered)


def _sqlstate(exc: BaseException) -> str:
    """Every driver hides SQLSTATE somewhere different, and none of them agree."""
    for attribute in ("sqlstate", "pgcode", "code"):
        value = getattr(exc, attribute, None)
        if value:
            return str(value)
    args = getattr(exc, "args", ())
    if args and isinstance(args[0], str) and re.fullmatch(r"[0-9A-Z]{5}", args[0]):
        return args[0]
    return ""


class DbapiExecutor:
    """Executes against any PEP-249 connection.

    Takes a `connect()` factory rather than a connection, because the
    connection must be opened **as the asker** — a pooled application
    connection would run every query as the application, and row-level
    security would never fire.
    """

    def __init__(
        self,
        connect: Callable[[], Any],
        dialect: str,
        on_error: Callable[[ExecutionError], None] | None = None,
    ) -> None:
        self.connect = connect
        self.dialect = dialects.get(dialect).name
        self.on_error = on_error

    def run(self, request: ExecutionRequest) -> ExecutionResult:
        """Execute, or raise `ExecutionError` carrying the engine's own words."""
        d = dialects.get(request.dialect or self.dialect)
        sql, params = bind(request.sql, request.params, d.name)
        started = time.perf_counter()
        connection = None
        cursor = None

        try:
            connection = self.connect()
            cursor = connection.cursor()
            self._prepare_session(cursor, d, request.timeout_seconds)

            cursor.execute(sql, params) if params else cursor.execute(sql)

            columns = [c[0] for c in (cursor.description or [])]
            # One more than the cap, so "there were more" is knowable without
            # fetching a result set nobody asked for.
            fetched = cursor.fetchmany(request.row_limit + 1)
            rows = [tuple(r) for r in fetched[: request.row_limit]]
            return ExecutionResult(
                columns=columns,
                rows=rows,
                ms=int((time.perf_counter() - started) * 1000),
                truncated=len(fetched) > request.row_limit,
                row_limit=request.row_limit,
            )

        except ExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001 — every driver raises its own types
            ms = int((time.perf_counter() - started) * 1000)
            message = str(exc).strip() or exc.__class__.__name__
            error = ExecutionError(
                message=message,
                dialect=d.name,
                sql=request.sql,
                sqlstate=_sqlstate(exc),
                ms=ms,
                timed_out=bool(re.search(r"timeout|timed out|cancell?ed", message, re.I)),
            )
            if self.on_error:
                self.on_error(error)
            raise error from exc
        finally:
            for closeable in (cursor, connection):
                try:
                    if closeable is not None:
                        closeable.close()
                except Exception:  # noqa: BLE001 — a close failure must not mask the real one
                    pass

    @staticmethod
    def _prepare_session(cursor: Any, d: dialects.Dialect, timeout_seconds: int) -> None:
        """Read-only and time-bounded, best effort.

        Best effort is deliberate: an engine or a driver that rejects one of
        these is not a reason to refuse to answer the question, because the
        read-only grant and the guard are the real boundary. But where the
        engine does support it, a runaway query stops being our problem.
        """
        for statement in d.session_sql:
            rendered = statement.format(
                timeout_ms=int(timeout_seconds * 1000),
                timeout_s=int(timeout_seconds),
            )
            try:
                cursor.execute(rendered)
            except Exception:  # noqa: BLE001
                continue


def run(
    sql: str,
    dialect: str,
    connect: Callable[[], Any],
    params: dict[str, Any] | None = None,
    row_limit: int = DEFAULT_ROW_LIMIT,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> ExecutionResult:
    """The `sql.execute` tool surface — one call, plain arguments.

    Never offered to the model. The orchestrator calls it after the guard and
    the policy compiler have both passed, and only then.
    """
    return DbapiExecutor(connect, dialect).run(
        ExecutionRequest(
            sql=sql,
            dialect=dialect,
            params=params or {},
            row_limit=row_limit,
            timeout_seconds=timeout_seconds,
        )
    )


def duckdb_connect(path: str = ":memory:", read_only: bool = False) -> Callable[[], Any]:
    """A connect factory for DuckDB — the engine everything is tested against."""

    def connect() -> Any:
        import duckdb

        return duckdb.connect(path, read_only=read_only)

    return connect
