# Beta Queries — design record

> Companion to `docs/beta-queries-spec.md` (what it does) and
> `docs/beta-queries-handoff.md` (what exists today). This file is the
> **why**: the bets the design makes, and the four flaws a review caught
> before they were built on.

> **Status: idea captured, core built, remainder documented.** This is the
> document to hand to a person or an LLM picking the work up. The code that
> exists is real and tested; the code that does not is specified here with the
> reasoning that shaped it, including four design flaws found and corrected
> before anything was built on them.

## The idea in one page

Ask a question in plain English. Get back the SQL (formatted, in an editor),
the result grid, a written answer, and the live context of the conversation in
a panel beside the chat — all scoped to the databases you are actually
entitled to see. Six engines: SQL Server, Postgres, Snowflake, Databricks,
MySQL, DuckDB.

**The bet:** the model's job is small. Routing, table selection, join paths,
dates, identifier spelling, row filters and masks are all decided
*deterministically* before the model is called, and validated again after.
What is left — the projection and the predicates — is the part a model is
genuinely good at. Every fact handed over is a fact it cannot get wrong.

Eleven stages, each removing a way for the next to be wrong:

```
turn → entitlements → route → tables → joins → PLAN (one model call)
     → identifiers → guard → policy → execute → heal
```

**Five ideas carry the design:**

1. **The catalog lives in a graph, not a cache.** "Which tables answer this"
   and "how do they join" are traversals. A cache answers "what did I store
   under this key"; it cannot answer "what is the cheapest route from
   `absence` to `department`". Redis is the copy you read; Neo4j is the truth.
2. **Identifiers come from the catalog, never from the model.** A model cannot
   know how a column was spelled at DDL time. `written → catalog → quoted for
   this engine`, resolved after generation and before the guard.
3. **Base tables only.** A view hides its grain, filters and joins, so a number
   from one cannot be explained. Refused by name, with the base tables offered.
4. **Every failure says it twice** — once in the words of the job, once in the
   engine's own words — and the technical half is redacted where it would leak
   the existence of an object the asker cannot see.
5. **One model call before execution, one repair after.** An agentic loop does
   not fit in two seconds, and a second repair has the same success rate as the
   first at twice the cost.

## Context

Beta Queries is a text-to-SQL feature: ask in plain English, get formatted SQL, a
result grid, a written answer and the live conversation context — scoped to the
databases the asker is entitled to see. Six engines: SQL Server, Postgres,
Snowflake, Databricks, MySQL, DuckDB.

### Where this started

Fourteen modules existed, covered by 237 tests — dialects, identifiers, guard,
healing, crawler, graph, semantics, router, profile memory, the 30-scenario
conversation layer, catalog sync, the eval corpus and the Airflow DAG — and
**none of it could answer a single live question.** Every module that *talks to
anything* was missing: orchestrator, LLM provider, compiler, executor,
entitlements. An inventory also found `agent.yaml` declaring **seven tool
endpoints pointing at modules or functions that did not exist** — a contract
that lied to the model about its own tools.

That gap is now closed (Parts 0, 1, 1b and 2 below), and four further things
were asked for on top:

1. When something fails, the user gets **two explanations** — one in business
   terms, one the verbatim engine error — plus an acknowledgement that it is
   being worked on.
2. The system **fixes itself behind the scenes**: targeted re-crawl, Neo4j
   update, re-profiling, and a learned lesson so the same failure stops
   recurring.
3. The user is **notified when it is fixed** and can replay their question.
4. The catalog captures **what a table actually contains**, not just its column
   names, so the next question has enough context to route well.

### Decisions taken (from the user)

| | |
|---|---|
| Autonomy | Auto-fix facts read from the database; **propose** anything inferred (joins, synonyms, semantics) for human approval |
| Notification | In-app pending notification **and** email |
| Table descriptions | **LLM description for every table**, at least once — with content-hash caching so it is paid for once, not per crawl |
| Scope | Error layer + remediation + notifications **and** the runnable vertical slice |

### What running it caught that reading it would not

**377 tests, ruff and guardrails clean.** `python scripts/beta_queries_demo.py`
answers real questions against DuckDB with no Redis, no Neo4j and no model key.
Five bugs that only a running system surfaces:

