"""The stage machine — one question, one pass, narrated as it goes.

The order is the design. Each stage removes a way for the next one to be wrong:

    turn          most questions are not questions. A greeting, a thank-you, a
                  pivot and a meta question never reach the model at all.
    entitlements  resolved before retrieval, so an unentitled table is never
                  in the prompt to be hallucinated or leaked.
    route         which database, from the value index rather than the words.
    tables        which tables, views excluded and staging demoted.
    joins         how they connect, from the graph — never from the model.
    plan          ONE model call. Projection and predicates only.
    identifiers   what it wrote resolved to what the catalog holds.
    guard         the security boundary, on generated and hand-edited SQL alike.
    policy        row filters and masks, injected into every scope.
    execute       as the asker, read-only, bounded.
    heal          on failure: classify, repair once deterministically, stop.

Narration is emitted by this module, never by the model. The first step has to
render at ~50 ms and the model does not answer until ~900 ms, so anything the
model narrates is narration of the past.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from beta_queries import dialects
from beta_queries.agent.planner import plan_query
from beta_queries.agent.prompts import SchemaCard, prune_columns
from beta_queries.agent.providers import Provider
from beta_queries.context.model import ConversationContext, FilterChip
from beta_queries.dialogue.policy import DialoguePolicy
from beta_queries.dialogue.turn import handle_turn
from beta_queries.entitlements.resolver import EntitlementResolver, GrantSet
from beta_queries.progress import StepMachine
from beta_queries.routing.router import SourceProfile, route
from beta_queries.sql import healing
from beta_queries.sql.compiler import compile_policies
from beta_queries.sql.executor import DbapiExecutor, ExecutionError, ExecutionRequest
from beta_queries.sql.guard import GuardContext, check
from beta_queries.sql.identifiers import Catalog, rewrite_identifiers

DEFAULT_ROW_LIMIT = 1000


@dataclass
class Answer:
    """Everything one turn produces. The UI renders this and nothing else."""

    text: str = ""
    scenario: str = ""
    sql: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    truncated: bool = False
    datasource: str | None = None
    tables: list[str] = field(default_factory=list)
    joins: list[str] = field(default_factory=list)
    assumptions: list[dict[str, Any]] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    clarification: dict[str, Any] | None = None
    error: dict[str, str] | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    panel: dict[str, Any] = field(default_factory=dict)
    ms: int = 0
    llm_calls: int = 0

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class Source:
    """One registered datasource and everything needed to reach it."""

    id: str
    dialect: str
    profile: SourceProfile
    connect: Callable[[], Any]
    column_types: dict[str, dict[str, str]] = field(default_factory=dict)
    default_filters: dict[str, list[str]] = field(default_factory=dict)


class Orchestrator:
    def __init__(
        self,
        sources: Sequence[Source],
        graph: Any,
        entitlements: EntitlementResolver,
        provider: Provider,
        policy: DialoguePolicy | None = None,
        healing_memory: healing.HealingMemory | None = None,
        steps_config: str | None = None,
        row_limit: int = DEFAULT_ROW_LIMIT,
        facts: dict[str, Any] | None = None,
    ) -> None:
        self.sources = {s.id: s for s in sources}
        self.graph = graph
        self.entitlements = entitlements
        self.provider = provider
        self.policy = policy or DialoguePolicy()
        self.healing = healing_memory or healing.HealingMemory()
        self.steps_config = steps_config
        self.row_limit = row_limit
        self.facts = facts or {}

    # ── the one entry point ─────────────────────────────────────────────────

    def ask(
        self,
        question: str,
        principal: str,
        ctx: ConversationContext | None = None,
        sink: Callable[[dict[str, Any]], None] | None = None,
        today: date | None = None,
    ) -> Answer:
        started = time.perf_counter()
        ctx = ctx or ConversationContext(session_id=principal)
        machine = (
            StepMachine.from_file(self.steps_config, sink=sink)
            if self.steps_config
            else StepMachine(sink=sink)
        )
        answer = Answer()

        # 1. Most turns are not questions, and never reach the model.
        outcome = handle_turn(question, ctx, self.policy, self.facts, today)
        answer.scenario = outcome.scenario
        answer.text = outcome.reply.text
        answer.suggestions = outcome.reply.suggestions
        if not outcome.reply.executes_sql:
            answer.panel = ctx.to_panel()
            answer.steps = machine.trace()
            answer.ms = int((time.perf_counter() - started) * 1000)
            return answer

        resolved_question = outcome.question

        # 2. Entitlements, before anything is retrieved.
        machine.start("entitlements")
        grants = self.entitlements.resolve(principal)
        usable = [s for s in self.sources.values() if s.id in grants.datasources]
        machine.done("entitlements", n=len(usable))
        if not usable:
            return self._reply(answer, machine, ctx, started, "out_of_scope")

        # 3. Which database.
        machine.start("route")
        decision = route(resolved_question, [s.profile for s in usable])
        if not decision.confident:
            scenario = "ambiguous_source" if decision.needs_clarification else "out_of_scope"
            machine.fail("route", decision.reason)
            return self._reply(
                answer, machine, ctx, started, scenario, sources=", ".join(s.id for s in usable)
            )
        source = self.sources[decision.chosen]
        why = decision.candidates[0].reasons[0] if decision.candidates[0].reasons else ""
        machine.done("route", datasource=source.id, why=why)
        answer.datasource = source.id
        ctx.datasource = source.id

        # 4 and 5. Which tables, and how they connect — both from the graph.
        machine.start("schema")
        entitled_fqns = {t for t in grants.tables if t.startswith(f"{source.id}.")}
        candidates = self.graph.candidate_tables(
            resolved_question, entitled=entitled_fqns, datasource=source.id
        )
        if not candidates:
            machine.fail("schema", "nothing in the entitled catalog matches")
            return self._reply(answer, machine, ctx, started, "out_of_scope", sources=source.id)
        fqns = [c.fqn for c in candidates[:4]]
        join_plan = self.graph.join_plan(fqns)
        machine.done("schema", n=len(join_plan.tables), joins=len(join_plan.steps))
        answer.tables = list(join_plan.tables)
        answer.joins = [
            f"{s.left.split('.')[-1]}.{s.left_column} = "
            f"{s.right.split('.')[-1]}.{s.right_column} [{s.source}]"
            for s in join_plan.steps
        ]

        # 6. Which rows count. Counted here, enforced at the compiler — a
        # default the model forgets is how "active employees" quietly includes
        # the leavers.
        machine.start("filters")
        defaults = self._default_filters(source, join_plan.tables)
        machine.done("filters", n=len(defaults))

        # 7. One model call.
        machine.start("generate")
        cards = self._cards(source, join_plan.tables, resolved_question)
        result = plan_query(
            question=resolved_question,
            datasource=source.id,
            dialect=source.dialect,
            cards=cards,
            provider=self.provider,
            entitled=entitled_fqns,
            join_steps=[
                s.as_sql({t: t.split(".")[-1] for t in join_plan.tables}) for s in join_plan.steps
            ],
            resolved_dates=[(d.label, *d.as_params()) for d in outcome.pre.dates],
            context=ctx.to_prompt(),
            guidance=self.healing.guidance(source.dialect),
            unreachable=join_plan.unreachable,
        )
        answer.llm_calls = result.calls
        if not result.ok or result.plan is None:
            problem = result.errors[0] if result.errors else "no plan"
            machine.fail("generate", problem)
            # A rejected object that is a view earns the view answer. Saying
            # "not in the catalog" about a table the user can plainly see in
            # their BI tool is the least helpful true thing available.
            view = self._view_named_in(problem, source)
            if view:
                return self._reply(
                    answer,
                    machine,
                    ctx,
                    started,
                    "view_not_queryable",
                    view=view,
                    tables=", ".join(t.split(".")[-1] for t in join_plan.tables)
                    or "the base tables",
                )
            return self._reply(answer, machine, ctx, started, "ambiguous_intent")
        plan = result.plan
        machine.done("generate")

        if plan.clarification is not None:
            answer.clarification = plan.clarification.model_dump()
            answer.text = plan.clarification.question
            return self._reply(answer, machine, ctx, started, None)

        answer.assumptions = [a.model_dump() for a in plan.assumptions]

        # 8, 9, 10. Resolve, guard, apply policy — in that order, always.
        machine.start("guard")
        prepared = self._prepare(
            plan.sql or "",
            source,
            grants,
            join_plan.tables,
            assumptions=self._assumptions(source, join_plan.tables),
        )
        if prepared.get("error"):
            machine.fail("guard", prepared["error"])
            return self._reply(
                answer, machine, ctx, started, "policy_blocked", detail=prepared["error"]
            )
        sql = prepared["sql"]
        answer.sql = sql
        for rationale in prepared.get("assumptions", []):
            answer.assumptions.append(
                {"text": rationale, "editable": True, "source": "catalog_default"}
            )
        machine.done("guard", n=prepared["checks"])

        # 11. Execute.
        machine.start("execute", datasource=source.id)
        params = {p.name: p.value for p in plan.params}
        try:
            executed = DbapiExecutor(source.connect, source.dialect).run(
                ExecutionRequest(
                    sql=sql, dialect=source.dialect, params=params, row_limit=self.row_limit
                )
            )
        except ExecutionError as error:
            machine.fail("execute", error.message.splitlines()[0][:80])
            return self._on_execution_error(answer, machine, ctx, started, error, source)

        machine.done("execute", rows=executed.row_count, ms=executed.ms)
        answer.columns = executed.columns
        answer.rows = executed.rows
        answer.truncated = executed.truncated

        # 12. Answer, from the template — no second model call.
        machine.start("answer")
        first = executed.first()
        if first and plan.answer_template:
            answer.text = plan.render_answer(first)
        elif not executed.rows:
            answer.text = self.policy.respond(
                "no_rows",
                {
                    "filters": ", ".join(c.label for c in ctx.filters) or "none",
                    "suspect": defaults[0] if defaults else "none",
                },
            ).text
        else:
            answer.text = f"{executed.row_count} rows."
        machine.done("answer")

        ctx.last_sql = sql
        ctx.last_plan_id = f"{source.id}:{ctx.fingerprint()}"
        ctx.last_answer = answer.text
        for expression in defaults:
            ctx.add_filter(
                FilterChip(
                    id=expression,
                    label=expression,
                    source="catalog_default",
                    rationale="catalog default",
                )
            )

        return self._reply(answer, machine, ctx, started, None)

    # ── stages ──────────────────────────────────────────────────────────────

    def _cards(self, source: Source, fqns: Sequence[str], question: str) -> list[SchemaCard]:
        cards: list[SchemaCard] = []
        for fqn in fqns:
            node = self.graph.table(fqn)
            if node is None:
                continue
            types = source.column_types.get(fqn, {})
            columns = [(name, types.get(name, "")) for name in node.columns]
            cards.append(
                SchemaCard(
                    fqn=fqn,
                    columns=prune_columns(columns, question),
                    description=" ".join(sorted(node.terms))[:160],
                    default_filters=source.default_filters.get(fqn, []),
                )
            )
        return cards

    def _default_filters(self, source: Source, fqns: Sequence[str]) -> list[str]:
        out: list[str] = []
        for fqn in fqns:
            out.extend(source.default_filters.get(fqn, []))
        return out

    def _view_named_in(self, problem: str, source: Source) -> str:
        """Is the object this complaint names a view we crawled?"""
        for node in self.graph.tables():
            if not node.is_view or node.datasource != source.id:
                continue
            if node.name.lower() in problem.lower():
                return node.relname
        return ""

    def _assumptions(self, source: Source, fqns: Sequence[str]) -> list[tuple[str, str, str]]:
        """Catalog defaults, as (table, predicate, rationale)."""
        out: list[tuple[str, str, str]] = []
        for fqn in fqns:
            for expression in source.default_filters.get(fqn, []):
                out.append((fqn, expression, f"{expression} (catalog default)"))
        return out

    def _prepare(
        self,
        sql: str,
        source: Source,
        grants: GrantSet,
        fqns: Sequence[str],
        assumptions: Sequence[tuple[str, str, str]] = (),
    ) -> dict[str, Any]:
        """Resolve identifiers, guard, then compile policy. Order is not optional.

        Identifiers first, because the guard's allow-list compares names and a
        mis-spelled one would be rejected for the wrong reason. Policy last,
        because it adds predicates the guard has no business rejecting.
        """
        relnames = {f.split(".", 1)[1]: False for f in fqns}
        columns = {
            f.split(".", 1)[1]: list(self.graph.table(f).columns)
            for f in fqns
            if self.graph.table(f) is not None
        }

        resolved = rewrite_identifiers(sql, Catalog(columns, dialect=source.dialect))
        if not resolved.ok:
            problem = resolved.errors[0] if resolved.errors else resolved.ambiguities[0].message
            return {"error": problem}

        verdict = check(
            resolved.sql,
            GuardContext(dialect=source.dialect, tables=relnames, row_limit=self.row_limit),
        )
        if not verdict.ok:
            return {"error": verdict.findings[0].message if verdict.findings else "rejected"}

        compiled = compile_policies(
            verdict.sql, grants, source.id, source.dialect, assumptions=assumptions
        )
        if not compiled.ok:
            return {"error": compiled.rejections[0]}

        return {
            "sql": compiled.sql,
            "checks": 12 + len(compiled.filters_applied),
            "assumptions": compiled.assumptions_applied,
        }

    def _on_execution_error(
        self,
        answer: Answer,
        machine: StepMachine,
        ctx: ConversationContext,
        started: float,
        error: ExecutionError,
        source: Source,
    ) -> Answer:
        """Classify, learn, and say both things: the business one and the real one."""
        diagnosis = healing.diagnose(error.message, source.dialect)
        self.healing.observe(diagnosis, source.dialect)
        plan = healing.plan_repair(diagnosis)

        scenario = {
            "permission_denied": "policy_blocked",
            "timeout": "timeout",
            "too_many_rows": "too_many_rows",
        }.get(diagnosis.kind, "execution_error")

        reply = self.policy.respond(
            scenario,
            {
                "error": error.message.splitlines()[0],
                "seconds": 30,
                "filters": ", ".join(c.label for c in ctx.filters) or "none",
            },
        )
        answer.text = reply.text
        answer.suggestions = reply.suggestions
        answer.error = {
            # Two layers, deliberately. The business line is what happened; the
            # technical line is the engine's own words, which is the only thing
            # useful to whoever has to fix it.
            "business": reply.text,
            "technical": error.message,
            "kind": diagnosis.kind,
            "next": plan.detail or diagnosis.hint,
            "retryable": "yes" if plan.diagnosis.retryable else "no",
        }
        return self._reply(answer, machine, ctx, started, None)

    def _reply(
        self,
        answer: Answer,
        machine: StepMachine,
        ctx: ConversationContext,
        started: float,
        scenario: str | None,
        **facts: Any,
    ) -> Answer:
        if scenario:
            reply = self.policy.respond(scenario, {**self.facts, **facts})
            answer.text = reply.text or answer.text
            answer.suggestions = reply.suggestions or answer.suggestions
            answer.scenario = scenario
        answer.steps = machine.trace()
        answer.panel = ctx.to_panel()
        answer.ms = int((time.perf_counter() - started) * 1000)
        return answer


def dialect_of(source_id: str, sources: Sequence[Source]) -> str:
    match = next((s for s in sources if s.id == source_id), None)
    return dialects.get(match.dialect).name if match else "duckdb"
