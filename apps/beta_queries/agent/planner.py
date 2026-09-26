"""The single generation call.

One model call before execution, because an agentic loop cannot fit in two
seconds and because every extra call is another chance to invent a table name.
Everything the model could get wrong that we can decide ourselves has already
been decided by the time this runs.

What comes back is validated, not trusted. A `QueryPlan` that does not parse is
repaired exactly once — the parse failure is shown back with what it produced —
and then surfaced as a clarification rather than a half-answer. A plan that
references a table outside the entitled set is rejected here as well as at the
guard, because the guard is the boundary and this is the earlier, cheaper one.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from beta_queries.agent.contract import QueryPlan
from beta_queries.agent.prompts import (
    SchemaCard,
    build_system,
    build_user,
)
from beta_queries.agent.providers import DEFAULT_TIMEOUT, Completion, Provider, parse_plan

MAX_REPAIRS = 1
# A transport failure — timeout, reset, 502 — is not the model's fault and is
# often gone a second later, so it earns one retry. A parse failure is the
# model's, and has its own repair pass with the error fed back.
TRANSPORT_RETRIES = 1
TRANSPORT_BACKOFF_SECONDS = 1.5


@dataclass
class PlanResult:
    plan: QueryPlan | None = None
    completions: list[Completion] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    repaired: bool = False
    # Why there is no plan, in a word the user can act on:
    # timeout | truncated | auth | unavailable | invalid | rejected.
    # Every one of these used to surface as "ambiguous_intent".
    failure: str = ""

    @property
    def ok(self) -> bool:
        return self.plan is not None

    @property
    def ms(self) -> int:
        return sum(c.ms for c in self.completions)

    @property
    def calls(self) -> int:
        return len(self.completions)


def _reject(plan: QueryPlan, entitled: set[str], datasource: str) -> list[str]:
    """Checks that are cheaper here than at the guard, and identical in effect."""
    problems: list[str] = []

    if plan.datasource_id != datasource:
        problems.append(
            f"plan targets {plan.datasource_id!r} but the routed source is {datasource!r}"
        )

    if plan.sql:
        for table in plan.referenced_tables:
            bare = table.split(".")[-1].lower()
            if not any(
                t.lower() == table.lower() or t.split(".")[-1].lower() == bare for t in entitled
            ):
                problems.append(f"{table} is not in the entitled catalog")

        # Every literal bound: a plan carrying its values inline has already
        # lost, whatever the SQL looks like.
        for param in plan.params:
            if f":{param.name}" in plan.sql:
                continue
            if f"@{param.name}" in plan.sql or f"${param.name}" in plan.sql:
                # A real trap rather than a style preference: `@p0` is DuckDB's
                # absolute-value operator and parses as ABS(p0); `$p0` is a
                # column on T-SQL and MySQL. Only `:p0` is a placeholder on all
                # six, so the wrong sigil fails here as a bad plan rather than
                # much later as a missing column.
                problems.append(
                    f"parameter {param.name} must be written :{param.name} — "
                    "@ and $ collide with operators on some engines"
                )
                continue
            problems.append(f"parameter {param.name} is never referenced in the SQL")

    return problems


def plan_query(
    question: str,
    datasource: str,
    dialect: str,
    cards: Sequence[SchemaCard],
    provider: Provider,
    entitled: set[str] | None = None,
    join_steps: Sequence[str] = (),
    resolved_dates: Sequence[tuple[str, str, str]] = (),
    context: dict[str, Any] | None = None,
    profile_hints: dict[str, Any] | None = None,
    guidance: Sequence[str] = (),
    unreachable: Sequence[str] = (),
    timeout: float = DEFAULT_TIMEOUT,
) -> PlanResult:
    """Plan once, repair once, then stop."""
    system = build_system(dialect)
    user = build_user(
        question=question,
        datasource=datasource,
        dialect=dialect,
        cards=cards,
        join_steps=join_steps,
        resolved_dates=resolved_dates,
        context=context,
        profile_hints=profile_hints,
        guidance=guidance,
        unreachable=unreachable,
    )
    allowed = {c.fqn for c in cards} | set(entitled or set())
    result = PlanResult()
    prompt = user

    for attempt in range(MAX_REPAIRS + 1):
        started = time.perf_counter()
        completion = None
        for transport_try in range(TRANSPORT_RETRIES + 1):
            try:
                completion = provider.complete(system, prompt, timeout=timeout)
                break
            except Exception as exc:  # noqa: BLE001 — a provider failure is a result
                result.errors.append(f"model call failed: {exc}")
                result.failure = _classify_transport(exc)
                # Auth and configuration will not fix themselves in 1.5 s.
                if result.failure == "auth" or transport_try >= TRANSPORT_RETRIES:
                    return result
                time.sleep(TRANSPORT_BACKOFF_SECONDS)
        if completion is None:
            return result
        result.failure = ""
        completion.ms = completion.ms or int((time.perf_counter() - started) * 1000)
        result.completions.append(completion)

        if completion.truncated:
            # Half a statement that happens to parse is worse than none.
            result.errors.append("model response was truncated")
            result.failure = "truncated"
            return result

        try:
            plan = parse_plan(completion.text)
        except Exception as exc:  # noqa: BLE001 — pydantic and json both land here
            result.errors.append(str(exc))
            if attempt >= MAX_REPAIRS:
                result.failure = "invalid"
                return result
            result.repaired = True
            prompt = (
                f"{user}\n\n"
                f"Your previous reply could not be used: {exc}\n"
                "Reply with one JSON object only, no prose and no code fences."
            )
            continue

        problems = _reject(plan, allowed, datasource)
        if not problems:
            result.plan = plan
            return result

        result.errors.extend(problems)
        if attempt >= MAX_REPAIRS:
            result.failure = "rejected"
            return result
        result.repaired = True
        prompt = (
            f"{user}\n\n"
            f"Your previous reply was rejected: {'; '.join(problems)}\n"
            "Use only the tables listed above, and bind every literal."
        )

    return result


def clarification_from(result: PlanResult, question: str) -> dict[str, Any]:
    """What to say when planning failed. Never a half-answer, never a raw error."""
    return {
        "question": "I couldn't turn that into a query I trust. Which did you mean?",
        "detail": result.errors[0] if result.errors else "",
        "asked": question,
    }


def _classify_transport(exc: BaseException) -> str:
    """Name a transport failure the way the person fixing it would."""
    text = f"{type(exc).__name__} {exc}".lower()
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if any(m in text for m in ("401", "403", "unauthor", "forbidden", "api_key", "is not set")):
        return "auth"
    return "unavailable"
