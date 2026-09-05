# AGENTS.md — how to work in this repo

Instructions for coding agents (and humans) working in this monorepo: **what
lives where, where new things go, and what must hold before you commit.**

`CLAUDE.md` holds the coding rules (style, guardrails, security). This file
holds the *map*. Read both.

---

## 1 · Layout — Turborepo-style

```
apps/                    deployable things that run
  finance_advisor/         dashboard + alerts + memory SDKs
packages/                shared libraries other things import
  future_agents/           the agent framework (core, agents, patterns, workers)
  guardrails/              secrets / package / structure enforcement engine
  scanning/                web scraper + Snowflake knowledge store
  token_saver.py           standalone module
  mcp_server.py            standalone module
data/                    assets, not code
  agents/                  10,000 role definitions (YAML) + index
  config/                  runtime config
  skills/                  skill definitions
docs/                    all prose: guides, architecture, leadership_guides/
web/                     browser assets (static/)
scripts/                 CLI + GitHub Actions entrypoints
templates/               project scaffolding templates
examples/                runnable demos
tests/                   the whole pytest suite
```

**Directory names use underscores, not hyphens.** Turborepo convention prefers
`finance-advisor`; Python cannot import that. Importability wins.

### How imports resolve

`packages/` and `apps/` are both import roots, so imports carry **no path
prefix**:

```python
from future_agents.core.events import EventBus     # packages/future_agents/…
from guardrails.secrets_scanner import SecretsScanner
from finance_advisor.memory import FinanceMemorySDK  # apps/finance_advisor/…
```

Wired in `pyproject.toml` — `packages.find.where = ["packages", "apps"]` for
installs, `pytest.pythonpath = ["packages", "apps", "."]` for tests. If you add
a new top-level package or app, add it to `include` there or it will not install.

### Where turbo actually applies

`turbo.json` + `package.json` workspaces orchestrate the **JavaScript** members
only — today that is the VS Code extension, alongside the browser SDK it loads.
Python work runs through pytest/ruff/make, not turbo. Do not add Python
directories to `workspaces`; npm cannot build them and it will only mislead.

---

## 2 · Where do I put a new thing?

| You are adding | It goes in | Also do |
|---|---|---|
| A new agent type | `packages/future_agents/agents/<name>_agent.py` | Subclass `BaseAgent`; register in `AgentRegistry`; add tests |
| An agentic pattern | `packages/future_agents/patterns/` | Export from the package `__init__` |
| A spec-driven delivery stage or gate | `packages/future_agents/sdd/` | Stages stay deterministic without an LLM; an engine may only enrich free text. Rules go in `data/config/spec_kit/spec-kit-enterprise.yaml`, never inline |
| Support for another language | one `Toolchain` entry in `packages/future_agents/sdd/repos/languages.py` | Nothing else changes — detection, scaffolding, CI and task commands all read from it |
| A repo-knowledge rule or detector | `packages/future_agents/sdd/knowledge/` | Placement must cite its evidence; a false "this already exists" is worse than none |
| A memory tier, retrieval rule or lesson policy | `packages/future_agents/sdd/memory/` | Everything written is sanitised first, everything remembered decays, and a blocking question is re-asked however well remembered |
| A ticket source (Jira, ServiceNow, …) | `packages/future_agents/sdd/intake/adapters.py` | Take the payload, never fetch it; carry an `ExternalRef`; sanitise the text |
| A worker agent or skill | `data/config/spec_kit/workforce.yaml` + `workforce.bind(...)` | Specs are data, handlers are code. A skill must return `Evidence` that says what actually ran |
| A seniority profile | `packages/future_agents/sdd/personas.py` | A persona must change behaviour (thresholds, gates, risks), not tone |
| A scheduled worker | `packages/future_agents/workers/` + entrypoint in `scripts/workers/` | Entrypoints must not import the framework — GitHub Actions runs them bare |
| A guardrail rule | `packages/guardrails/` | Add a case to `tests/test_guardrails.py` |
| A user-facing application | `apps/<app_name>/` | Own README; add to `include` in `pyproject.toml` |
| A finance skill | `apps/finance_advisor/memory/skills.py` | Register in `SKILLS`; mirror the maths in the JS SDK if it should work client-side |
| A tool the chat agent can call | `apps/finance_advisor/agent/tools.py` | Add to `build_toolset`; it must be read-only or local — no orders, no mail, no writes off-box |
| A planner input or what-if lever | `apps/finance_advisor/planner/` | A field must change an output, or don't collect it; a what-if must run through `simulate()` so both sides are built the same way |
| An LLM provider | `apps/finance_advisor/agent/providers.py` | Take the key as a call argument; never store, log or return it |
| Role/agent definition data | `data/agents/…` | Regenerate `agents_index.json` |
| A guide or doc | `docs/` | Never at the repo root — root keeps only README and CLAUDE.md |
| An architecture diagram | `packages/future_agents/sdd/handbook/figures.py` | Diagrams are code, not binaries: `--diagrams` regenerates `docs/diagrams/` and the PDF from the same source |
| A browser asset | `web/static/` | — |
| A one-off script | `scripts/` | Keep it runnable with no framework import if CI calls it |

