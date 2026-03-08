# IT Agents Guardrails — Podman Container Guide

Everything a developer needs to build, run, and hand off this system using **Podman** (rootless, daemonless). All commands also work with Docker — just swap `podman` → `docker`.

---

## Prerequisites

| Tool | Min version | Install |
|---|---|---|
| Podman | 4.x | `dnf install podman` / `brew install podman` |
| podman-compose _(optional)_ | 1.x | `pip install podman-compose` |
| make _(optional)_ | any | pre-installed on most systems |

> **No Docker daemon required.** Podman runs rootless and daemonless — no `sudo`, no background service.

---

## Quick Start (3 commands)

```bash
# 1. Build the image
podman build -t it-agents-guardrails -f Containerfile .

# 2. Scan your project for guardrail violations
podman run --rm -v /path/to/your/project:/workspace:z it-agents-guardrails check

# 3. Auto-fix folder structure issues
podman run --rm -v /path/to/your/project:/workspace:z it-agents-guardrails fix
```

---

## Using Make (Recommended)

The `Makefile` wraps all Podman commands. Run `make help` for the full list.

```bash
make build                              # Build the image
make check                              # Scan current directory
make check WORKSPACE=/my/project        # Scan a specific project
make fix   WORKSPACE=/my/project        # Auto-fix that project
make test                               # Run all 29 tests
make shell                              # Interactive bash inside container
```

---

## All Container Commands

| Command | What it does |
|---|---|
| `check [path]` | Scan for violations — secrets, packages, structure (default) |
| `fix [path]` | Auto-create missing required directories |
| `block [path]` | Like check but **exits 1** on any violation — use in CI/CD |
| `secrets [path]` | Secrets-only scan |
| `packages [path]` | Package version policy scan only |
| `scaffold <type> <name>` | Scaffold a new project from template |
| `search <keyword>` | Search 10,000 IT agent role definitions |
| `agents` | Generate / reindex all agents |
| `test [pytest args]` | Run test suite |
| `package` | Build a distributable ZIP of the whole system |
| `serve [path]` | Watch mode — re-scans every 30 seconds |
| `shell` | Drop into bash for manual exploration |
| `help` | Print all commands |

### Examples — raw Podman

```bash
IMAGE=it-agents-guardrails
WS=/path/to/your/project

# Check
podman run --rm -v "$WS:/workspace:z" $IMAGE check

# Fix folder structure
podman run --rm -v "$WS:/workspace:z" $IMAGE fix

# CI block mode (exits 1 on violation)
podman run --rm -v "$WS:/workspace:z" $IMAGE block

# Secrets scan only
podman run --rm -v "$WS:/workspace:z" $IMAGE secrets

# Scaffold a new Python service
podman run --rm -v "$WS:/workspace:z" $IMAGE scaffold python-service my-api

# Scaffold a SQL Server service
podman run --rm -v "$WS:/workspace:z" $IMAGE scaffold sqlserver-service my-db-app

# Search agents
podman run --rm $IMAGE search "backend engineer"
podman run --rm $IMAGE search "sql server dba"

# Run tests
podman run --rm $IMAGE test

# Run tests for a specific module
podman run --rm $IMAGE test -k sqlserver

# Interactive session
podman run -it --rm -v "$WS:/workspace:z" $IMAGE shell
```

---

## Using podman-compose

```bash
# Copy and configure environment
cp .env.example .env
# Edit .env — set WORKSPACE_PATH to your project directory

# Run guardrails check
podman-compose run --rm guardrails check

# Auto-fix
podman-compose run --rm guardrails fix

# CI block mode
podman-compose run --rm ci

# Run tests
podman-compose run --rm test

# Regenerate agent index
podman-compose run --rm agents
```

---

## Environment Variables

Set these in `.env` (copy from `.env.example`):

| Variable | Default | Description |
|---|---|---|
| `WORKSPACE_PATH` | `.` (current dir) | Host path to mount as `/workspace` |
| `GUARDRAILS_MODE` | `check` | Default mode: `check` \| `fix` \| `block` |
| `PLATFORM_ENV` | `development` | `development` \| `staging` \| `production` |
| `GUARDRAILS_SLACK_WEBHOOK` | _(empty)_ | Slack webhook for human escalation alerts |
| `GUARDRAILS_WEBHOOK_URL` | _(empty)_ | Generic webhook for escalation |

---

## Scaffold — Project Types

Use the `scaffold` command to create a properly-structured new project:

```bash
# Python microservice
podman run --rm -v /my/projects:/workspace:z it-agents-guardrails \
  scaffold python-service my-api

# Node/TypeScript REST API
podman run --rm -v /my/projects:/workspace:z it-agents-guardrails \
  scaffold node-service my-node-api

# SQL Server backed service
podman run --rm -v /my/projects:/workspace:z it-agents-guardrails \
  scaffold sqlserver-service my-db-service

# ML project
podman run --rm -v /my/projects:/workspace:z it-agents-guardrails \
  scaffold ml-project my-model

# Data pipeline (dbt / Airflow)
podman run --rm -v /my/projects:/workspace:z it-agents-guardrails \
  scaffold data-pipeline my-etl

# Terraform / IaC
podman run --rm -v /my/projects:/workspace:z it-agents-guardrails \
  scaffold infra-terraform my-infra

# Generic (no specific stack)
podman run --rm -v /my/projects:/workspace:z it-agents-guardrails \
  scaffold generic-project my-app
```

