# Spec-Driven Delivery (SDD)

**Objective in → verified delivery out → lesson recorded.**

The system turns a human objective (a meeting line, a ticket, a chat message)
into a spec, a plan, a task DAG, executed work, a QA verdict and a delivery
record — pausing to ask the human when, and only when, an unknown would change
the outcome. Every artifact is data, every gate is executable, and the whole run
is one resumable JSON document.

Implementation: `packages/future_agents/sdd/`. Rulebook:
`data/config/spec_kit/spec-kit-enterprise.yaml`. CLI: `scripts/spec_kit.py`.
API: `/api/sdd/*`.

**The full reference is `docs/spec-driven-delivery-handbook.pdf`** — 59 pages
covering every stage, pattern and code path, generated from the source itself
(`python scripts/generate_handbook.py`). This page is the summary.

---

## 0 · Package layout

```
packages/future_agents/sdd/
  models.py          IR artifacts + run state (the only place artifacts are defined)
  config.py          spec-kit-enterprise.yaml loader
  constitution.py    executable gates
  personas.py        seniority profiles
  clarify.py         intent scoring, questions, meetings
  pipeline.py        the stage machine
  master.py          multi-repo orchestration
  memory_hub.py      case-based reasoning
  router.py          role/intent → engine
  stages/            pm · architect · planner · worker · qa · delivery · _extract
  repos/             languages (19 toolchains) · scaffold (required structure)
  knowledge/         index · conventions · placement  ← repo RAG
  handbook/          the generated PDF
```

Embedding it elsewhere is one import root and one object:

```python
from future_agents.sdd import DeliveryPipeline, RepoKnowledge, SpecKitConfig

RepoKnowledge.build("../any-repo")          # works on any language, any repo
DeliveryPipeline(SpecKitConfig.load(), repo_root="../any-repo")
```

## 1 · The pipeline

```
intake → clarify → spec → plan → tasks → work → qa → deliver → harvest
          ↑ ↓
       async questions / meeting
```

| Artifact | Module | Bounds the next stage by |
|---|---|---|
| `Objective` | `models.py` | raw intent + source + constraints |
| `ClarificationResult` | `clarify.py` | confidence, questions, assumptions, meeting |
| `Spec` | `stages.PMStage` | `REQ-nnn` + Given/When/Then `AC` ids |
| `Plan` | `stages.ArchitectStage` | components, risks, `spec_hash` |
| `TaskGraph` | `stages.TaskPlanner` | test-first DAG, `plan_hash` |
| `WorkResult[]` | `stages.WorkerStage` | per-task status and coverage claims |
| `QAReport` | `stages.QAStage` | behaviour checks, findings, verdict |
| `Delivery` | `stages.DeliveryStage` | accepted? + unconfirmed assumptions |
| `MemoryCase` | `memory_hub.py` | pitfalls that constrain the next plan |

Each stage is **deterministic without a model**. An engine (Claude, Copilot,
anything) only enriches free-text fields through `EngineRouter`; if it is absent,
slow, or fails, the pipeline still produces the same structure. That is what
makes runs reproducible, testable in CI, and cheap to dry-run.

---

## 2 · What changed from the original design

The draft architecture was sound in shape. These are the refinements that make
it survive contact with real work:

| # | Refinement | Why |
|---|---|---|
| 1 | **Clarification is a first-class stage**, not a PM-agent side effect | The dominant failure mode of agent pipelines is confidently building the wrong thing. Intent is *scored*, and low confidence stops the run. |
| 2 | **Escalation ladder**: auto-assume → async questions → meeting → blocked | A meeting is expensive. Only unknowns that survive an async round, or a genuinely tangled objective, earn one. |
| 3 | **Traceability IDs** (`REQ-001` → `REQ-001-AC-001` → `T-007`) | Coverage becomes computable instead of asserted. QA can name exactly which criterion is unverified. |
| 4 | **Assumption ledger** | Every unknown the pipeline resolved on its own is recorded and surfaced at delivery. Nothing is silently guessed. |
| 5 | **Content hashes on every artifact** | A plan drawn from a superseded spec is a *stale-plan* violation, not a silent inconsistency. |
| 6 | **Test-first DAG** — the implement task depends on its test task | Test parity is enforced by graph shape, not by hoping the worker writes tests. |
| 7 | **Failures weighted above successes in memory retrieval** | A case that records a pitfall changes the next plan; a success case rarely does. |
| 8 | **Executable constitution** | Rules are data with gate methods (`check_spec`, `check_plan`, `check_tasks`, `diff_gate`), with markdown *rendered from* them so prose cannot drift. |
| 9 | **QA scope fences are enforced in code** | The agent cannot fail a pipeline over load testing that was never in scope. |
| 10 | **Current model IDs** | The draft pinned `claude-3.5-sonnet` / `claude-3.5-haiku`. The rulebook now uses the Claude 5 family (`claude-opus-5`, `claude-sonnet-5`, `claude-haiku-4-5-20251001`) and routes by role and intent. |
| 11 | **Config rejects inline secrets at load time** | `${ENV_VAR}` or a secrets manager, enforced by the loader — not by review. |
| 12 | **Runs are resumable JSON** | A run can wait days for a meeting and resume in a different process. |