**Never put code at the repo root.** Root is for manifests
(`pyproject.toml`, `package.json`, `turbo.json`, `Containerfile`, `Makefile`)
and the two instruction files.

---

## 3 · Before you commit

Run what CI runs — these are the same commands, in the same scope:

```bash
pytest -q                                              # 1655 tests, all must pass
ruff check packages/future_agents/ apps/ scripts/
ruff format --check packages/future_agents/ apps/ scripts/
python packages/guardrails/guardrails_engine.py . --mode block   # must exit 0
```

Or install the hooks once and let them run for you:
`pip install pre-commit && pre-commit install`.

### Scope notes that will otherwise surprise you

- CI lints `packages/future_agents/`, `apps/` and `scripts/` — **not**
  `packages/scanning/` or `packages/guardrails/`, which carry pre-existing
  violations. Do not widen the scope in a PR that is about something else; you
  will inherit unrelated failures.
- CI runs on the **merge commit** with `main`, so a lint error can appear in a
  PR that neither branch has alone. If CI fails and local passes, merge `main`
  first and re-check.
- `ruff` is minor-pinned (`~=0.16.0`) so CI and your machine format identically.
  If your local ruff disagrees with CI, check `ruff --version` first — a stale
  binary earlier on `PATH` will shadow the installed one. Note that ruff also
  formats Python code blocks **inside Markdown**, so READMEs are in scope.
- The guardrails engine detects this repo as a `python-service` and enforces
  that profile's required files. It accepts `Containerfile` as a `Dockerfile`
  equivalent (Podman-first repo).

---

## 4 · Rules that are not negotiable

These are enforced by the guardrails engine and by review:

1. **No secrets in code.** `os.environ[...]` or a secrets manager. `.env` is
   never committed; `.env.example` always is, with `REPLACE_ME` placeholders.
2. **No exact version pins** without written justification — `~=` for Python,
   `^` for npm.
3. **Financial and advisory output is educational only.** Every skill result
   carries the not-advice disclaimer; nothing recommends a specific security or
   promises a return. Do not remove those disclaimers.
4. **Personal data stays local.** The finance memory store is gitignored;
   `sensitive` records redact by default in recall, exports, logs and prompts.
   Never add telemetry or an outbound call that carries user financial context.
   The chat agent is bring-your-own-key: a user's key is a request-scoped
   argument, never a stored field, a log line or a response body.
5. **Escalate to a human** for: major version upgrades, new production
   environment variables, irreversible migrations, anything touching auth,
   payments, PII or PHI, and deleting files or branches.

---

## 5 · Working agreements for agents

- **Verify, don't assume.** Run the suite and, for anything with a runtime
  surface, actually drive it (start the app, hit the endpoint, screenshot the
  page). "Tests pass" is not the same as "it works".
- **Report honestly.** If something is skipped, blocked or partially done, say
  so plainly, with the output. A green summary over a red run is worse than
  useless.
- **Keep PRs about one thing.** A restructure and a feature in one PR cannot be
  reviewed properly.
- **Match the surrounding code** — comment density, naming, idiom. Do not
  restate what code does in comments; explain only non-obvious *why*.
- **Pre-existing failures are not yours to silently adopt or hide.** Fix them
  deliberately in their own change, or leave them and say they exist.
- **Data-driven over duplicated prose.** Comparison tables, matrices and
  catalogs live as data (e.g. `RUNTIME_MATRIX`, `skill_catalog()`) so docs, API
  and UI cannot drift apart.

---

## 6 · Fast orientation

```bash
make help                      # available targets
pytest -q tests/test_finance_memory.py    # a fast, representative suite
uvicorn finance_advisor.app:app --port 8600
#   http://localhost:8600                 dashboard
#   http://localhost:8600/sdk/js/demo.html  browser SDK demo
python -c "from finance_advisor.memory import FinanceMemorySDK as S; print(S.capabilities())"
```

Splitting a component into its own repository: see `docs/REPO-SPLIT.md`.
