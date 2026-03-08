#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# IT Agents Guardrails — Container Entrypoint
#
# Usage:  podman run ... it-agents-guardrails <COMMAND> [args]
#
# Commands:
#   check        [path]              — Scan for violations (default)
#   fix          [path]              — Auto-fix folder structure issues
#   block        [path]              — Scan + exit 1 on any violation (CI mode)
#
# Voice commands (voice-enabled image required):
#   voice-create <sample.wav> <name> — Create a voice profile from an audio sample
#   voice-list                       — List all registered voice profiles
#   voice-search <keyword>           — Search voice profiles
#   voice-speak  <profile-id> <text> — Synthesise speech in a voice
#   voice-score  <profile-id> <wav>  — Score synthesised audio accuracy
#   voice-export <profile-id>        — Export voice as .voicepack (shareable)
#   voice-import <file.voicepack>    — Import a .voicepack from another user
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

  # ── voice-create ───────────────────────────────────────────────
  voice-create)
    SAMPLE_PATH="${2:-}"
    VOICE_NAME="${3:-My Voice}"
    PERSONALITY="${4:-custom}"
    if [ -z "$SAMPLE_PATH" ] || [ ! -f "$SAMPLE_PATH" ]; then
      echo -e "${RED}Usage: voice-create <sample.wav> <name> [personality]${RESET}"
      echo -e "  Personalities: formal-executive friendly-helper technical-expert"
      echo -e "                 enthusiastic-innovator calm-counselor direct-commander"
      echo -e "                 creative-storyteller empathetic-advisor sharp-analyst global-connector"
      exit 1
    fi
    echo -e "${BOLD}🎙️  Creating voice profile: '$VOICE_NAME'${RESET}"
    echo -e "   Sample  : $SAMPLE_PATH"
    echo -e "   Persona : $PERSONALITY"
    echo -e "   Engine  : ${VOICE_ENGINE:-stub}"
    echo ""
    python3 - <<PYEOF
import asyncio, sys
sys.path.insert(0, "$APP")
from future_agents.voice import VoiceCloner, VoiceRegistry
from future_agents.voice.voice_profile import PersonalityType
from pathlib import Path

async def main():
    try:
        personality = PersonalityType("$PERSONALITY")
    except ValueError:
        personality = PersonalityType.CUSTOM

    registry = VoiceRegistry(registry_dir=Path("${VOICE_REGISTRY_DIR:-$WORKSPACE/.voice-registry}"))
    cloner = VoiceCloner(target_score=float("${VOICE_TARGET_SCORE:-9.5}"))
    profile = await cloner.create_profile_from_sample(
        sample_path="$SAMPLE_PATH",
        name="$VOICE_NAME",
        personality=personality,
    )
    registry.save(profile)
    print(f"✅ Voice profile created!")
    print(f"   ID         : {profile.id}")
    print(f"   Name       : {profile.name}")
    print(f"   Personality: {profile.personality.value}")
    print(f"   Embedding  : {profile.embedding.dimension if profile.embedding else 'none'}-d")
    print(f"   Best score : {profile.best_score}/10")
    print(f"")
    print(f"   Next steps:")
    print(f"   → Speak:  voice-speak {profile.id} 'Hello, I am your IT assistant'")
    print(f"   → Export: voice-export {profile.id}")

asyncio.run(main())
PYEOF
    ;;

  # ── voice-list ─────────────────────────────────────────────────
  voice-list)
    echo -e "${BOLD}🎙️  Registered Voice Profiles${RESET}"
    python3 - <<PYEOF
import sys
sys.path.insert(0, "$APP")
from future_agents.voice import VoiceRegistry
from pathlib import Path

registry = VoiceRegistry(registry_dir=Path("${VOICE_REGISTRY_DIR:-$WORKSPACE/.voice-registry}"))
profiles = registry.list_all()
if not profiles:
    print("  No voice profiles registered yet.")
    print("  Run: voice-create <sample.wav> <name>")
else:
    print(f"  {'ID':20s} {'Name':30s} {'Persona':25s} {'Score':7s}")
    print("  " + "─" * 90)
    for p in sorted(profiles, key=lambda x: x.get("best_score", 0), reverse=True):
        print(f"  {p['id']:20s} {p['name']:30s} {p.get('personality','?'):25s} {p.get('best_score',0):.1f}/10")
PYEOF
    ;;

  # ── voice-search ───────────────────────────────────────────────
  voice-search)
    QUERY="${2:-}"
    echo -e "${BOLD}🔍 Voice profile search: '$QUERY'${RESET}"
    python3 - <<PYEOF
import sys
sys.path.insert(0, "$APP")
from future_agents.voice import VoiceRegistry
from pathlib import Path

registry = VoiceRegistry(registry_dir=Path("${VOICE_REGISTRY_DIR:-$WORKSPACE/.voice-registry}"))
results = registry.search("$QUERY")
if not results:
    print("  No profiles found matching '$QUERY'")
else:
    for p in results:
        print(f"  {p['id']}  {p['name']}  [{p.get('personality','?')}] score={p.get('best_score',0):.1f}/10")
        print(f"    Tags: {', '.join(p.get('tags',[]))}")