---

## 3 · The clarification gate

`IntentClarifier` runs a set of detectors over the objective and everything
attached to it. Each detector returns signals with a confidence cost:

| Detector | Fires on | Blocking |
|---|---|---|
| vague terms | "faster", "robust", "user-friendly", "TBD" | no |
| missing metric | change objectives with no baseline/target | yes |
| missing acceptance | no observable outcome stated | no (assumed) |
| missing data source | data/report work with no system of record | yes |
| missing integration target | integration work with no counterparty | yes |
| dangling reference | objective opens with "it"/"this" | yes |
| multi-objective | "and also", "as well as" | no |
| escalation trigger | auth, payments, PII, PHI, migrations | yes |
| open-ended | ends in "?" or fewer than six words | yes |

```
confidence = (1 − Σ signal weights) × structure_bonus
```

`structure_bonus` rewards well-formed intake (constraints, raw inputs, a
deadline). Then:

- `confidence ≥ ready_threshold` and no blocking unknowns → **spec now**
- `confidence < meeting_threshold` → **meeting** (too tangled for a form)
- blocking unknowns survive `max_rounds` async rounds → **meeting**
- otherwise → **async questions**

Low-risk unknowns with a sensible default become `Assumption` records instead of
questions (`auto_assume_low_risk`), and every one of them appears on the
delivery record as unconfirmed.

A meeting request arrives complete: title, reason, agenda (one line per open
question), attendees and duration. Closing it is one call — notes become
objective context, answers close the questions, and the run continues:

```python
state = pipeline.hold_meeting(state, notes, {question_id: answer})
```

---

## 4 · Memory hub (case-based reasoning)

Cases are markdown on disk (`docs/memory/cases/`) plus a JSON index —
reviewable, diffable, greppable. `MemoryHub.harvest(state)` compresses a
finished run into problem / solution / **pitfalls**, where pitfalls are mined
from the blocking questions that had to be asked, the meeting that was needed,
QA findings, and failed tasks.

Retrieval runs before `plan.md` is drafted; matched pitfalls are injected as
`Plan.historical_warnings` and as `Risk(source="memory")` — constraints on the
plan, not suggestions in a prompt.

---

## 5 · Engine routing

`EngineRouter` resolves **role → engine** from the rulebook, lets an **intent
keyword** override it, and falls back when an engine is unavailable. Engines are
`CallableEngine` (any function), `AnthropicEngine` (optional `ai` extra) or
`NullEngine` (default; deterministic). An engine exception degrades to empty
output and is recorded — a remote model never crashes a run.

```yaml
agents:
  roles:
    architect_agent: { engine: "claude-opus-5" }
    worker_agent:    { engine: "claude-sonnet-5", fallback: "claude-opus-5" }
  intent_routes:
    terraform: "claude-opus-5"
```

---

## 6 · CI/CD golden pattern

`Constitution.diff_gate(golden, proposed)` compares a proposed pipeline against
the approved template in `data/config/spec_kit/golden-microservice.yaml`. Removing
a topology line (`jobs:`, `needs:`, `runs-on:`, `uses:`, `steps:`, `strategy:`)
is a rewrite and is rejected; additive steps pass.

```bash
python scripts/spec_kit.py diff-gate --proposed .github/workflows/ci.yml
```

---

## 7 · QA protocol

- Every in-scope acceptance criterion becomes a `BehaviourCheck` with
  Given/When/Then **and** an Arrange-Act-Assert skeleton.
- A criterion is *verified* only when a test task covering it completed **and**
  the code tasks for it completed.
