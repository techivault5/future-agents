# Text-to-SQL — what is actually minimum necessary

Written after the full build went to a real laptop, against GPT Luna with real
Neo4j and Redis, and did not work. Two symptoms: the model appears to stop
responding, and the answers do not correspond to the question.

Both have causes I can name in this repository. Neither is the model, and
neither is Neo4j.

**The honest headline:** the two inputs that research says matter most —
**column values in the prompt** and **examples of queries that worked** — are
the two this build does not supply. The component built most heavily, the
schema graph, is the one ablations show contributes least on its own.

---

## 1. Symptom one — "the LLM stops responding"

It is not stopping. It is failing, and every kind of failure is being reported
with the same bland sentence.

`apps/beta_queries/agent/providers.py`:

```python
DEFAULT_TIMEOUT = 8.0
# The budget allows one call at ~900 ms. Anything slower has already lost, so
# fail fast and let the orchestrator degrade rather than blocking the turn.
DEFAULT_MAX_TOKENS = 1500
```

| Setting | Value | What it does to you |
|---|---|---|
| `DEFAULT_TIMEOUT` | **8 s** | a cold Luna call over a large card set exceeds this routinely |
| `DEFAULT_MAX_TOKENS` | **1500** | a long SQL plus an `answer_template` truncates mid-statement |
| transport | blocking `urllib.request.urlopen` | **no streaming** — all-or-nothing after 8 s, no partial output to watch |
| retry on transport failure | **none** | `MAX_REPAIRS` covers parse and validation failures only |

That comment is the mistake. An 8-second ceiling is a **latency policy**
written as if it were a correctness rule. It made sense for the p95 ≤ 2 s
target; it is wrong for a laptop making a cold call to an internal endpoint.

The failure path collapses everything into one message:

```
providers.complete()  ──timeout/502/truncation──▶  exception
planner.plan_query()  ──▶  result.errors.append("model call failed: …")
orchestrator          ──▶  not result.ok  ──▶  scenario "ambiguous_intent"
```

So a timeout, a truncated JSON body, an auth rejection and a genuinely
ambiguous question all produce **the same reply**. From the chat it reads as
"it stopped."

### What to change first — five lines, before rebuilding anything

1. `DEFAULT_TIMEOUT` → **45.0**. Measure the real p95 before tightening.
2. `DEFAULT_MAX_TOKENS` → **4000**. Truncation is silent and expensive.
3. **Retry once on transport failure**, with a short backoff. Today only
   parse failures retry, which is exactly backwards: a parse failure is the
   model's fault and unlikely to differ on retry; a timeout is not.
4. **Stop collapsing to `ambiguous_intent`.** Carry the reason through:
   *"the model took longer than 45 s"* and *"the model's reply was cut off at
   1500 tokens"* are different problems with different fixes, and the user
   needs to see which.
5. **Log the prompt, the raw completion, `stop_reason` and `ms`** for every
   call. Without this you are guessing, which is where you are now.

Also check one thing about Luna specifically: the client sends
`response_format: {"type": "json_schema", …}` when a schema is passed. If Luna
does not support that field it may ignore it — or reject the request. Confirm
it honours strict JSON schema, and if not, drop to plain JSON mode and rely on
the repair pass.

---

## 2. Symptom two — "the answer doesn't correlate with my question"

This is not a model quality problem either. The prompt is starved, and the
routing inputs are probably empty.

### The prompt has no data in it

`orchestrator._cards()` builds every schema card like this:

```python
SchemaCard(
    fqn=fqn,
    columns=prune_columns(columns, question),
    description=" ".join(sorted(node.terms))[:160],
    default_filters=source.default_filters.get(fqn, []),
)
```

`SchemaCard` declares a `sample_values` field, and `render()` already emits
`e.g. …` hints for it:

```python
values = self.sample_values.get(name)
hint = f"  e.g. {', '.join(values[:4])}" if values else ""
```

**Nothing ever populates it.** The plumbing exists and is empty. The model sees
column names and types, and no idea what is in them.

And `description` is not a description — it is `" ".join(sorted(node.terms))`,
a bag of alphabetised tokens. The modules that would write real prose,
`catalog/profiler.py` and `catalog/describe.py`, are specified and not built.