---

## CI/CD Integration

### GitHub Actions

```yaml
# .github/workflows/guardrails.yml
name: Guardrails

on: [push, pull_request]

jobs:
  guardrails:
    runs-on: ubuntu-latest
    container:
      image: it-agents-guardrails:latest
    steps:
      - uses: actions/checkout@v4
      - name: Run guardrails (block mode)
        run: |
          python3 /app/guardrails/guardrails_engine.py . --mode block
```

### GitLab CI

```yaml
# .gitlab-ci.yml
guardrails:
  image: it-agents-guardrails:latest
  script:
    - python3 /app/guardrails/guardrails_engine.py . --mode block
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

### Podman-in-Podman (self-hosted runners)

```bash
# Build once, push to your registry
podman build -t registry.mycompany.com/it-agents-guardrails:latest .
podman push registry.mycompany.com/it-agents-guardrails:latest
```

---

## Agent Search

The image contains all 10,000 IT role agent definitions. Search them:

```bash
# By role
podman run --rm it-agents-guardrails search "backend"
podman run --rm it-agents-guardrails search "devops"
podman run --rm it-agents-guardrails search "sql server dba"
podman run --rm it-agents-guardrails search "cloud architect"

# Load a specific agent by ID
podman run --rm it-agents-guardrails shell
# Then inside:
python3 -c "
import yaml
agent = yaml.safe_load(open('/app/agents/technical/backend-development/agent-00001.yaml'))
print(agent['name'], '|', agent['primary_stack'], '|', agent['guardrails_profile'])
"
```

---

## Handing Off to Another Developer

Give them this entire folder. They need:

1. **Podman installed** (or Docker)
2. **This folder** (with `Containerfile`, `Makefile`, `compose.yaml`, `.env.example`)
3. Run three commands:

```bash
cp .env.example .env            # configure workspace path
make build                      # build image
make check WORKSPACE=/their/project   # run first scan
```

That's it — no Python installation required, no pip installs, fully self-contained.

---

## Rootless Podman Notes

- The `:z` volume flag sets the correct SELinux label for rootless Podman on RHEL/Fedora
- The container runs as UID 1001 (`guardrails` user) — not root
- No `--privileged` or `--cap-add` flags needed
- Works in environments where Docker is not allowed

### Podman Machine (macOS / Windows)

```bash
# First-time setup
podman machine init
podman machine start

# Then use exactly the same commands as Linux
make build
make check
```

---

## Guardrails Profiles

Configured in `config/guardrails_config.yaml`:

| Profile | Secrets | Packages | Structure |
|---|---|---|---|
| `standard` | Block critical | Auto patch + minor | Warn |
| `strict` | Block all | Ask all changes | Error |
| `relaxed` | Warn only | Minimal checks | Warn |
| `architect` | Block all | Ask + rationale | Enforce all |

```bash
# Override profile at runtime
podman run --rm \
  -v /my/project:/workspace:z \
  -e GUARDRAILS_PROFILE=strict \
  it-agents-guardrails check
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `permission denied` on `/workspace` | Add `:z` to the volume flag: `-v path:/workspace:z` |
| `image not found` | Run `make build` first |
| `podman-compose not found` | `pip install podman-compose` |
| Tests fail on `agents_index.json` | Run `make agents` to regenerate the index |
| `WORKSPACE_PATH` not picked up | Check your `.env` file exists and is not empty |
| Container exits immediately | Run `make shell` and inspect manually |

---

## File Reference

```
future-agents/
├── Containerfile               ← Podman/Docker build definition (multi-stage)
├── compose.yaml                ← podman-compose / docker compose services
├── Makefile                    ← All commands wrapped for convenience
├── .env.example                ← Environment variable template (copy → .env)
├── scripts/
│   └── entrypoint.sh           ← Container startup — all commands live here
├── guardrails/
│   ├── guardrails_engine.py    ← Main scanner orchestrator
│   ├── secrets_scanner.py      ← Secret detection patterns
│   ├── package_manager.py      ← Package version policy
│   ├── folder_validator.py     ← Folder structure rules + scaffolding
│   └── human_input_handler.py  ← Human escalation flows
├── agents/                     ← 10,000 IT role definitions
├── config/
│   ├── guardrails_config.yaml  ← Runtime configuration
│   └── connective_config.yaml  ← Component wiring
├── skills/
│   └── combined_guardrails.yaml
└── templates/
    ├── project-structures/     ← Scaffold templates per project type
    └── ci/                     ← GitHub Actions / GitLab CI templates
```