- Coverage is measured over MUST criteria; `required_coverage` (default 1.0)
  decides pass or fail.
- Out-of-scope fences (`qa.out_of_scope`) are dropped before checks are built —
  they can never become findings.
- Reporting is `summary_only`: a verdict line, verified behaviours, and the
  first blocker. Logs stay out of the channel unless asked for.

---

## 8 · Using it

```bash
# Intake a meeting transcript and drive it as far as it can go
python scripts/spec_kit.py run \
  --statement "Deliver a weekly churn report for sales" \
  --source meeting_transcript --by dana --input notes.txt

# It paused with questions? Answer them (or record the meeting)
python scripts/spec_kit.py answer --state .spec-kit/runs/run-x.json \
  --answer q-8f2a="Snowflake, refreshed nightly at 02:00"
python scripts/spec_kit.py meeting --state .spec-kit/runs/run-x.json \
  --notes-file meeting.md

python scripts/spec_kit.py cases --query "churn report"   # past pitfalls
python scripts/spec_kit.py constitution                   # governance as markdown
```

```python
from future_agents.sdd import DeliveryPipeline, Objective, SpecKitConfig

pipeline = DeliveryPipeline(SpecKitConfig.load())
state = pipeline.start(Objective(statement="…", submitted_by="dana"))
if state.awaiting_human:
    state = pipeline.answer(state, {q.id: "…" for q in state.pending_questions()})
```

HTTP (`uvicorn future_agents.api.main:app`):

| Route | Purpose |
|---|---|
| `POST /api/sdd/objectives` | intake (wire a meeting-notes webhook here) |
| `GET /api/sdd/runs/{id}/questions` | what the system needs from a human |
| `POST /api/sdd/runs/{id}/answers` | answer and resume |
| `POST /api/sdd/runs/{id}/meeting` | record a meeting and resume |
| `GET /api/sdd/cases` | search the memory hub |
| `GET /api/sdd/constitution` | governance rules (MCP resource) |
| `POST /api/sdd/cicd/diff-gate` | golden-pattern check |

---

## 9 · Wiring a real worker

The default `dry_run_backend` records what *would* happen. A real backend is one
function — shell out to a coding agent, open a PR, run the suite:

```python
def backend(task, spec):
    result = subprocess.run([...], capture_output=True, text=True)
    return WorkResult(
        task_id=task.id,
        status=TaskStatus.DONE if result.returncode == 0 else TaskStatus.FAILED,
        criterion_ids=task.criterion_ids,      # what this task claims to cover
        changed_files=[...],
        error=result.stderr[:500],
    )

DeliveryPipeline(config, backend=backend)
```

Coverage claims are what QA verifies against, so a backend must only claim a
criterion it actually exercised.

---

---

## 9a · Personas, languages, structure, and many repos

Four capabilities layered on the pipeline above. Full detail in the handbook
(chapters 7–9 and 14).

### Personas — working at 25 years of experience

`packages/future_agents/sdd/personas.py`. A persona changes behaviour, not tone:

| Effect | Mechanism |
|---|---|
| How hard intent is interrogated | `ready_threshold` / `meeting_threshold` |
| What coverage is acceptable | `qa.required_coverage` |
| Which reviews are mandatory | `gate_tasks()` appends REVIEW units to the DAG |
| Which design constraints apply | `risks_for()` appends plan risks |
| Which engine runs a role | `engine_overrides` |

Built in: `principal_hybrid` (default — AI/ML + full-stack, 25y),
`principal_ai_engineer`, `principal_fullstack`, `staff_platform`, `pragmatic`.
An unknown id falls back to the hybrid rather than raising.

```bash
python scripts/spec_kit.py personas
python scripts/spec_kit.py --persona principal_ai_engineer run --statement "…"
```

### Any language

`languages.py` holds 19 toolchains — Python, TypeScript, JavaScript, Go, Rust,
Java, Kotlin, C#, Ruby, PHP, Swift, C/C++, Scala, Elixir, Dart, R, SQL/dbt,
Terraform, Shell. Each carries install/test/lint/format/typecheck/build/audit
commands, the ecosystem's layout, its dependency-pinning policy, and a starter
manifest. Repos are **detected** from manifests and extensions (a manifest
outweighs 50 files), never assumed, and nothing in the pipeline hard-codes
`pytest`.