This matters more than anything else in the design. On BIRD, switching from
sample column values to **distinct** sample column values moved schema-linking
accuracy from **86.67% to 90.60%**
([Rethinking Schema Linking](https://arxiv.org/pdf/2510.14296)). Systems at
human-level accuracy add, per column, either a description **or three value
examples** ([ReViSQL](https://arxiv.org/html/2603.20004v1)). BIRD's entire
emphasis over older benchmarks is database *content*, not schema shape.

A model that cannot see that `status` holds `ACTIVE`/`TERMINATED`, or that
`region` holds `EMEA`/`APAC`, will guess — and its guesses will not correlate
with your question.

### Routing is scoring on inputs that may be empty

`routing/router.py::score_source()` is where "which database" is decided:

| Signal | Weight | Where it comes from |
|---|---|---|
| a question word is a **known value** | **+40** | `profile.value_index`, built at crawl time by `profile_values` |
| **synonyms** expand the question's words | enables the rest | hand-written in `beta_queries_sources.yaml` |
| the question names a **table** | ~+20 | table names, tokenised |

Both of the strong signals are things **you have to supply**. If the crawl ran
without value profiling, and `synonyms` is still the example file's HR
vocabulary rather than yours, routing falls back to token overlap against
physical table names. Against real warehouse names — `DW_FACT_EMPL_ASSG_CURR`,
`T_HR_EMP_M` — token overlap finds nothing. You get "nothing covers that", or
a confident route to the wrong source.

### The examples channel is not connected

The spec calls certified past queries *"the highest-leverage quality input in
the whole system"* — `query_memory` rows with `is_certified = 1`, fed in as
few-shot. `agent/prompts.py::build_user()` has parameters for cards, joins,
dates, context, profile hints, healing guidance and unreachable tables. It has
**no parameter for examples**. Nothing learns from a query that worked.

---

## 3. What the research says is minimum

The uncomfortable part, stated plainly because it contradicts where the effort
went in this build.

**Schema linking is not the lever you think it is.** An ablation across two
model families found that *despite 96.5% gold-table recall, the embedding
linker did not significantly beat no linking at all*
([on-prem BIRD frontier](https://arxiv.org/html/2606.29733)). Getting the right
tables into the prompt is necessary and nowhere near sufficient.

**Values are the lever.** See §2 — the largest single measured gain in this
list comes from putting distinct column values in the prompt.

**Execution feedback is the second lever.** Self-correction on the real
database error roughly doubles per-query latency for a large accuracy gain
([DIN-SQL](https://openreview.net/pdf?id=p53QDxSIc5)) — the best
accuracy-per-unit-complexity trade available.

**A graph is fine, and cheap.** A zero-shot pathfinder over the schema graph
reaches state-of-the-art linking with **one lightweight LLM call and no
training** ([SchemaGraphSQL](https://arxiv.org/pdf/2505.18363)). Neo4j is not
your problem. It is also not your win.

### The six things that must exist, and nothing else

| # | Component | Why it is not optional |
|---|---|---|
| 1 | **Schema card with distinct values** — per column: name, type, 3 distinct example values, and a one-line description where one exists | the measured lever; without it the model is guessing at content |
| 2 | **One model call** producing SQL + parameters as JSON | everything else is scaffolding around this |
| 3 | **Bound parameters** — never string interpolation | correctness and injection, both |
| 4 | **A read-only AST check** — single SELECT, known tables, row cap | the only honest enforcement; a prompt is not a control |
| 5 | **Execute, and catch the engine error** | the input to #6, and the only ground truth |
| 6 | **Repair once on the real error, then stop** | the second lever; a second repair costs double for near-nothing |

That is the whole minimum. Everything else in what I gave you is an
optimisation on top of these six, and optimisations on top of a broken
foundation are what you have been debugging.

---

## 4. What to keep, and what to put down

From the existing build, judged on whether it earns its complexity **today**:

### Keep — these solve real problems you will hit immediately

| Module | Why |
|---|---|
| `sql/identifiers.py` | `report id` vs `report_id`. On a case-insensitive engine this binds to the wrong column and returns a confident wrong number. No prompt fixes it |
| `sql/guard.py` | minimum #4, already written and tested |
| `dialects.py` | six engines really do differ; `:p0` is the only placeholder that parses on all of them |
| `sql/executor.py` | minimum #5 |
| `sql/healing.py` | minimum #6 |

### Put down for now — right ideas, wrong time

| Module | Why it can wait |
|---|---|
| `entitlements/` | necessary before production, irrelevant to "does it answer correctly" |
| `catalog/graph.py` traversal | ablations say it is not where accuracy comes from. A flat list of candidate tables plus FK edges is enough to start |
| `catalog/readiness.py` | solves a problem you do not have until you have many datasources |
| the 204k-case corpus | a generated eval is worth having **after** something passes a hand-written twenty |
| two-layer errors, incidents, notifications | presentation and operations, downstream of correctness |
| the 30-scenario conversation layer | keep the classifier; the rest is polish |

**The rule:** anything that does not change whether the SQL is right is not
minimum. Most of what I built you is in that category.

---

## 5. Configuration, sync and words — the chain to check

You asked specifically about this, and it is where I would look first, because
this is the part that is *yours* to fill in and probably is not filled in.

### The chain, end to end

```
beta_queries_sources.yaml          ← you write: synonyms, description, subject_areas
        │
        ▼
scripts/beta_queries_crawl.py      ← reads metadata AND samples values
        │                            (value profiling must be ON)
        ▼
build_source_profile()             ← collapses into what the router scores:
        │                            table_terms, column_terms, value_index, synonyms
        ▼
route()  +40 per value hit         ← "india" → hrdb.employee.country_name
        │
        ▼
candidate_tables()                 ← which tables
        │
        ▼
_cards()                           ← what the model actually sees   ← THE GAP
```

### What to verify, in order

| # | Check | If it is empty |
|---|---|---|
| 1 | `value_index` is non-empty for each source | the +40 signal is dead; routing is name-matching only |
| 2 | `synonyms` maps **your** business words to **your** table words | "how many people" scores zero against `employee` |
| 3 | `profile_values: true` and `max_distinct` is high enough for your columns | values were never sampled |
| 4 | schema cards carry values | the model is blind to content — **currently always true** |
| 5 | `description` per source is real prose | routing has no tiebreak |

The settings that control #3 live in `beta_queries_sources.yaml` under
`defaults`: `profile_values`, `max_distinct` (columns with more distinct values
than this are not indexed), `sample_limit` (values kept per column),
`max_value_len`.

**`max_distinct: 200` is the one to look at.** A `country_name` column with
more than 200 distinct values is skipped entirely — so "India" never enters the
value index, and the question that names it routes on nothing.

### The single highest-value configuration change

`synonyms` is not decoration. It is the map from the words your users type to
the words your catalog holds, and the example file ships with HR vocabulary
that is almost certainly not yours. Write thirty entries for your actual
domain before touching anything else. It is an afternoon, and it will move more
than a week of graph tuning.

---

## 6. The diagnostic to run before changing anything

You are debugging blind. For one real question, print:

| Print | Tells you |
|---|---|
| routed source + **score** + the reason | whether routing worked, or guessed |
| candidate tables + **scores** | whether the right tables were even considered |
| the **rendered schema cards, verbatim** | whether values and descriptions are present — they are not |
| the **full prompt** | what the model actually got, rather than what you think it got |
| the **raw completion**, `stop_reason`, `ms`, token counts | symptom 1, instantly: `max_tokens` means truncation, a timeout means the 8 s ceiling |

That single dump separates symptom 1 from symptom 2 at a glance, and tells you
which of §5's five checks is failing. Everything in this document after §1 is
an educated reading of the code; that dump is evidence.

---

## 7. Rebuild order

Each step has a check. Do not move on until it passes.

| # | Build | Done when |
|---|---|---|
| 1 | The diagnostic in §6 | you can see the prompt for a real question |
| 2 | Values into the schema cards — 3 distinct per column | the rendered card shows `e.g. ACTIVE, TERMINATED` |
| 3 | The five provider fixes in §1 | no turn ever fails with a bare "ambiguous" again |
| 4 | Twenty hand-written questions from your users, with expected SQL | you have a number to move |
| 5 | Repair-once on the engine error | the number goes up |
| 6 | `synonyms` for your domain | routing accuracy on those twenty |
| 7 | Certified examples as few-shot | the number goes up again |

Note what is **not** in that list: the graph, entitlements, readiness,
incidents, notifications, the generated corpus. Add them when a measured number
says you need them.

---

## 8. Scorecard on what I gave you

| Verdict | Components |
|---|---|
| **Earns its place** | identifiers · guard · dialects · executor · healing |
| **Premature** | entitlements · readiness · incidents · the 204k corpus · two-layer errors |
| **Plumbed but empty** — worst category, looks done and does nothing | `SchemaCard.sample_values` · table descriptions · the certified-examples channel |
| **Correct but not the bottleneck** | the Neo4j graph and join pathfinding |

The third row is the one that cost you. A field that exists, renders, and is
never filled reads as finished in every review — and it is the field the
research says matters most.

---

## Sources

- [How Far Do On-Prem Open LLMs Get on Text-to-SQL?](https://arxiv.org/html/2606.29733) — the schema-linking ablation
- [Rethinking Schema Linking: Context-Aware Bidirectional Retrieval](https://arxiv.org/pdf/2510.14296) — distinct values, 86.67% → 90.60%
- [ReViSQL: Achieving Human-Level Text-to-SQL](https://arxiv.org/html/2603.20004v1) — description or three value examples per column
- [DIN-SQL](https://openreview.net/pdf?id=p53QDxSIc5) — decomposition and self-correction
- [SchemaGraphSQL](https://arxiv.org/pdf/2505.18363) — zero-shot graph pathfinding, one LLM call
- [Understanding the Effects of Noise in BIRD-Bench](https://arxiv.org/pdf/2402.12243) — how much benchmark error is question ambiguity
- [Agentar-Scale-SQL](https://arxiv.org/html/2509.24403v1) — test-time scaling, for when the basics are done
