#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# IT Agents Guardrails — Container Entrypoint
#
# Usage:  podman run ... it-agents-guardrails <COMMAND> [args]
#
# Commands:
#   check   [path]   — Scan for violations (default)
#   fix     [path]   — Auto-fix folder structure issues
#   block   [path]   — Scan + exit 1 on any violation (CI mode)
#   test             — Run the test suite
#   agents           — Generate / reindex all 10,000 agents
#   search  <term>   — Search agents by role keyword
#   serve            — Run continuous watch mode (re-checks on change)
#   shell            — Drop to bash for manual exploration
#   help             — Print this message
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

APP=/app
WORKSPACE="${WORKSPACE:-/workspace}"
CMD="${1:-check}"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
BOLD='\033[1m'
RESET='\033[0m'

banner() {
  echo -e "${BOLD}"
  echo "═══════════════════════════════════════════════════════════"
  echo "  🛡️  IT Agents Guardrails"
  echo "  Command : $CMD"
  echo "  Workspace: $WORKSPACE"
  echo "═══════════════════════════════════════════════════════════"
  echo -e "${RESET}"
}

run_guardrails() {
  local mode="$1"
  local target="${2:-$WORKSPACE}"
  python3 "$APP/guardrails/guardrails_engine.py" "$target" --mode "$mode"
}

case "$CMD" in

  # ── check ──────────────────────────────────────────────────────
  check)
    banner
    TARGET="${2:-$WORKSPACE}"
    echo -e "${BLUE}Scanning: $TARGET${RESET}"
    echo ""
    run_guardrails check "$TARGET"
    EXIT=$?
    echo ""
    if [ $EXIT -eq 0 ]; then
      echo -e "${GREEN}✅ All checks passed${RESET}"
    else
      echo -e "${YELLOW}⚠️  Issues found — see report above${RESET}"
      echo -e "   Run 'fix' mode to auto-fix structure issues."
    fi
    exit $EXIT
    ;;

  # ── fix ────────────────────────────────────────────────────────
  fix)
    banner
    TARGET="${2:-$WORKSPACE}"
    echo -e "${BLUE}Auto-fixing: $TARGET${RESET}"
    echo ""
    run_guardrails fix "$TARGET"
    echo ""
    echo -e "${GREEN}✅ Fix pass complete${RESET}"
    ;;

  # ── block (CI mode) ────────────────────────────────────────────
  block)
    banner
    TARGET="${2:-$WORKSPACE}"
    echo -e "${BLUE}CI block mode — scanning: $TARGET${RESET}"
    echo ""
    run_guardrails block "$TARGET"
    EXIT=$?
    if [ $EXIT -ne 0 ]; then
      echo -e "${RED}❌ Violations found — blocking commit/deploy${RESET}"
      exit 1
    fi
    echo -e "${GREEN}✅ No violations — safe to proceed${RESET}"
    ;;

  # ── test ───────────────────────────────────────────────────────
  test)
    banner
    echo -e "${BLUE}Running test suite...${RESET}"
    echo ""
    cd "$APP"
    python3 -m pytest tests/ -v --tb=short "${@:2}"
    ;;

  # ── agents ─────────────────────────────────────────────────────
  agents)
    banner
    echo -e "${BLUE}Generating / reindexing all IT agents...${RESET}"
    echo ""
    cd "$APP"
    python3 scripts/generate_agents.py
    echo ""
    AGENT_COUNT=$(python3 -c "import json; print(len(json.load(open('agents/agents_index.json'))))" 2>/dev/null || echo "?")
    echo -e "${GREEN}✅ Done — $AGENT_COUNT agents indexed${RESET}"
    ;;

  # ── search ─────────────────────────────────────────────────────
  search)
    TERM="${2:-}"
    if [ -z "$TERM" ]; then
      echo -e "${RED}Usage: search <role-keyword>${RESET}"
      exit 1
    fi
    echo -e "${BLUE}Searching agents for: '$TERM'${RESET}"
    echo ""
    python3 - <<PYEOF
import json
idx = json.load(open("$APP/agents/agents_index.json"))
matches = [a for a in idx if "$TERM".lower() in a.get("role","").lower()
           or "$TERM".lower() in a.get("name","").lower()]
print(f"Found {len(matches)} agents matching '$TERM'\n")
for a in matches[:20]:
    print(f"  {a['id']:12s} | {a['name']:35s} | {a.get('seniority',''):10s} | {a.get('guardrails_profile','')}")
if len(matches) > 20:
    print(f"\n  ... and {len(matches)-20} more. Narrow your search term.")