```bash
python scripts/spec_kit.py detect --path .
python scripts/spec_kit.py languages
```

### Repository structure

`scaffold.py` computes what a repo is missing and writes only that — idempotent,
dry-run by default, never creating a forbidden file (`.env`, key material,
state files). Universal surface: README, .gitignore, .env.example,
docs/architecture.md, docs/runbook.md, docs/adr/0001, a CI workflow built from
that language's own commands, plus the language manifest and its expected
layout. Monorepos keep `packages/`/`apps/` — the validator accepts conventional
roots instead of littering.

```bash
python scripts/spec_kit.py scaffold --path ../new-service --language go --write
```

When a pipeline is given `repo_root`, missing structure becomes an INFRA task in
the delivery rather than a lint failure three weeks later.

### Master orchestrator

`master.py` runs one objective across many repositories: profiles each, routes
by keyword/language (an explicit list always wins), orders them into dependency
waves, and — the part that matters to a human — **merges every repo's questions
into one set**, so one answer sheet or one meeting unblocks the whole program.
Each repo plans against its own toolchain and, optionally, its own persona.

```bash
python scripts/spec_kit.py program \
  --repo checkout-api=../checkout-api --repo web-app=../web-app \
  --depends web-app:checkout-api \
  --source meeting_transcript --input notes.txt \
  --statement "Add saved payment methods to checkout"
```

## 9b · Repository knowledge (RAG) — where a change may and may not go

`packages/future_agents/sdd/knowledge/`. Indexed once per pipeline (under a
second on a 600-file repo), then consulted by three stages.

| Source | Taken | Used for |
|---|---|---|
| Python files | docstring, classes, functions, methods (AST) | reuse, duplicate risk |
| Other code | symbols by per-language pattern | the same, in any language |
| Directories | kind, purpose, file count, bulk-data detection | target/test paths, fences |
| `AGENTS.md` / `CLAUDE.md` / `CONTRIBUTING.md` | "where does a new X go" tables, prohibitions | the decisive rules |
| Toolchain | ecosystem layout + test glob | fallback |

Retrieval is TF-IDF over paths, symbol names and docs with symmetric suffix
stripping (`invoices` finds `invoice_agent.py`). A "this already exists" claim
additionally requires **two query words in a path or symbol name** — prose
overlap alone matches almost anything, and a false duplicate warning teaches
people to ignore the real one. `RepoIndex.search` is the seam an embedding store
replaces.

Evidence is ranked: the repo's own written rule → the closest existing code →
the toolchain layout → the domain word in the requirement.

```bash
python scripts/spec_kit.py index --path . --query "churn report snowflake"
python scripts/spec_kit.py where --what "a new agent type that reviews pull requests"
```

```
  goes in   packages/future_agents/agents/…_agent.py   [new-module, confidence 0.9]
  because   the repo's own rule: 'A new agent type' → …/<name>_agent.py (AGENTS.md)
  tests     tests/test_agent_type_reviews.py

  read first:      packages/future_agents/agents/pdf_agent.py::PDFAgent.agent_type
  other approaches:
    - …/agents/pdf_agent.py [extend]     trade-off: grows an existing file
    - packages/…_type_reviews.py [new]   trade-off: one more file to discover
  must not go in:
    x <root>        Never put code at the repo root [AGENTS.md]
    x data/agents/  bulk data (10000 files across 53 directories) [repo scan]
```

What the pipeline does with it:

| Stage | Effect |
|---|---|
| PM | requirements echoing existing code become `spec.context_notes` |
| Architect | a `PlacementDecision` per requirement; `target_path` per component; fence violations and duplicates become plan risks |
| Planner | tasks carry real file paths; descriptions say where it goes, what to read first, what to avoid |
| Worker | the backend receives a task that already knows its target file |

Without `repo_root` the pipeline runs exactly as before — knowledge is additive,
never required.

---

## 10 · Limits (stated plainly)

- Requirement extraction is heuristic (modal verbs, imperatives, transcript
  attribution). It reads a well-run meeting well and a rambling one poorly —
  an engine on `pm_agent` improves the prose, not the IDs.
- Memory retrieval is keyword/Jaccard, not embeddings. Swap in a vector store
  behind `MemoryHub.retrieve` when the case count outgrows it.
- `dry_run_backend` does no work. Delivery is only as real as the backend wired
  behind it.
- API runs live in memory; use `save_state`/`load_state` for durability.
