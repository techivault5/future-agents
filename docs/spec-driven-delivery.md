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

---

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

## 10 · Limits (stated plainly)

- Requirement extraction is heuristic (modal verbs, imperatives, transcript
  attribution). It reads a well-run meeting well and a rambling one poorly —
  an engine on `pm_agent` improves the prose, not the IDs.
- Memory retrieval is keyword/Jaccard, not embeddings. Swap in a vector store
  behind `MemoryHub.retrieve` when the case count outgrows it.
- `dry_run_backend` does no work. Delivery is only as real as the backend wired
  behind it.
- API runs live in memory; use `save_state`/`load_state` for durability.
