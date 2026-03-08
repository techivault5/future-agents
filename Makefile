# ═══════════════════════════════════════════════════════════════
# IT Agents Guardrails — Makefile
# Works with Podman (default) or Docker (set ENGINE=docker)
#
#   make build          Build the container image
#   make check          Scan current directory for violations
#   make fix            Auto-fix folder structure
#   make test           Run test suite inside container
#   make help           Full command reference
# ═══════════════════════════════════════════════════════════════

# ── Configuration ──────────────────────────────────────────────
IMAGE        := it-agents-guardrails
TAG          := latest
ENGINE       := podman           # swap to 'docker' if needed
COMPOSE      := podman-compose   # swap to 'docker compose' if needed
WORKSPACE    ?= $(shell pwd)     # directory to scan; override: make check WORKSPACE=/my/project
PLATFORM_ENV ?= development

RUN_FLAGS := --rm \
             -v "$(WORKSPACE):/workspace:z" \
             -e PLATFORM_ENV=$(PLATFORM_ENV)

.DEFAULT_GOAL := help
.PHONY: build rebuild check fix block secrets packages scaffold search \
        agents test lint format shell serve package clean help

# ── Build ──────────────────────────────────────────────────────

## build: Build the container image
build:
	@echo "🔨 Building $(IMAGE):$(TAG) with $(ENGINE)..."
	$(ENGINE) build -t $(IMAGE):$(TAG) -f Containerfile .
	@echo "✅ Image ready: $(IMAGE):$(TAG)"

## rebuild: Force rebuild with no cache
rebuild:
	$(ENGINE) build --no-cache -t $(IMAGE):$(TAG) -f Containerfile .

# ── Guardrails commands ────────────────────────────────────────

## check: Scan WORKSPACE for guardrail violations (default: current dir)
check:
	@echo "🔍 Checking: $(WORKSPACE)"
	$(ENGINE) run $(RUN_FLAGS) $(IMAGE):$(TAG) check

## fix: Auto-fix folder structure issues in WORKSPACE
fix:
	@echo "🔧 Fixing: $(WORKSPACE)"
	$(ENGINE) run $(RUN_FLAGS) $(IMAGE):$(TAG) fix

## block: Exit 1 on any violation — use in CI/CD pipelines
block:
	$(ENGINE) run $(RUN_FLAGS) $(IMAGE):$(TAG) block

## secrets: Run secrets-only scan on WORKSPACE
secrets:
	$(ENGINE) run $(RUN_FLAGS) $(IMAGE):$(TAG) secrets

## packages: Run package policy scan only
packages:
	$(ENGINE) run $(RUN_FLAGS) $(IMAGE):$(TAG) packages

## serve: Watch mode — re-checks WORKSPACE every 30 seconds
serve:
	@echo "👀 Watching $(WORKSPACE) — Ctrl+C to stop"
	$(ENGINE) run $(RUN_FLAGS) --name it-agents-watch $(IMAGE):$(TAG) serve

# ── Scaffolding ────────────────────────────────────────────────

## scaffold: Scaffold a new project structure
##   Usage: make scaffold TYPE=python-service NAME=my-service
##          make scaffold TYPE=sqlserver-service NAME=my-db-app
##   Types: python-service | node-service | fullstack-app |
##          ml-project | data-pipeline | sqlserver-service |
##          infra-terraform | generic-project
TYPE ?= python-service
NAME ?= my-project
scaffold:
	$(ENGINE) run $(RUN_FLAGS) $(IMAGE):$(TAG) scaffold $(TYPE) $(NAME)

# ── Agents ─────────────────────────────────────────────────────

## agents: Generate / reindex all 10,000 IT agents
agents:
	$(ENGINE) run --rm $(IMAGE):$(TAG) agents

## search: Search agents by role keyword
##   Usage: make search TERM=backend
##          make search TERM="sql server"
TERM ?= backend
search:
	$(ENGINE) run --rm $(IMAGE):$(TAG) search "$(TERM)"

# ── Testing ────────────────────────────────────────────────────

## test: Run the full test suite inside the container
test:
	$(ENGINE) run --rm $(IMAGE):$(TAG) test

## test-v: Run tests with verbose output
test-v:
	$(ENGINE) run --rm $(IMAGE):$(TAG) test -v

## test-k: Run tests matching a keyword
##   Usage: make test-k K=sqlserver
K ?= ""
test-k:
	$(ENGINE) run --rm $(IMAGE):$(TAG) test -k "$(K)"

# ── Code quality (host-side) ───────────────────────────────────

## lint: Run ruff linter on the source
lint:
	$(ENGINE) run --rm -v "$(shell pwd):/app:z" $(IMAGE):$(TAG) \
	  /bin/bash -c "cd /app && python3 -m ruff check guardrails/ tests/ scripts/"

## format: Run ruff formatter (auto-fix style issues)
format:
	$(ENGINE) run --rm -v "$(shell pwd):/app:z" $(IMAGE):$(TAG) \
	  /bin/bash -c "cd /app && python3 -m ruff format guardrails/ tests/ scripts/"

# ── Packaging ──────────────────────────────────────────────────

## package: Build distributable ZIP of the full project
package:
	$(ENGINE) run --rm -v "$(shell pwd)/..:/output:z" $(IMAGE):$(TAG) package

# ── Dev shell ──────────────────────────────────────────────────

## shell: Interactive bash session inside the container
shell:
	$(ENGINE) run -it $(RUN_FLAGS) $(IMAGE):$(TAG) shell

# ── Compose shortcuts ──────────────────────────────────────────

## compose-up: Start all services with podman-compose
compose-up:
	$(COMPOSE) up

## compose-check: Run check via compose
compose-check:
	$(COMPOSE) run --rm guardrails check

## compose-test: Run tests via compose
compose-test:
	$(COMPOSE) run --rm test

## compose-ci: CI block mode via compose
compose-ci:
	$(COMPOSE) run --rm ci

# ── Cleanup ────────────────────────────────────────────────────

## clean: Remove the container image and cache volumes
clean:
	-$(ENGINE) rmi $(IMAGE):$(TAG) 2>/dev/null || true
	-$(ENGINE) volume rm future-agents_guardrails-cache 2>/dev/null || true
	@echo "✅ Cleaned up"

## clean-reports: Remove local guardrails report files
clean-reports:
	rm -f .guardrails-report.json .guardrails-human-log.jsonl .guardrails.sarif

# ── Help ───────────────────────────────────────────────────────

## help: Show this help message
help:
	@echo ""
	@echo "  🛡️  IT Agents Guardrails — Make Commands"
	@echo ""
	@grep -E '^## ' Makefile | sed 's/^## //' | \
	  awk -F: '{ printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 }'
	@echo ""
	@echo "  Variables:"
	@echo "    ENGINE=$(ENGINE)    — swap to 'docker' if needed"
	@echo "    WORKSPACE=$(WORKSPACE)"
	@echo "    TYPE=$(TYPE)   — project type for scaffold"
	@echo "    TERM=$(TERM)    — search term for agent search"
	@echo ""
	@echo "  Examples:"
	@echo "    make build"
	@echo "    make check WORKSPACE=/path/to/my-project"
	@echo "    make scaffold TYPE=node-service NAME=my-api"
	@echo "    make search TERM=\"sql server dba\""
	@echo "    make test"
	@echo "    make block                    # CI pipeline usage"
	@echo ""