PYEOF
    ;;

  # ── voice-speak ────────────────────────────────────────────────
  voice-speak)
    PROFILE_ID="${2:-}"
    TEXT="${3:-Hello, I am your IT assistant.}"
    if [ -z "$PROFILE_ID" ]; then
      echo -e "${RED}Usage: voice-speak <profile-id> <text>${RESET}"
      exit 1
    fi
    echo -e "${BOLD}🔊 Synthesising speech: '$TEXT'${RESET}"
    python3 - <<PYEOF
import asyncio, sys
sys.path.insert(0, "$APP")
from future_agents.voice import VoiceCloner, VoiceRegistry
from pathlib import Path

async def main():
    registry = VoiceRegistry(registry_dir=Path("${VOICE_REGISTRY_DIR:-$WORKSPACE/.voice-registry}"))
    profile = registry.load("$PROFILE_ID")
    cloner = VoiceCloner(
        output_dir=Path("$WORKSPACE/.voice-output"),
        target_score=float("${VOICE_TARGET_SCORE:-9.5}"),
    )
    result = await cloner.synthesize(profile, """$TEXT""")
    registry.save(profile)  # persist updated improvement history
    print(f"✅ Speech synthesised!")
    print(f"   Audio  : {result.audio_path}")
    print(f"   Engine : {result.engine}")
    print(f"   Score  : {result.score:.2f}/10  (iteration {result.iteration})")
    print(f"   Speaker similarity : {result.speaker_similarity:.2f}/10")
    print(f"   Prosody match      : {result.prosody_match:.2f}/10")
    print(f"   MOS predictor      : {result.mos:.2f}/10")

asyncio.run(main())
PYEOF
    ;;

  # ── voice-score ────────────────────────────────────────────────
  voice-score)
    PROFILE_ID="${2:-}"
    AUDIO_PATH="${3:-}"
    if [ -z "$PROFILE_ID" ] || [ -z "$AUDIO_PATH" ]; then
      echo -e "${RED}Usage: voice-score <profile-id> <synthesised.wav>${RESET}"
      exit 1
    fi
    echo -e "${BOLD}📊 Scoring voice accuracy${RESET}"
    python3 - <<PYEOF
import asyncio, sys
sys.path.insert(0, "$APP")
from future_agents.voice import VoiceRegistry, VoiceScorer
from pathlib import Path

async def main():
    registry = VoiceRegistry(registry_dir=Path("${VOICE_REGISTRY_DIR:-$WORKSPACE/.voice-registry}"))
    profile = registry.load("$PROFILE_ID")
    ref_wav = registry.get_reference_wav("$PROFILE_ID")
    scorer = VoiceScorer()
    score = await scorer.score(profile, "$AUDIO_PATH", reference_path=ref_wav)
    print(score)

asyncio.run(main())
PYEOF
    ;;

  # ── voice-export ───────────────────────────────────────────────
  voice-export)
    PROFILE_ID="${2:-}"
    if [ -z "$PROFILE_ID" ]; then
      echo -e "${RED}Usage: voice-export <profile-id>${RESET}"
      exit 1
    fi
    echo -e "${BOLD}📦 Exporting voice profile...${RESET}"
    python3 - <<PYEOF
import sys
sys.path.insert(0, "$APP")
from future_agents.voice import VoiceRegistry
from pathlib import Path

registry = VoiceRegistry(registry_dir=Path("${VOICE_REGISTRY_DIR:-$WORKSPACE/.voice-registry}"))
pack = registry.export_voicepack("$PROFILE_ID", output_dir=Path("$WORKSPACE"))
print(f"✅ VoicePack exported: {pack}")
print(f"   Size: {pack.stat().st_size / 1024:.1f} KB")
print(f"")
print(f"   Share this file with anyone. They can import it with:")
print(f"   podman run ... it-agents-voice voice-import {pack.name}")
PYEOF
    ;;

  # ── voice-import ───────────────────────────────────────────────
  voice-import)
    PACK_PATH="${2:-}"
    if [ -z "$PACK_PATH" ] || [ ! -f "$PACK_PATH" ]; then
      echo -e "${RED}Usage: voice-import <file.voicepack>${RESET}"
      exit 1
    fi
    echo -e "${BOLD}📥 Importing voice profile: $PACK_PATH${RESET}"
    python3 - <<PYEOF
import sys
sys.path.insert(0, "$APP")
from future_agents.voice import VoiceRegistry
from pathlib import Path

registry = VoiceRegistry(registry_dir=Path("${VOICE_REGISTRY_DIR:-$WORKSPACE/.voice-registry}"))
profile = registry.import_voicepack("$PACK_PATH", overwrite=False)
print(f"✅ Voice profile imported!")
print(f"   ID   : {profile.id}")
print(f"   Name : {profile.name}")
print(f"   Score: {profile.best_score}/10")
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
    echo "  ── Guardrails ──────────────────────────────────────────────"
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
    echo ""
    echo "  ── Voice (it-agents-voice image required) ──────────────────"
    echo "  voice-create <wav> <name> [persona]  Create voice from sample"
    echo "  voice-list                            List all voice profiles"
    echo "  voice-search <keyword>                Search voice profiles"
    echo "  voice-speak  <id> <text>              Synthesise speech"
    echo "  voice-score  <id> <wav>               Score voice accuracy (0-10)"
    echo "  voice-export <id>                     Export as .voicepack (shareable)"
    echo "  voice-import <file.voicepack>         Import shared voice"
    echo ""
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