PYEOF
    ;;

  # ── package ────────────────────────────────────────────────────
  package)
    banner
    echo -e "${BLUE}Building distributable ZIP...${RESET}"
    echo ""
    cd "$APP"
    python3 scripts/package_zip.py
    ;;

  # ── secrets ────────────────────────────────────────────────────
  secrets)
    TARGET="${2:-$WORKSPACE}"
    echo -e "${BOLD}🔍 Secrets-only scan: $TARGET${RESET}"
    echo ""
    python3 - <<PYEOF
import sys
sys.path.insert(0, "$APP")
from guardrails.secrets_scanner import SecretsScanner
findings = SecretsScanner().scan_directory("$TARGET")
if not findings:
    print("✅ No secrets found")
else:
    for f in findings:
        icon = "🔴" if f["severity"] == "critical" else "🟡"
        print(f"{icon} [{f['severity'].upper():8s}] {f['rule_id']:30s} {f['file']}:{f.get('line','?')}")
        print(f"   {f['description']}")
    print(f"\n{len(findings)} issue(s) found")
    sys.exit(1)
PYEOF
    ;;

  # ── packages ───────────────────────────────────────────────────
  packages)
    TARGET="${2:-$WORKSPACE}"
    echo -e "${BOLD}📦 Package policy scan: $TARGET${RESET}"
    echo ""
    python3 - <<PYEOF
import sys
sys.path.insert(0, "$APP")
from guardrails.package_manager import PackageManager
issues = PackageManager().check("$TARGET")
if not issues:
    print("✅ All packages compliant")
else:
    for i in issues:
        print(f"  [{i['type']:15s}] {i.get('package','?'):30s} {i.get('message','')}")
    sys.exit(1)
PYEOF
    ;;

  # ── scaffold ───────────────────────────────────────────────────
  scaffold)
    PROJECT_TYPE="${2:-python-service}"
    PROJECT_NAME="${3:-my-project}"
    TARGET="${4:-$WORKSPACE}"
    echo -e "${BOLD}🏗️  Scaffolding $PROJECT_TYPE: $PROJECT_NAME${RESET}"
    echo ""
    python3 - <<PYEOF
import sys
sys.path.insert(0, "$APP")
from guardrails.folder_validator import FolderValidator
fv = FolderValidator()
created = fv.generate_structure("$PROJECT_TYPE", "$PROJECT_NAME", "$TARGET", dry_run=False)
print(f"✅ Created {len(created)} paths for $PROJECT_TYPE")
for p in created:
    print(f"   {p}")
PYEOF
    ;;

  # ── serve (watch mode) ─────────────────────────────────────────
  serve)
    TARGET="${2:-$WORKSPACE}"
    echo -e "${BLUE}👀 Watch mode — scanning $TARGET every 30s (Ctrl+C to stop)${RESET}"
    echo ""
    while true; do
      echo -e "$(date '+%H:%M:%S') — running check..."
      run_guardrails check "$TARGET" 2>&1 | tail -5
      sleep 30
    done
    ;;

  # ── shell ──────────────────────────────────────────────────────
  shell)
    echo -e "${BLUE}Dropping to bash. Type 'exit' to leave.${RESET}"
    exec /bin/bash
    ;;

  # ── help ───────────────────────────────────────────────────────
  help|--help|-h)
    echo -e "${BOLD}IT Agents Guardrails — Container Commands${RESET}"
    echo ""
    echo "  check    [path]            Scan for violations (default)"
    echo "  fix      [path]            Auto-fix folder structure"
    echo "  block    [path]            Scan + exit 1 on violation (CI/CD)"
    echo "  secrets  [path]            Secrets-only scan"
    echo "  packages [path]            Package policy scan only"
    echo "  scaffold <type> <name>     Scaffold new project structure"
    echo "  search   <keyword>         Search 10,000 IT agent roles"
    echo "  agents                     Generate / reindex all agents"
    echo "  test     [pytest-args]     Run test suite"
    echo "  package                    Build distributable ZIP"
    echo "  serve    [path]            Watch mode (re-checks every 30s)"
    echo "  shell                      Interactive bash session"
    echo "  help                       Show this message"
    echo ""
    echo "  Project types for scaffold:"
    echo "    python-service  node-service  fullstack-app  ml-project"
    echo "    data-pipeline   sqlserver-service  infra-terraform  generic-project"
    echo ""
    echo "  Environment variables:"
    echo "    WORKSPACE          Default scan path (default: /workspace)"
    echo "    GUARDRAILS_MODE    Default mode: check | fix | block"
    echo "    PLATFORM_ENV       development | staging | production"
    echo ""
    ;;

  # ── unknown ────────────────────────────────────────────────────
  *)
    echo -e "${RED}Unknown command: $CMD${RESET}"
    echo "Run 'help' for available commands."
    exit 1
    ;;

esac
