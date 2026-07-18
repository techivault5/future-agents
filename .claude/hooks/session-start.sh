#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# IT Agents Guardrails — Session Start Hook
# Runs automatically when Claude Code starts a session.
# Installs dependencies, activates guardrails, and primes AI context.
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# ── Only run full setup in remote/web environments ───────────────────
# Comment this block out if you want guardrails locally too
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  # Still run the lightweight guardrails check locally
  if command -v python3 &>/dev/null && [ -f "$ROOT/guardrails/guardrails_engine.py" ]; then
    python3 "$ROOT/guardrails/guardrails_engine.py" "$ROOT" --mode check 2>/dev/null || true
  fi
  exit 0
fi

echo "🛡️  IT Agents Guardrails — Session Start"
echo "   Project: $ROOT"
echo "   Environment: ${CLAUDE_CODE_REMOTE:-local}"

# ── 1. Python dependencies ───────────────────────────────────────────
echo ""
echo "📦 Installing Python dependencies..."
pip install --quiet --upgrade pip 2>/dev/null || true

# Core project
if [ -f "$ROOT/pyproject.toml" ]; then
  pip install --quiet -e "$ROOT[dev]" || pip install --quiet -e "$ROOT"
elif [ -f "$ROOT/requirements.txt" ]; then
  pip install --quiet -r "$ROOT/requirements.txt"
fi

# Guardrails-specific deps
pip install --quiet pyyaml packaging

# Optional: richer secret scanning
pip install --quiet detect-secrets 2>/dev/null || true

echo "   ✓ Python dependencies ready"

# ── 2. Node dependencies (if applicable) ────────────────────────────
if [ -f "$ROOT/package.json" ] && command -v npm &>/dev/null; then
  echo ""
  echo "📦 Installing Node dependencies..."
  cd "$ROOT" && npm install --silent
  echo "   ✓ Node dependencies ready"
fi

# ── 3. Pre-commit hooks ──────────────────────────────────────────────
if [ -f "$ROOT/.pre-commit-config.yaml" ] && command -v pre-commit &>/dev/null; then
  echo ""
  echo "🔗 Installing pre-commit hooks..."
  cd "$ROOT" && pre-commit install --install-hooks -q 2>/dev/null || true
  echo "   ✓ Pre-commit hooks installed"
fi

# ── 4. Run guardrails check ──────────────────────────────────────────
echo ""
echo "🛡️  Running guardrails check..."
if [ -f "$ROOT/guardrails/guardrails_engine.py" ]; then
  python3 "$ROOT/guardrails/guardrails_engine.py" "$ROOT" --mode check \
    2>/dev/null && echo "   ✓ Guardrails passed" || echo "   ⚠  Guardrails found issues (see report)"
fi

# ── 5. Export session environment ────────────────────────────────────
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  {
    echo "export PYTHONPATH=\"$ROOT\""
    echo "export GUARDRAILS_CONFIG=\"$ROOT/config/guardrails_config.yaml\""
    echo "export GUARDRAILS_INTERACTIVE=\"false\""   # Non-interactive in Claude sessions
    echo "export IT_AGENTS_ROOT=\"$ROOT\""
    echo "export PLATFORM_ENV=\"${PLATFORM_ENV:-development}\""
  } >> "$CLAUDE_ENV_FILE"
fi

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  ✅ Session ready. Guardrails active."
echo "  📋 Rules: $ROOT/CLAUDE.md"
echo "  🔍 Report: $ROOT/.guardrails-report.json"
echo "═══════════════════════════════════════════════════════"