- `@p0` is DuckDB's **absolute-value operator** — sqlglot parses it as `ABS(p0)`.
  Only `:p0` is a placeholder on all six engines; `$p0` is a column on T-SQL and
  MySQL. The planner now rejects the wrong sigil by name.
- The catalog default was **counted and never applied** — "how many people in
  India" answered 3 while calling them active; two are.
- A view got a generic refusal instead of the view answer.
- The answer template broke when the identifier layer renamed a column.
- `StepMachine` rendered `{datasource}` literally when no args were passed.

### Build order at a glance

| # | Part | Why here | Status |
|---|---|---|---|
| 0 | Fix the lying contract + free wins | Everything builds on the contract | ✅ |
| 1 | The runnable slice (entitlements → provider → planner → compiler → executor → orchestrator) | Nothing else is honestly testable until a question can be answered | ✅ |
| 1.7 | `app.py` + SSE | the HTTP surface | ⬜ |
| 1b | Sync on discovery + readiness narration | Needs the orchestrator to narrate into | ✅ |
| 2 | Two-layer errors | Needs a real executor to produce real errors | ✅ |
| 3 | Incidents + remediation — **staged, see below** | Needs errors to act on | ⬜ |
| 4 | Notifications | Needs incidents to notify about | ⬜ |

Part 3 is **not one step**. The review's strongest argument is that the
automatic trigger should be last, not first, because operator accept/reject
decisions are the only honest evidence for what is safe to automate:

| 3a | `ErrorReport` alone — no incident, no worker | most of the user-visible value, near-zero risk |
| 3b | Incidents, **observe-only** — open/join, record waiters, operator view | learns the true incident cardinality with zero blast radius |
| 3c | `probe_object` — **read-only**, surfaced in the operator view | no writes at all |
| 3d | Manual apply — an operator reads the probe and clicks | builds the labelled dataset for 3e |
| 3e | Auto-apply **one kind, one datasource, behind a flag** (`identifier_case`) | narrowest, purely factual, smallest blast radius |
| 3f | `RemediationWorker` as scheduler wiring — lease, backoff, cap, abandon | last |
| 5 | Table profiling + LLM descriptions | Independent; improves routing everywhere | yes |
| 6 | Bundle for download | Last | yes |

Parts 5 and 6 can be done in parallel with anything after Part 1.

---

## Part 0 — Fix what is already broken (do this first, it is small)

`apps/beta_queries/agent.yaml` declares nine tools; **seven point at nothing**.
The model is being told it has tools that cannot be called.

| Tool | Declared endpoint | Reality |
|---|---|---|
| `catalog.search` | `retrieval.hybrid:search` | module missing |
| `catalog.join_path` | `catalog.graph:join_paths` | module exists, **function does not** (it is a method, `join_plan`) |
| `values.resolve` | `retrieval.values:resolve` | module missing |
| `context.get` | `context.store:get` | module missing |
| `sql.execute` | `sql.executor:run` | module missing |
| `memory.lookup` | `memory.cache:lookup` | module missing |
| `catalog.describe` | `catalog.cards:describe` | module missing |

Also free wins found in the inventory:

- `catalog/crawler.py` **captures** `table.comment` and `column.comment` from the
  engine, then `build_source_profile()` **never reads them**. DBA-written
  descriptions are sitting unused. Feed them into `table_terms`/`column_terms`.
- `Table.row_estimate`, `Table.grain`, `Column.null_fraction` and
  `JoinEdge.cardinality` are declared and never populated.
- `TableNode.metrics`, `bi_assets`, `success_count` exist in the graph and
  nothing in the crawl path fills them.
- `ambiguous_intent` in `healing.py` has a strategy and a hint but **no regex**,
  so `diagnose()` can never return it. Either give it patterns or document that
  only a caller raises it.
- `pyodbc~=5.1` is in spec §19's dependency list and missing from `pyproject.toml`.

**Add a test that every `endpoint:` in `agent.yaml` imports and resolves.** A
contract that lies is worse than no contract, and this must never regress.

---

## Part 1 — The runnable slice

Nothing else can be tested honestly until a question can actually be answered.
Build in this order; each step is independently testable.

