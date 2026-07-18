#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# IT Agents Guardrails — Universal Installer
#
# Install guardrails into ANY project with one command:
#
#   curl -sSL https://raw.githubusercontent.com/techivault5/future-agents/main/scripts/install.sh | bash
#
# Or locally:
#   bash path/to/future-agents/scripts/install.sh [target-dir] [project-type]
#
# Project types: python-service | node-service | fullstack-app |
#                data-pipeline  | ml-project   | infra-terraform |
#                microservice-docker | generic-project
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

# ── Config ───────────────────────────────────────────────────────
GUARDRAILS_REPO="https://github.com/techivault5/future-agents"
GUARDRAILS_BRANCH="claude/it-agents-guardrails-setup-EDhUR"
TARGET="${1:-.}"
PROJECT_TYPE="${2:-auto}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(dirname "$SCRIPT_DIR")"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
RESET='\033[0m'

info()    { echo -e "${BLUE}ℹ️  $*${RESET}"; }
success() { echo -e "${GREEN}✅ $*${RESET}"; }
warn()    { echo -e "${YELLOW}⚠️  $*${RESET}"; }
error()   { echo -e "${RED}❌ $*${RESET}"; exit 1; }

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  🛡️  IT Agents Guardrails Installer"
echo "  Target: $(realpath "$TARGET")"
echo "  Profile: $PROJECT_TYPE"
echo "═══════════════════════════════════════════════════════════"
echo ""

TARGET="$(realpath "$TARGET")"
mkdir -p "$TARGET"

# ── Step 1: Copy guardrails engine ───────────────────────────────
info "Installing guardrails engine..."
mkdir -p "$TARGET/guardrails"

for f in guardrails_engine.py secrets_scanner.py package_manager.py \
          folder_validator.py human_input_handler.py; do
  if [ -f "$SOURCE_ROOT/guardrails/$f" ]; then
    cp "$SOURCE_ROOT/guardrails/$f" "$TARGET/guardrails/$f"
  fi
done
# Init file for importability
touch "$TARGET/guardrails/__init__.py"
success "Guardrails engine installed"

# ── Step 2: Copy config ──────────────────────────────────────────
info "Installing configuration..."
mkdir -p "$TARGET/config"
cp "$SOURCE_ROOT/config/guardrails_config.yaml" "$TARGET/config/"
cp "$SOURCE_ROOT/config/connective_config.yaml" "$TARGET/config/"
success "Configuration installed"

# ── Step 3: Copy skills ──────────────────────────────────────────
info "Installing skills..."
mkdir -p "$TARGET/skills"
cp "$SOURCE_ROOT/skills/combined_guardrails.yaml" "$TARGET/skills/"
success "Skills installed"

# ── Step 4: Install CLAUDE.md ────────────────────────────────────
info "Installing AI coding rules (CLAUDE.md)..."
if [ ! -f "$TARGET/CLAUDE.md" ]; then
  cp "$SOURCE_ROOT/CLAUDE.md" "$TARGET/CLAUDE.md"
  success "CLAUDE.md installed"
else
  warn "CLAUDE.md already exists — skipping (add guardrails rules manually)"
fi

# ── Step 5: Install Claude Code hook ────────────────────────────
info "Installing Claude Code session hook..."
mkdir -p "$TARGET/.claude/hooks"
cp "$SOURCE_ROOT/.claude/hooks/session-start.sh" "$TARGET/.claude/hooks/session-start.sh"
chmod +x "$TARGET/.claude/hooks/session-start.sh"

# Merge into .claude/settings.json
SETTINGS="$TARGET/.claude/settings.json"
if [ ! -f "$SETTINGS" ]; then
  cat > "$SETTINGS" << 'EOF'
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/session-start.sh"
          }
        ]
      }
    ]
  }
}
EOF
  success "Claude Code hook registered"
else
  warn ".claude/settings.json exists — add the SessionStart hook manually:"
  echo '    "$CLAUDE_PROJECT_DIR/.claude/hooks/session-start.sh"'
fi

# ── Step 6: Install Cursor rules ────────────────────────────────
if [ -f "$SOURCE_ROOT/.cursor/rules/guardrails.mdc" ]; then
  mkdir -p "$TARGET/.cursor/rules"
  cp "$SOURCE_ROOT/.cursor/rules/guardrails.mdc" "$TARGET/.cursor/rules/guardrails.mdc"
  success "Cursor rules installed"
