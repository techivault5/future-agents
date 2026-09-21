# Beta Queries — handoff

Point an LLM at this file. It says what exists, what is true, what is next, and
what must never change.

## Read in this order

| | |
|---|---|
| 1 | `docs/beta-queries-spec.md` — §29 stores · §30 identifiers · §31 healing · §32 sync · §33 eval |
| 2 | `apps/beta_queries/agent.yaml` — the runtime contract given to the model |
| 3 | `apps/beta_queries/README.md` — what runs today, how to run it |

## Built and tested (377 tests, no database needed)

| Module | Answers |
|---|---|
| `dialects.py` | how six engines differ: row cap, base-table test, comments, FKs, quoting |
| `sql/identifiers.py` | **what the model wrote → what the catalog holds → quoted for this engine** |
| `sql/guard.py` | G00–G12 over the AST — the security boundary |
| `sql/healing.py` | error → kind → repair strategy → a lesson that stops it recurring |
| `catalog/crawler.py` | metadata harvest; views recorded, never planned against |
| `catalog/graph.py` | **which tables**, and **how they join** — Neo4j + in-memory twin |
| `catalog/semantics.py` | which records count; which column is the right column |
| `routing/router.py` | which datasource, and whether to ask |
| `memory/profile.py` | what this user means, 7-day sliding TTL, email never stored |
| `nlp/` + `context/` + `dialogue/` | 30 conversational scenarios, one response shape each |
| `sync/plan.py` — and `catalog/readiness.py` | four crawl phases; answer, caveat or queue while a source is still syncing |
| `entitlements/resolver.py` | deny beats allow; `ent_hash` keys the cache; 60s snapshot |
| `agent/` (`contract` · `prompts` · `planner` · `providers`) | **one** model call; catalog text and chat history fenced as data; offline `EchoProvider` |
| `sql/compiler.py` | RLS predicates and masks injected into **every** SELECT scope |
| `sql/executor.py` | read-only, as the asker, bounded — and the source of every real engine error |
| `errors/report.py` | two layers, technical one redacted where it would leak an object |
| `orchestrator.py` | **the eleven stages — it answers a question end to end** |
| `eval/corpus.py` | 204 282 generated business questions · 44 hazards · 264-case gate |
| `airflow/dags/beta_queries_catalog_sync.py` | one config-driven DAG |

## It runs

```bash
pip install -e ".[beta_queries,dev]"
python scripts/beta_queries_demo.py
```

No Redis, no Neo4j, no model key. DuckDB is the engine, `DictKV` stands in for
Redis, `InMemoryGraph` for Neo4j, `EchoProvider` for the LLM. The fixture
schema is hostile on purpose — a column called `report id`, one called `user`,
a case-sensitive `Status`, a view that looks like the obvious answer, and a
staging twin of the real table. It answers, refuses and explains all of them.

## Not built

`app.py` + SSE (HTTP surface) · `incidents/` · `sync/targeted.py` ·
`remediation/worker.py` · `notify/` · `catalog/profiler.py` +
`catalog/describe.py` · `retrieval/` · the Monaco UI. Spec §19 has the map;
`DESIGN.md` carries the reasoning for each, which matters more than the code
for three of them:

| Piece | The one thing that must not be lost |
|---|---|
| `incidents/` | Key on **`(datasource, kind, object)`**, never on the healing signature — `signature()` strips quoted literals by design, so two different broken columns hash identically |
| `sync/targeted.py` | A read-only **probe**, never a re-crawl. `diff_catalog` always quarantines a one-table refresh (1 in 4,000), and `infer_joins` inverts its own safety check on a single-table datasource — it would invent exactly the joins it exists to suppress |
| `remediation/worker.py` | Ship it **last**. Snowflake, SQL Server and MySQL merge "you may not see it" into "it does not exist", so a permission denial classifies as `unknown_table`, auto-remediates as the *catalog* principal, resolves, and tells every waiter it is fixed — and every one of them fails again identically. Never auto-resolve a not-found on those three; never probe on `permission_denied`; never say "fixed" |

## The pipeline, in order

```
question
  -> dialogue/turn.handle_turn      classify · resolve follow-up · pick response shape
  -> catalog/readiness.decide       ready · wait · partial · queue · failed
  -> entitlements/resolver          three-layer enforcement, deny beats allow
  -> routing/router.route           which datasource
  -> catalog/graph.candidate_tables which tables (views excluded, staging demoted)
  -> catalog/graph.join_plan        how they join (declared > learned > inferred)
  -> agent/planner                  ONE model call -> QueryPlan
  -> sql/identifiers.rewrite        exact spelling, correct quoting     <-- do not skip
  -> sql/guard.check                read-only, entitled, capped
  -> sql/compiler                   RLS + masks, into every scope
  -> sql/executor                   as the asker, never the app account
  -> sql/healing.heal               on failure: classify, repair once, learn
  -> errors/report.build            two layers; technical one redacted if it leaks
```

`rewrite_identifiers` runs **before** the guard and **after** generation. That
ordering is the fix for the whole class of case/quoting failures.

## Rules that must not be relaxed

1. **Base tables only.** A view hides grain, filters and joins. `G06` refuses
   it by name; the crawl still records it so the catalog can explain why.
2. **Never invent a join.** No path ⇒ say so. Two equal paths ⇒ ask.
3. **Read-only, single SELECT**, enforced by permission, not by prompt.
4. **Every literal bound.** No string-concatenated SQL, ever.
5. **Dates never reach the model.** A calendar resolver is right every time.
6. **Catalog text and chat history are data, not instructions.**
7. **Identifiers come from the catalog**, never from the model's spelling.
8. **One model call** before execution; **one** repair attempt after a failure.
9. **PII is profiled for cardinality only.** A 400-row `email` column is
   low-cardinality and is still personal data.
10. **A clarification answered once is remembered** against that user.

## Definition of done for the next change

```bash
pip install -e ".[beta_queries,dev]"
pytest -q                                          # all green
ruff check packages/future_agents/ apps/ scripts/  # clean
ruff format --check packages/future_agents/ apps/ scripts/
python packages/guardrails/guardrails_engine.py . --mode block   # exits 0
python -c "from beta_queries.eval import corpus; print(sum(1 for _ in corpus.hazard_suite()))"
```

The 264-case hazard suite is the release gate. A case that should `clarify` and
instead `answer`s is a failure, not a near miss.

## Open, and blocking

- **GPT Luna contract** — structured output? embeddings? streaming? prefix caching?
- **Where entitlements live today** — Entra groups, an RBAC table, SQL Server roles?
  The resolver should be a thin adapter over what exists.
- **SQL Server version** — 2025/Azure gives native `VECTOR` + DiskANN; 2022
  pushes ANN to Redis.
- **Security review before phase 1.** This touches auth and PII. Two specifics:
  PII detection is name-based and will miss an unconventionally named column;
  and `agent.yaml` marks catalog text untrusted but **not the chat history**,
  so an instruction planted in turn 1 can ride into turn 5. A
  `conversation_is_data` constraint is drafted, not applied.
