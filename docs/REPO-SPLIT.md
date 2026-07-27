# Splitting this monorepo into standalone repositories

The content-type restructure (`src/`, `data/`, `docs/`, `web/`) makes three
components cleanly separable. This is the runbook for actually extracting them,
**with history preserved**.

> The session that wrote this could not create the repositories: the GitHub App
> is scoped to `techivault5/future-agents` and `POST /user/repos` returns
> `403 Resource not accessible by integration`. Create the empty private repos
> yourself (or grant repo-creation scope), then run the commands below.

## Readiness at a glance

| Candidate | Contents | Standalone today? | Size |
|---|---|---|---|
| `it-agents-guardrails` | `packages/guardrails/`, config, templates, its tests + guides | ✅ Yes — only needs `pyyaml`, `packaging` | ~250 KB |
| `agent-definitions` | `data/agents/` (10,000 role YAMLs + index) | ✅ Yes — pure data, no code | ~42 MB |
| `finance-advisor` | `apps/finance_advisor/` + its tests | ⚠️ No — see below | ~700 KB |

### Why `finance-advisor` is not standalone yet

It imports four modules from the framework:

```
future_agents.definitions.loader          future_agents.definitions.schema
future_agents.infrastructure.knowledge_store   future_agents.models.knowledge
```

Pick one before extracting:

1. **Depend on the framework** (least work): publish `future-agents` to an index
   or install from git, and add it to the new repo's dependencies.
2. **Vendor the four modules** into `finance_advisor/_framework/` — they are
   small and dependency-light. Cleanest separation; you own the copies.
3. **Extract a fifth repo**, `future-agents-core`, holding just those modules,
   and depend on it from both. Best if other projects grow the same need.

The memory framework and both SDKs (`memory/`, `memory/sdk/js`,
`memory/sdk/vscode`) have **no framework imports** — they are already standalone
and could ship as their own package under any of these options.

## Extraction commands

Uses [`git-filter-repo`](https://github.com/newren/git-filter-repo)
(`pip install git-filter-repo`). Each block runs on a throwaway clone, so the
monorepo is never modified.

### 1 · it-agents-guardrails

```bash
git clone https://github.com/techivault5/future-agents.git /tmp/split-guardrails
cd /tmp/split-guardrails
git filter-repo \
  --path packages/guardrails/ \
  --path data/config/guardrails_config.yaml \
  --path templates/project-structures/ \
  --path tests/test_guardrails.py \
  --path docs/IT-AGENTS-GUARDRAILS.md \
  --path docs/VIBE-CODER-GUIDE.md \
  --path-rename packages/guardrails/:guardrails/ \
  --path-rename data/config/:config/ \
  --path-rename docs/:docs/
git remote add origin https://github.com/techivault5/it-agents-guardrails.git
git push -u origin main
```

Then add a `pyproject.toml` declaring `pyyaml~=6.0` and `packaging~=24.0`, and a
console entry point for `guardrails_engine.py`.

### 2 · agent-definitions

```bash
git clone https://github.com/techivault5/future-agents.git /tmp/split-agents
cd /tmp/split-agents
git filter-repo --path data/agents/ --path-rename data/agents/:agents/
git remote add origin https://github.com/techivault5/agent-definitions.git
git push -u origin main
```

42 MB of YAML. Consider whether it wants Git LFS, or whether a release artifact
(the ZIP `scripts/package_zip.py` already builds) serves consumers better than a
clone.

### 3 · finance-advisor

Resolve the dependency question above first, then:

```bash
git clone https://github.com/techivault5/future-agents.git /tmp/split-finance
cd /tmp/split-finance
git filter-repo \
  --path apps/finance_advisor/ \
  --path tests/test_finance_advisor.py \
  --path tests/test_finance_memory.py \
  --path-rename apps/finance_advisor/:finance_advisor/
git remote add origin https://github.com/techivault5/finance-advisor.git
git push -u origin main
```

Then fix imports (`finance_advisor.` → `finance_advisor.`), add a
`pyproject.toml` with `pydantic>=2`, optional `[api]` and `[localnlp]` extras,
and copy `.github/workflows/finance-alerts.yml`.

## After each split

1. Leave a pointer in this repo (a stub README where the code was) so the
   monorepo does not silently keep a stale copy.
2. Decide the direction of truth — a component should live in exactly one place.
   Two copies drift within weeks.
3. Move the matching CI workflow across; the monorepo's jobs will no longer
   cover extracted code.
4. Re-run the guardrails engine in the new repo: each split repo is a
   `python-service` by the same standard and will want its own `src/` layout,
   `.env.example`, `.pre-commit-config.yaml` and `docs/`.

## What should *not* be split

`future_agents/` (framework), `scanning/`, `scripts/`, `examples/` and `tests/`
are tightly coupled to each other and to the framework's event bus, registry and
orchestrator. Splitting those buys nothing today and costs a versioning
boundary on every change.