### 1.1 `entitlements/resolver.py` + `entitlements/policy.py`
`GrantSet` (which tables this principal may read), `ent_hash` for cache keying,
Redis snapshot with a 60s TTL, and the RLS/mask predicates the compiler injects.
Resolve from the graph (`(:User)-[:MEMBER_OF]->(:Group)-[:GRANTED]->(:Table)`)
behind an adapter, because where entitlements actually live is still an open
question — see **Open questions**. Ship an `InMemoryEntitlements` so everything
downstream is testable today.

### 1.2 `agent/providers.py`
One `Provider` protocol, three implementations: **GPT Luna** (the real target),
Anthropic, and `EchoProvider` — a deterministic stub returning a canned
`QueryPlan` so the whole pipeline is testable in CI with no key and no spend.
The API key is a call argument, never module state, never logged.

### 1.3 `agent/prompts.py` + `agent/planner.py`
Prompt assembly from: schema cards (entitled tables only), the join plan the
graph already resolved, the context object, the user's profile hints, and
`HealingMemory.guidance()` for this dialect. **One structured call** returning a
`QueryPlan` — the contract already exists in `agent/contract.py`.

### 1.4 `sql/compiler.py` + `sql/formatter.py`
AST rewrite: inject RLS predicates and masks, bind parameters, apply the row cap
in the dialect's own spelling. Then pretty-print to house style — this is what
makes the query look like a 20-year engineer wrote it.

### 1.5 `sql/executor.py`
Read-only execution **as the asker**, statement timeout, row cap, cancellation.
Returns rows *or* an `ExecutionError` carrying the verbatim engine message,
which is the input to the whole error layer.

### 1.6 `orchestrator.py`
The stage machine that wires it all together and drives `progress.StepMachine`
so the narration is server-driven. Owns the deadline policy: what to degrade
when the 2s budget is at risk.

### 1.7 `app.py` + `api/routes.py` + `api/schemas.py`
FastAPI with SSE, following `apps/finance_advisor/app.py` as the house
precedent. Endpoints: `POST /ask`, `GET /stream/{id}`, `POST /feedback`,
`GET /notifications`, `POST /notifications/{id}/replay`.

**Checkpoint:** `POST /ask` answers a question against DuckDB with the
`EchoProvider`, end to end, in CI, with no external services.

---

## Part 1b — Sync on discovery, and answering while it is still syncing

A datasource is useless until its metadata is in the graph, and waiting for the
nightly DAG means a database connected at 10am is unusable until 5am tomorrow.

### Registration triggers the crawl immediately
Adding a source to `data/config/beta_queries_sources.yaml` — or calling
`POST /sources` — enqueues a crawl **now**, in the background, rather than
waiting for the schedule. Structure first (fast, minutes), then joins, then
value profiling, then descriptions (slow). Each phase publishes readiness as it
completes, so the catalog becomes **progressively** useful instead of
all-or-nothing.

### `catalog/readiness.py` — a state machine per datasource
```
unknown -> syncing -> partial -> ready
                   \-> failed
state: {status, phase, tables_seen, tables_total, pct, started_at, eta, error}
```
Stored in the KV so every process sees the same answer, and published on the
EventBus (`catalog.sync.*`) — which would be that bus's **first real
subscriber**; it has none today.

Phases and what each unlocks:

| Phase | Unlocks | Status |
|---|---|---|
| structure | table and column names — routing and identifier resolution work | `partial` |
| joins | multi-table questions | `partial` |
| values | "India" resolves to a literal | `partial` |
| descriptions | best routing on unfamiliar names | `ready` |

### Asking a question while a sync is running
The orchestrator checks readiness **before** routing and takes one of three
paths — the choice is by remaining work, not by guesswork:

1. **Nearly done** (structure complete, ETA within the budget) → **wait and
   narrate.** The chat streams the sync steps, then continues into the normal
   answer flow.
2. **Usable but incomplete** → **answer, with a visible caveat chip**: *"I'm
   still reading `salesdb` — I answered from what I have. This may be
   incomplete."* Honest beats blocked.
3. **Not usable yet** (structure not finished, or the source failed) → **queue
   the question** against the sync, and reuse the Part 4 notification: *"I'm
   still reading that database. I'll tell you the moment I can answer this."*
   When the phase completes, the waiter is notified with a one-click replay.

That third path is the same machinery as the incident waiters — one
notification system, two producers.

### Narration
New steps in `data/config/beta_queries_steps.yaml`, driven by the existing
`progress.StepMachine`, so the chat reads:

```
Syncing metadata for salesdb…        412 of ~900 tables
Metadata ready                       900 tables, 214 joins
Looking for the right data source…   using salesdb — 'EMEA' resolves in customer.region
Reading table definitions…           3 tables, 2 joins resolved
Working out which records count…     1 filter applied
Writing the query…
Checking it is safe and uses base tables…  passed 12 checks
Running it against salesdb…          9 rows in 240 ms
```

Server-driven, never model-authored — the first step has to render at ~50ms and
the model does not answer until ~900ms.

Two small additions are needed to make this work, and only two:

- **New step ids in the YAML** (`sync`, `sync_wait`) — `StepMachine` already
  takes its steps from config, so this is data, not code.
- **A `progress(step_id, **fmt)` method** on `StepMachine`. Today a step goes
  `running -> done` once; a sync that takes four minutes needs to re-emit
  "412 of ~900 tables" while still running. Small, additive, and the existing
  `_emit`/`sink` path already carries it to SSE.

---

## Part 2 — Two-layer errors

### `errors/report.py`
```
ErrorReport:
  incident_id, stage, business, technical, what_now,
  can_retry, retry_after, suggestions
```

- **business** — what happened in the user's language and why, never an error
  code. *"The employee table doesn't have a field called 'report id' any more —
  it looks like it changed since I last read that database. I'm refreshing my
  map of it now."*
- **technical** — the engine's message, **verbatim**, plus the SQL. Never
  paraphrased: the person who can fix it needs the real string.
- **what_now** — the acknowledgement. *"I've raised this and I'm working on it.
  I'll tell you the moment it's fixed."*

Wording lives in **`data/config/beta_queries_errors.yaml`**, matching the
existing pattern of `beta_queries_dialogue.yaml` and `beta_queries_steps.yaml`
— a product owner edits the words, and nothing in that file can change what a
query does.

Every `kind` in `healing.py` gets an entry. Unknown kinds degrade to a generic
business line plus the real technical error, never a blank.

---

## Part 3 — Incidents and remediation

> **REVISED after design review.** Four things in the original Part 3 were
> verified wrong by running them. The corrections are below; the reasoning is
> in "What the review changed" at the end of this file.

### Prerequisite: the KV protocol cannot support this yet
`KV` is `get`/`set`/`delete`. There is **no way to enumerate open incidents**,
so the worker cannot find its own work, and no `SETNX`, so there is no lease
and two workers would duplicate every remediation. Extend `KV` with `nx=`,
set and sorted-set operations **before** anything else in this part. Spec §9
already requires `SET bq:lock:{qhash} NX EX 5` for stampede control, so this
was needed regardless.

### `incidents/store.py`
`Incident` keyed on **`(datasource_id, kind, object)`** — *not* the healing
signature.

Verified: `signature()` strips quoted literals to `'?'` by design, so
`Invalid column name 'employe_id'` and `Invalid column name 'custmer_nam'`
produce an identical hash. Keying on it would collapse **every**
`unknown_column` failure in a 40,000-table estate into one incident, and the
worker would have no idea which object to refresh — the discriminator is
stripped before hashing. The signature stays where it belongs, in
`HealingMemory`, where a generic lesson is the point.

The object cannot be read from the error either: SQL Server and Postgres name a
bare column with no table, Databricks names a query alias. The incident carries
the `QueryPlan.referenced_tables` for context, so it **cannot be built from
`diagnose(error)` alone** — `heal()` needs a context argument.

```
Incident: id, signature, kind, datasource, objects[], status,
          business, technical, remediation, attempts,
          waiters[] (hashed ids), replay{user -> question},
          opened_at, updated_at, resolved_at
status: open | remediating | resolved | needs_human | wont_fix
```
KV-backed (`memory/profile.py`'s `KV` protocol — Redis in prod, `DictKV` in
tests). The `KV`/`DictKV`/`user_key` trio should be **hoisted out of
`memory/profile.py`** into `memory/kv.py` so incidents and notifications can use
it without importing profile internals.

### `sync/targeted.py` — a read-only **probe**, not a re-crawl

The original "targeted re-crawl reusing `crawl()`" is wrong in four verified
ways, so the primitive changes shape:

- `diff_catalog` **always quarantines** it — 1 table against 4,000 is ratio
  0.00025, so it would be a guaranteed no-op that logs an error every time.
- `infer_joins` **inverts its own safety check** on a one-table datasource: the
  competing candidates that made a join ambiguous are absent, so joins the full
  crawl correctly refused become "unique". It would invent exactly the joins it
  was built to suppress.
- `build_source_profile`'s value index is **first-writer-wins and order
  dependent**; inserting one table out of order silently reassigns which column
  "India" resolves to, changing an unrelated question's routing.
- The `Runner` protocol is `run(sql)` with **no parameter channel**, so the
  obvious implementation interpolates a name lifted from an engine error —
  downstream of model output, downstream of user text — into SQL run by the
  *privileged catalog principal*. That violates "every literal bound".

So:

```
probe_object(datasource, relname) -> PRESENT(columns, exact_spelling) | ABSENT | UNKNOWN
refresh_object(datasource, relname)   # columns only, only when PRESENT and changed
```

Neither ever calls `crawl()`, `infer_joins`, `profile_values` or
`build_source_profile`. **Never prunes, never asserts absence** — ABSENT writes
a `missing_since` tombstone and the next full crawl does the deleting, with the
shrink guard intact.

Implementation: add an `{object_filter}` placeholder to the **existing**
`_COLUMNS_*` statements rather than writing a second family — the current ones
encode real per-engine bugs (T-SQL's `sys.tables`, Databricks never emitting
`BASE TABLE`, DuckDB's `duckdb_columns()` join) that a hand-written second set
would reintroduce. `Runner` gains `run(sql, params)` first.

**The honest remediation for catalog drift is "run the full crawl sooner", not
"patch one node."** The probe's job is to decide whether that is warranted,
plus the one narrow purely-factual fix: the exact spelling of a table already
in the graph.

### `remediation/worker.py`
`RemediationWorker(BaseWorker)` — the existing worker pattern fits exactly;
register it in `AgentSystem._register_default_workers()`
(`packages/future_agents/system.py`).

| Error kind | Action | Auto? |
|---|---|---|
| identifier_case, and unknown_column/table **only on engines that separate not-found from denied** | probe → refresh exact spelling, or schedule a full crawl | behind a per-datasource flag |
| unknown_table on **Snowflake, SQL Server, MySQL** | `needs_human` — see below | **never** |
| stale value index (see note) | re-profile that column's values | **yes** |
| missing or wrong join | write a `:PROPOSED` edge, unused until approved | no — propose |
| ambiguous column / semantics | propose a preferred mapping | no — propose |
| permission_denied | `needs_human`, raise an access request | no — never retry |
| timeout / too_many_rows | `needs_human` + user guidance | no |

**Note on the stale value index:** zero rows is *not* an engine error — nothing
throws, `diagnose()` never sees it, and `healing.py` has no kind for it. It is
raised by the answer stage (the `no_rows` scenario already in
`beta_queries_dialogue.yaml`) when a bound literal came from the value index and
matched nothing. That is a second, non-error producer of incidents, and the
incident store must accept both.

### The permission masquerade — the flaw that would have shipped a lie

Three of six engines **merge "you may not see it" into "it does not exist", on
purpose**, so you cannot probe for object existence. This is already in our own
patterns:

```
("unknown_table", r"object '([^']+)' does not exist or not authorized")   # Snowflake
```

Verified end to end: a Snowflake permission denial classifies as
`unknown_table` → `strategy=deterministic` → auto-remediate → the crawl runs as
the **read-only catalog principal**, which *can* see the object → catalog
refreshed → replay passes (it resolves identifiers, it does not execute) →
incident resolves → every waiter is told it is fixed → every one of them fails
again, identically. Not an edge case: the most common shape of this failure in
an enterprise estate, and the architecture produced it deterministically.

Three changes:

1. **Never auto-resolve a not-found on Snowflake, SQL Server or MySQL.** Absence
   is not conclusive on those engines, so it goes to `needs_human`.
2. **Never probe on `permission_denied`.** It tells you nothing about the user
   and generates audit noise on the most sensitive objects in the estate.
3. **Never say "fixed".** Say what is true: *"The catalog has been updated for
   `sales.orders`. Your question is ready to run again."* The retry executes
   under the **user's own principal**, which is the only place the truth lives.
   If it was permissions, they get an honest permission error instead of a lie.
   One wording change removes the whole class of false-positive notifications.

**And resolution is verified, never assumed.** Replay through identifier
resolution and the guard, **without executing**, before an incident closes.
That verifies the write landed; it cannot verify the hypothesis was right,
which is exactly why the notification promises a retry and not a fix.

### Information disclosure in the technical layer

"The verbatim engine error" will cheerfully show
`Invalid object name 'payroll.dbo.executive_comp'` to someone not entitled to
know that table exists — undoing, in the presentation layer, the metadata
hiding the database does on purpose. The technical layer is **redacted for
`permission_denied` and for not-found on unentitled objects**, and shown in
full only to operators or to users entitled to the object.

### Stopping, when the model of the problem is wrong

- **Attempt cap and exponential backoff** (2m → 10m → 1h → human). `BaseWorker`
  polls unconditionally and swallows failures, so without this a Snowflake
  object nobody can read is re-probed every two minutes forever.
- **Collapse levels**: `(ds, kind, object)` → `(ds, table)` → `(ds, schema)` →
  `(ds)`. A dropped schema of 30 tables × 20 columns is one incident, not 600.
- **Circuit breaker**, on the same reasoning as `SHRINK_GUARD`: above N new
  incidents for one datasource in M minutes, stop opening them, stop
  auto-remediating that datasource, open one "catalog drift suspected"
  incident, page a human, trigger a full crawl. A burst is evidence the
  per-object model is wrong, and the right response is to stop, not work harder.
- **An explicit `abandoned` state that tells the waiters honestly.** A TTL
  expiry is a silent drop with fifty people still waiting.
- **N distinct users before anything moves.** One person's typo must never be
  able to change the catalog.

### What must never be automated
Adding a table to the entitled catalog (a retrieval-scope change) · join edges,
**including "proposed"** — `neighbours()` has no status filter, so a proposed
edge is live the instant it lands, and proposals must therefore live in a
separate queue rather than as an attribute on an edge the planner reads ·
`Lesson.fix`, which is editing the model's prompt · default filters, which
decide every number the org sees · deleting or pruning anything from a targeted
path.

---

## Part 4 — Notifications

### `notify/pending.py`
Redis list per user: `bq:notify:{sha256(identity)}`. The chat surface drains it
on the next turn and offers a one-click replay of the exact original question.

### `notify/email.py`
`apps/finance_advisor/alerts.py::send_email` is already generic — same SMTP env
vars, returns a bool, degrades quietly when unconfigured. **Hoist it** to
`packages/future_agents/infrastructure/notifier.py` and have both callers import
it, rather than copying it across apps. It is blocking, so wrap it in
`asyncio.to_thread`.

**PII note:** the profile deliberately stores only a hash of the identity. Email
needs the real address, so it is stored **on the incident**, not on the profile,
and deleted when the incident closes. Add it to the pre-deploy security review.

---

## Part 5 — What a table actually contains

The crawler today records a comment **if a DBA wrote one** (they usually did
not) and derives nothing. This is the gap that makes routing weak on unfamiliar
table names.

### `catalog/profiler.py` — deterministic, free, every table
- **role**: fact / dimension / bridge / audit / staging / reference, from
  FK-out degree, measure count, PK shape and naming
- **grain**: from the primary or unique key — fills `Table.grain`, declared and
  never populated today
- key columns, measures, dimensions, date columns, **freshness** (max of the
  date column), `row_estimate`, `null_fraction`
- topics for routing, now including the **DBA comments that are currently
  ignored**

### `catalog/describe.py` — the LLM pass, once per table
Per the user's decision: **a description for every table.** Cost is bounded by
caching on a **content hash** (schema + role + sampled values), so a table is
described once and re-described only when its structure actually changes.
Batched, resumable, with `--dry-run` printing the estimated call count and cost
before spending anything.

Stored on the Neo4j `Table` node (`description`, `role`, `grain`, `topics`) and
fulltext-indexed, so it feeds routing and the schema cards.

`scripts/beta_queries_describe.py` — the one-time backfill CLI.

---

## What is documented but not built — and why it is written this way

Everything below is specified rather than implemented. The specification is the
deliverable; each item carries the reasoning that would otherwise be lost.

| Piece | The one thing that matters about it |
|---|---|
| `app.py` + SSE | The narration already exists as a step machine with a `sink`; the HTTP layer is plumbing, not design. |
| `incidents/` | Key on **`(datasource, kind, object)`**, never on the healing signature — verified: two different broken columns hash identically, because literals are stripped by design. |
| `sync/targeted.py` | A read-only **probe**, never a re-crawl. `diff_catalog` always quarantines a one-table refresh, and `infer_joins` inverts its own safety check on a single-table datasource. |
| `remediation/worker.py` | Last, not first. Ship 3a→3f in order; operator accept/reject decisions are the only honest evidence for what is safe to automate. |
| `notify/` | Say **"the catalog has been updated, your question is ready to run again"** — never "fixed". The retry runs as the user, which is the only place the truth lives. |
| `catalog/profiler.py` + `describe.py` | Deterministic role/grain/keys for free; LLM description per table cached on a **content hash**, so it is paid for once, not per crawl. |
| `retrieval/` | Only needed when term and value matching are not enough. Late, deliberately. |

### The trap that would have shipped a lie

Snowflake, SQL Server and MySQL **merge "you may not see it" into "it does not
exist"**, on purpose, so object existence cannot be probed. Verified end to
end: a Snowflake permission denial classifies as `unknown_table` →
`deterministic` → auto-remediate as the *catalog* principal (which can see it)
→ resolve → tell every waiter it is fixed → all of them fail again identically.

Three rules fall out, and they are why the remediation loop is staged:

1. Never auto-resolve a not-found on those three engines.
2. Never probe on `permission_denied`.
3. Never say "fixed".

## Part 6 — The code, captured

**42 modules · 4 config files · 12 test files · 2 entrypoints · 1 DAG · 2 docs.**

```
apps/beta_queries/
  orchestrator.py            the eleven stages, narrated
  dialects.py                what differs across six engines, encoded
  progress.py                server-driven narration (never the model)
  agent/      contract · prompts · planner · providers
  catalog/    models · crawler · graph · semantics · readiness
  sql/        identifiers · guard · compiler · executor · healing
  entitlements/resolver      deny-beats-allow, ent_hash, 60s snapshot
  errors/report              two layers, with redaction
  nlp/        preprocess · classify · rewrite      30 scenarios
  context/model              bounded typed context + panel
  dialogue/   policy · turn                        10 response modes
  routing/router             which database
  memory/profile             what this user means, 7-day sliding TTL
  eval/corpus                204,282 cases · 44 hazards · 264-case gate
  sync/plan                  crawl diffing with a partial-crawl quarantine

data/config/beta_queries_{sources,steps,dialogue,errors}.yaml
scripts/beta_queries_{demo,crawl}.py
airflow/dags/beta_queries_catalog_sync.py
tests/test_beta_queries_*.py                       12 files, 377 tests
docs/beta-queries-{spec,handoff}.md                33 sections
```

**Prove it in one command, with nothing external installed:**

```bash
pip install -e ".[beta_queries,dev]"
python scripts/beta_queries_demo.py
```

Hostile schema on purpose: a column called `report id`, one called `user`, a
case-sensitive `Status`, a view that looks like the obvious answer, and a
staging copy of the real table. It answers, refuses and explains all of them.

### Not in this drop

`app.py`/SSE · `incidents/` · `sync/targeted.py` · `remediation/worker.py` ·
`notify/` · `catalog/profiler.py` + `describe.py` · `retrieval/`. Each is
specified above with the reasoning that shaped it. Part 3 in particular must
ship **3a → 3f in order**; building the auto-remediation worker first is the
mistake the review caught.

---

## Verification

Every step below runs with **no external services** — DuckDB as the engine,
`DictKV` for Redis, `InMemoryGraph` for Neo4j, `EchoProvider` for the LLM.

### 1. The contract does not lie
```bash
pytest tests/test_beta_queries_agent_definition.py -q
```
New test: every `endpoint:` in `agent.yaml` imports and resolves to a callable.

### 2. End to end, for real, against a real database
```bash
python scripts/beta_queries_demo.py --engine duckdb
```
Builds a DuckDB file with deliberately hostile schema — a column called
`report id`, one called `user`, a view, a staging twin, an SCD2 pair — crawls
it, syncs the graph, asks a question and prints every stage. **This is the
acceptance test**: it must answer correctly, quoting `[report id]` properly and
refusing the view.

### 3. The sync narration
```bash
pytest tests/test_beta_queries_readiness.py -q
```
Asserts all three paths: wait-and-narrate, answer-with-caveat, and
queue-then-notify — including that a question queued during a sync is replayed
and notified on completion.

### 4. The healing loop actually closes
```bash
pytest tests/test_beta_queries_remediation.py -q
```
Drop a column from the DuckDB fixture mid-test, ask the question, assert:
the error carries both layers, an incident opens with the asker as a waiter,
the worker re-crawls, the graph updates, the **replay verification** passes,
and the waiter is notified. Then assert the negative: a `permission_denied`
incident is **never** auto-resolved.

### 5. The release gate
```bash
pytest -q                                                        # full suite
ruff check packages/future_agents/ apps/ scripts/
ruff format --check packages/future_agents/ apps/ scripts/
python packages/guardrails/guardrails_engine.py . --mode block   # exits 0
python scripts/beta_queries_eval.py --suite hazard               # 264 cases
```
A hazard case that should `clarify` and instead `answer`s fails the gate.

### 6. The bundle
```bash
python scripts/beta_queries_bundle.py
```
Unzips into a clean directory, `pip install -e ".[beta_queries,dev]"`, and
step 2 passes from the unzipped copy — proving it works on a machine that is
not this one.

---

## Open questions that do not block the build

These are adapter-shaped, so the build proceeds behind an interface and the
answer swaps in:

- **GPT Luna's contract** — structured output? embeddings? streaming? prefix
  caching? `providers.py` isolates this.
- **Where entitlements live today** — Entra groups, an RBAC table, SQL Server
  roles. `entitlements/resolver.py` is a thin adapter over whatever exists;
  `InMemoryEntitlements` unblocks everything until then.
- **SQL Server version** — 2025/Azure gives native `VECTOR` + DiskANN; 2022
  pushes ANN to Redis. Only affects retrieval, which is late in the order.

## Security review — required before any deploy

This touches **auth and PII** and `CLAUDE.md` mandates human review. Three
specifics this plan adds to the list:

1. Email addresses are now stored on incidents (the profile only ever held a
   hash). TTL-bounded and deleted on close, but it is new PII at rest.
2. The remediation worker writes to the catalog graph automatically. The blast
   radius is every user's future answers, so the auto/propose split matters and
   should be audited.
3. `agent.yaml` marks catalog text untrusted but **not the chat history** — an
   instruction planted in turn 1 can ride into turn 5. The
   `conversation_is_data` constraint is drafted and still not applied; it should
   land with this work.

---

## What the review changed, and what was verified

A design-review pass over the approved plan found four flaws. All four were
**verified by running them**, not taken on argument:

| Flaw | Verified how | Status |
|---|---|---|
| Incident keyed on the healing signature collapses unrelated failures | Two different broken columns produce an identical signature — literals are stripped by design | **plan corrected** |
| Snowflake/SQL Server/MySQL merge "denied" into "not found", so the loop tells users a permission problem is fixed | `diagnose()` on the real Snowflake string returns `unknown_table` / `deterministic` | **plan corrected** |
| A re-crawl discards curated metadata | `metrics` and `bi_assets` lost on the second `upsert_table` | **fixed and committed (`fbad454`)** |
| `diff_catalog` always quarantines a one-table refresh | 1 vs 4,000 → quarantined | **plan corrected** |

Two further pre-existing bugs it surfaced, one now fixed:

- The Cypher `UPSERT_TABLE` never removed vanished columns — a dropped column
  lived in the graph forever, which is the drift a refresh exists to correct.
  **Fixed in `fbad454`.**
- `InMemoryGraph.neighbours()` has no edge-status filter, so a "proposed" join
  edge would be live the moment it was written. This is why proposals must be a
  separate queue, not an attribute — noted above, not yet built.

### The one piece of good news in the review

`rewrite_identifiers` and `G06` already catch invented identifiers *before*
execution. So the failures that survive to the executor are disproportionately
**real drift** rather than model invention — which strengthens the case for the
loop and shrinks its expected volume considerably. That is also the argument
for staging it: size it from measured data rather than from imagination.