fi

# ── Step 7: Install Copilot instructions ────────────────────────
if [ -f "$SOURCE_ROOT/.github/copilot-instructions.md" ]; then
  mkdir -p "$TARGET/.github"
  if [ ! -f "$TARGET/.github/copilot-instructions.md" ]; then
    cp "$SOURCE_ROOT/.github/copilot-instructions.md" "$TARGET/.github/copilot-instructions.md"
    success "GitHub Copilot instructions installed"
  else
    warn ".github/copilot-instructions.md exists — append guardrails manually"
  fi
fi

# ── Step 8: Install pre-commit config ───────────────────────────
info "Installing pre-commit hooks..."
if [ ! -f "$TARGET/.pre-commit-config.yaml" ]; then
  cp "$SOURCE_ROOT/templates/ci/pre-commit-guardrails.yaml" "$TARGET/.pre-commit-config.yaml"
  success "Pre-commit config installed"
  if command -v pre-commit &>/dev/null; then
    cd "$TARGET" && pre-commit install -q 2>/dev/null && success "Pre-commit hooks activated"
  else
    warn "Install pre-commit: pip install pre-commit && pre-commit install"
  fi
else
  warn ".pre-commit-config.yaml exists — add guardrails hook manually"
fi

# ── Step 9: Scaffold project structure ──────────────────────────
info "Scaffolding standard folder structure ($PROJECT_TYPE)..."
if command -v python3 &>/dev/null; then
  python3 - << PYEOF
import sys
sys.path.insert(0, "$TARGET")
try:
    from guardrails.folder_validator import FolderValidator
    fv = FolderValidator({"project_type": "$PROJECT_TYPE" if "$PROJECT_TYPE" != "auto" else None})
    ftype = fv.detect_project_type("$TARGET")
    created = fv.generate_structure(ftype, "", "$TARGET", dry_run=False)
    print(f"   Scaffolded {len(created)} paths for {ftype} project")
except Exception as e:
    print(f"   (scaffold skipped: {e})")
PYEOF
  success "Folder structure scaffolded"
fi

# ── Step 10: Update .gitignore ───────────────────────────────────
info "Updating .gitignore..."
GITIGNORE="$TARGET/.gitignore"
GUARDRAILS_GITIGNORE_BLOCK="
# IT Agents Guardrails
.env
.guardrails-report.json
.guardrails-human-log.jsonl
.guardrails.sarif
*.pem
*.key
id_rsa
id_ed25519
credentials.json
secrets.json
terraform.tfvars
*.tfstate
*.tfstate.backup
"
if [ -f "$GITIGNORE" ]; then
  if ! grep -q "IT Agents Guardrails" "$GITIGNORE"; then
    echo "$GUARDRAILS_GITIGNORE_BLOCK" >> "$GITIGNORE"
    success ".gitignore updated"
  else
    info ".gitignore already has guardrails entries"
  fi
else
  echo "$GUARDRAILS_GITIGNORE_BLOCK" > "$GITIGNORE"
  success ".gitignore created"
fi

# ── Step 11: Install Python deps ────────────────────────────────
if command -v pip &>/dev/null || command -v pip3 &>/dev/null; then
  info "Installing Python guardrails dependencies..."
  pip install --quiet pyyaml packaging 2>/dev/null || \
  pip3 install --quiet pyyaml packaging 2>/dev/null || \
  warn "Could not install Python deps — run: pip install pyyaml packaging"
  success "Python dependencies ready"
fi

# ── Step 12: Run first guardrails check ─────────────────────────
echo ""
info "Running first guardrails check on your project..."
python3 "$TARGET/guardrails/guardrails_engine.py" "$TARGET" --mode check 2>/dev/null || true

# ── Done ─────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  🎉 GUARDRAILS INSTALLED SUCCESSFULLY"
echo ""
echo "  Next steps:"
echo "  1. Review: cat $TARGET/CLAUDE.md"
echo "  2. Check:  python3 guardrails/guardrails_engine.py . --mode check"
echo "  3. Fix:    python3 guardrails/guardrails_engine.py . --mode fix"
echo "  4. CI:     copy templates/ci/github-actions-guardrails.yml"
echo "             → .github/workflows/guardrails.yml"
echo ""
echo "  Your AI coding assistant now reads CLAUDE.md automatically."
echo "  Guardrails run on every Claude Code session start."
echo "═══════════════════════════════════════════════════════════"
echo ""
