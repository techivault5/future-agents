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
from beta_queries.catalog import readiness as readiness_mod
from beta_queries.context.harvest import harvest
from beta_queries.context.model import ConversationContext, FilterChip
from beta_queries.dialogue.policy import DialoguePolicy
from beta_queries.dialogue.turn import handle_turn
from beta_queries.entitlements.resolver import EntitlementResolver, GrantSet
from beta_queries.errors.report import ErrorMessages
from beta_queries.progress import StepMachine
from beta_queries.routing.router import SourceProfile, route, score_source
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
    # fqn -> column -> distinct example values, PII columns excluded. The
    # largest measured lever on accuracy: without them the model sees column
    # names and types and has to guess what the columns hold.
    column_values: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    # fqn -> the table comment a DBA wrote, when one exists.
    comments: dict[str, str] = field(default_factory=dict)


# Why a model call produced no plan, in words the person fixing it can act on.
MODEL_FAILURE_REASONS = {
    "timeout": "the model took longer than BQ_LLM_TIMEOUT_SECONDS to reply; try again in a moment",
    "truncated": "the model's reply was cut off at BQ_LLM_MAX_TOKENS; raise it and ask again",
    # Not "try again": a missing or wrong key fails identically every time.
    "auth": (
        "the model credentials are missing or were rejected — check LUNA_API_KEY, "
        "LUNA_BASE_URL and LUNA_MODEL"
    ),
    "unavailable": "the model endpoint could not be reached; try again in a moment",
}


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
        errors_config: str | None = None,
        readiness: Any = None,
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
        self.messages = ErrorMessages.from_file(errors_config) if errors_config else ErrorMessages()
        # Optional. Without it every source is assumed ready, which is correct
        # for a catalog crawled before this process started.
        self.readiness = readiness
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
        datasource: str | None = None,
    ) -> Answer:
        """Answer one turn.

        `datasource` pins the question to one source and skips routing. With
        several sources and thin routing signals — no synonyms, no value index
        — auto-routing picks wrong or asks "which database?", and both read as
        an inaccurate answer. Pin first; unpin once `--debug` shows the route
        scores separating cleanly.
        """
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

        # 3. Which database — pinned by the caller, or routed.
        machine.start("route")
        if datasource is not None:
            pinned = next((s for s in usable if s.id == datasource), None)
            if pinned is None:
                # Unknown and not-entitled read the same on purpose: saying
                # which one it is would tell the asker the source exists.
                machine.fail("route", f"{datasource} is not available")
                return self._reply(
                    answer,
                    machine,
                    ctx,
                    started,
                    "out_of_scope",
                    sources=", ".join(s.id for s in usable),
                )
            source, why = pinned, "pinned by the caller"
        else:
            decision = route(resolved_question, [s.profile for s in usable])
            if not decision.confident:
                scenario = "ambiguous_source" if decision.needs_clarification else "out_of_scope"
                machine.fail("route", decision.reason)
                return self._reply(
                    answer,
                    machine,
                    ctx,
                    started,
                    scenario,
                    sources=", ".join(s.id for s in usable),
                )
            source = self.sources[decision.chosen]
            why = decision.candidates[0].reasons[0] if decision.candidates[0].reasons else ""
        machine.done("route", datasource=source.id, why=why)
        answer.datasource = source.id
        ctx.datasource = source.id

        # 3b. Is that database actually readable yet? A question asked while
        # the metadata is still landing gets narration, a caveat, or a queue
        # slot — never a silent wait, because the user cannot tell a slow
        # system from a broken one.
        caveat = self._check_readiness(answer, machine, source)
        if caveat is not None and answer.error is not None:
            return self._reply(answer, machine, ctx, started, None)

        # 4 and 5. Which tables, and how they connect — both from the graph.
        machine.start("schema")
        entitled_fqns = {t for t in grants.tables if t.startswith(f"{source.id}.")}
        candidates = self.candidates_for(resolved_question, source, entitled_fqns)
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
            # A timeout, a truncated reply and a rejected key are not
            # ambiguity, and saying they are sends the user off rephrasing a
            # question that was fine.
            reason = MODEL_FAILURE_REASONS.get(result.failure)
            if reason:
                answer.error = {"stage": "generate", "kind": result.failure, "technical": problem}
                return self._reply(
                    answer, machine, ctx, started, "model_unavailable", reason=reason
                )
            return self._reply(answer, machine, ctx, started, "ambiguous_intent")
        plan = result.plan
        machine.done("generate")

        if plan.clarification is not None:
            answer.clarification = plan.clarification.model_dump()
            answer.text = plan.clarification.question
            return self._reply(answer, machine, ctx, started, None)

        # Extend, never replace: a sync caveat added earlier in this turn is an
        # assumption too, and overwriting it is how "I answered from a partial
        # catalog" silently stops being said.
        answer.assumptions.extend(a.model_dump() for a in plan.assumptions)

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
            return self._on_rejection(answer, machine, ctx, started, prepared["error"], source)
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

        # What the turn actually asked, so the next one can say "and in
        # Germany?" and still know what "and" refers to. Without this the
        # context has a last_plan_id and nothing else, and the rewrite
        # rebuilds a question with no subject in it.
        state = harvest(prepared.get("user_sql", ""), source.dialect, params)
        if state.metric:
            ctx.metric = state.metric
        if state.grain:
            ctx.grain = state.grain
        for column, value in state.filters:
            ctx.add_filter(
                FilterChip(
                    id=column,
                    label=f"{column} = {value}",
                    column=column,
                    value=value,
                    source="question",
                )
            )

        for expression in defaults:
            default_state = harvest(f"SELECT 1 FROM t WHERE {expression}", source.dialect, params)
            column, value = (default_state.filters or [(None, None)])[0]
            ctx.add_filter(
                FilterChip(
                    id=column or expression,
                    label=expression,
                    column=column,
                    value=value,
                    source="catalog_default",
                    rationale="catalog default",
                )
            )

        return self._reply(answer, machine, ctx, started, None)

    # ── stages ──────────────────────────────────────────────────────────────

    def candidates_for(
        self, question: str, source: Source, entitled: set[str] | None = None
    ) -> list[Any]:
        """The tables a question could be about, ranked — exactly as ask() ranks them.

        Public so the diagnostic shows what was actually used rather than a
        re-derivation that could drift from it.
        """
        return self.graph.candidate_tables(
            question,
            entitled=entitled,
            datasource=source.id,
            synonyms=source.profile.synonyms,
            value_hits=score_source(question, source.profile).matched_values,
        )

    def _cards(self, source: Source, fqns: Sequence[str], question: str) -> list[SchemaCard]:
        cards: list[SchemaCard] = []
        for fqn in fqns:
            node = self.graph.table(fqn)
            if node is None:
                continue
            types = source.column_types.get(fqn, {})
            columns = [(name, types.get(name, "")) for name in node.columns]
            kept = prune_columns(columns, question)
            values = source.column_values.get(fqn, {})
            cards.append(
                SchemaCard(
                    fqn=fqn,
                    columns=kept,
                    # A DBA's comment when there is one. The old fallback — the
                    # table's sorted search terms — reads to a model as noise.
                    description=(source.comments.get(fqn) or "")[:200],
                    # The crawl stores these with an `{alias}` placeholder for
                    # the compiler to fill. Shown raw, a model can copy the
                    # literal `{alias}` into its SQL.
                    default_filters=[
                        e.replace("{alias}", fqn.rsplit(".", 1)[-1])
                        for e in source.default_filters.get(fqn, [])
                    ],
                    # SchemaCard has always rendered these as "e.g. …"; nothing
                    # filled them, so the model never saw what a column holds.
                    sample_values={name: values[name] for name, _ in kept if values.get(name)},
                )
            )
        return cards

    def _default_filters(self, source: Source, fqns: Sequence[str]) -> list[str]:
        out: list[str] = []
        for fqn in fqns:
            out.extend(source.default_filters.get(fqn, []))
        return out

    def _check_readiness(self, answer: Answer, machine: StepMachine, source: Source) -> str | None:
        """Narrate the sync, add a caveat, or queue. Returns the caveat if any."""
        if self.readiness is None:
            return None

        state = self.readiness.get(source.id)
        verdict = readiness_mod.decide(state)

        if verdict.action == "ready":
            return None

        if verdict.action == "failed":
            answer.error = {
                "kind": "connection",
                "business": f"I couldn't read {source.id} — {state.error}",
                "technical": state.error,
                "what_now": "This is an infrastructure problem, not your question.",
                "stage": "sync",
                "retryable": True,
                "needs_user": False,
                "incident_id": f"{source.id}:sync",
                "redacted": False,
                "suggestions": [],
                "what_the_system_is_doing": "Retrying the crawl.",
            }
            answer.text = answer.error["business"]
            machine.fail("sync", state.error)
            return ""

        machine.start("sync", datasource=source.id)
        machine.progress("sync", seen=state.tables_seen, total=state.tables_total or "?")

        if verdict.action == "queue":
            # Taking the question is the honest option: we cannot answer it
            # yet and we know who to tell when we can.
            answer.error = {
                "kind": "not_ready",
                "business": (
                    f"I'm still reading {source.id} — {verdict.reason}. "
                    "I'll let you know the moment I can answer this."
                ),
                "technical": state.describe(),
                "what_now": "Your question is queued against that sync.",
                "stage": "sync",
                "retryable": True,
                "needs_user": False,
                "incident_id": f"{source.id}:sync",
                "redacted": False,
                "suggestions": [],
                "what_the_system_is_doing": "Reading the metadata now.",
            }
            answer.text = answer.error["business"]
            machine.fail("sync", verdict.reason)
            return ""

        if verdict.action == "wait":
            machine.done("sync_wait", eta=int(verdict.eta_seconds or 0))

        machine.done("sync", tables=state.tables_seen, joins="?")
        if verdict.caveat:
            answer.assumptions.append({"text": verdict.caveat, "editable": False, "source": "sync"})
        return verdict.caveat

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
            # The model's own SQL, before policy injected anything. This is
            # what the context harvests: an RLS predicate must never become a
            # removable chip the asker can see, or ask to drop.
            "user_sql": verdict.sql,
            "checks": 12 + len(compiled.filters_applied),
            "assumptions": compiled.assumptions_applied,
        }

    def _on_rejection(
        self,
        answer: Answer,
        machine: StepMachine,
        ctx: ConversationContext,
        started: float,
        problem: str,
        source: Source,
    ) -> Answer:
        """A rejection before execution still deserves both layers.

        Nothing threw, so there is no engine message — the technical layer is
        our own reason, which is the honest thing to show: this was our
        decision, not the database's, and nothing ran.
        """
        blocked = any(
            marker in problem.lower() for marker in ("not readable", "row by row", "aggregate")
        )
        scenario = "policy_blocked" if blocked else "ambiguous_intent"
        reply = self.policy.respond(scenario, {**self.facts, "detail": problem})

        answer.text = reply.text or problem
        answer.suggestions = reply.suggestions
        answer.error = {
            "kind": "rejected_before_execution",
            "business": reply.text or problem,
            "technical": problem + (f"\n\nSQL:\n{answer.sql}" if answer.sql else ""),
            "what_now": "Nothing ran against the database.",
            "stage": "guard",
            "retryable": False,
            "needs_user": True,
            "incident_id": "",
            "redacted": False,
            "suggestions": list(reply.suggestions),
            "what_the_system_is_doing": "No query was executed.",
        }
        answer.scenario = scenario
        return self._reply(answer, machine, ctx, started, None)

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
        report = self.messages.build(
            diagnosis,
            sql=answer.sql or "",
            dialect=source.dialect,
            # Only what this person may already see. A not-found naming
            # anything else is redacted, because three of six engines merge
            # "denied" into "not found" precisely so it cannot be probed.
            entitled_objects=sorted(answer.tables),
            incident_id=f"{source.id}:{diagnosis.kind}:{diagnosis.subject or '-'}",
            suggestions=reply.suggestions,
        )
        answer.text = report.business
        answer.suggestions = report.suggestions
        answer.error = report.as_dict()
        answer.error["what_the_system_is_doing"] = plan.detail or diagnosis.hint
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
