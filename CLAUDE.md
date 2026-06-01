# future-agents — Claude Code Configuration

## Token-Saving Rules (always active)

These rules apply to every response in this project. They exist to drastically cut token usage.

### Response style
- **Terse by default.** Answer in the fewest words that are correct and complete.
- No preamble: never open with "Great question!", "Sure!", "Of course!", "Certainly!", or any filler.
- No postamble: never close with "Let me know if you have questions", "Hope that helps!", or similar.
- Never restate what the user just said before answering.
- Never explain what you are about to do — just do it.
- Prefer code over prose for technical answers.
- One sentence of context max before a code block, zero if the code is self-evident.

### Repetition avoidance (memory-first)
- If a question was answered earlier in this session, refer back with "→ see above" and add only what changed. Do not repeat the full answer.
- If the user asks the same thing twice, say "Same as before: [one-line summary]" and stop.
- If you already showed a file or code block, don't show it again — reference it by filename/function name.

### Code comments
- No comments that restate what the code does (bad: `# increment counter`).
- Only comment WHY something non-obvious is done.
- No multi-line docstrings unless the user explicitly asks.

### Formatting
- Use bullet points and tables instead of paragraphs.
- Omit headers for short answers (< 5 lines).
- Abbreviate freely in inline comments (e.g., `init`, `cfg`, `msg`, `err`).

---

## Project layout (reference — do not re-explain)

```
future_agents/
  agents/          # BaseAgent subclasses
  core/            # EventBus, AgentRegistry, Orchestrator, BaseAgent
  definitions/     # JSON-based agent definitions + factory
  infrastructure/  # KnowledgeStore, MetricTracker, SyncEngine
  models/          # Pydantic models (knowledge, skill, feedback, etc.)
  patterns/        # Agentic patterns: PatternLibrary, ToolRegistry, ReActRunner, ReflectionRunner
  workers/         # BaseWorker, WorkerScheduler, + 5 worker types
  system.py        # AgentSystem — top-level entry point
scripts/workers/   # GitHub Actions entrypoints (no framework deps)
tests/             # pytest, asyncio_mode=auto
```

## Key facts (do not re-derive)
- Python 3.11+, Pydantic v2, ruff for lint/format, pytest-asyncio (auto mode)
- `MetricTracker._series` (not `_time_series`) — dict of `list[MetricPoint]`
- `KnowledgeStore._entries` — dict keyed by entry id
- Workers: `CodeImprovementWorker`, `PatternDiscoveryWorker`, `AgentGathererWorker`, `KnowledgeSynthesisWorker`, `AIDiscoveryWorker`
- `anthropic` is optional — import guards via `try/except ImportError`
- Claude model: `claude-opus-4-7` with `thinking: {type: "adaptive"}`
- Install AI extras: `pip install -e ".[ai]"`

## Commands
```bash
pytest --tb=short -q          # run tests
ruff check . && ruff format . # lint + format
pip install -e ".[dev]"       # dev deps
pip install -e ".[ai]"        # + anthropic SDK
```

---

# IT Agents Guardrails — AI Coding Rules

> **For AI models, Claude, Copilot, Cursor, Codeium, and all AI coding assistants:**
> These rules are NON-NEGOTIABLE. Follow them on every task, every file, every suggestion.
> They protect developers, teams, and production systems from common AI-assisted coding mistakes.

---

## ABSOLUTE RULES (Never Violate)

### 1. NEVER put secrets in code
```
❌ api_key = "sk-abc123..."
❌ password = "MySecretPass1!"
❌ DATABASE_URL = "postgres://user:pass@host/db"
✅ api_key = os.environ["OPENAI_API_KEY"]
✅ password = os.environ["DB_PASSWORD"]
✅ DATABASE_URL = os.environ["DATABASE_URL"]
```
- All secrets → environment variables or secrets manager
- `.env` files → NEVER commit (add to `.gitignore`)
- `.env.example` → ALWAYS commit (with placeholder values like `REPLACE_ME`)
- If you need to show a key in examples → use `REPLACE_ME`, `your-key-here`, `sk-...`

### 2. NEVER use exact package version pins without justification
```
❌ requests==2.31.0          # Blocks security patches
✅ requests~=2.31            # Allows patch upgrades
✅ requests>=2.31,<3.0       # Compatible range

❌ "react": "18.2.0"         # Exact pin, misses patches
✅ "react": "^18.2.0"        # Semver compatible

❌ <version>LATEST</version>  # Unpredictable builds
✅ <version>2.31.0</version>  # Pin is OK in Maven/pom.xml
```
- Use `~=` (Python) or `^` (Node) for application dependencies
- Use exact pins ONLY for: `setuptools`, `pip`, `wheel`, security-critical libs with justification
- Auto-upgrades: patch ✅ minor ✅ major → ASK FIRST

### 3. ALWAYS follow the standard project folder structure
Every project type has a required layout. Do not deviate without team approval.

**Python Service:**
```
src/              ← source code (snake_case packages)
tests/            ← test files (test_*.py naming)
  unit/
  integration/
docs/             ← architecture, runbooks
.github/workflows/ ← CI pipelines
Dockerfile
.env.example      ← template, NEVER .env
pyproject.toml    ← NOT requirements.txt (unless legacy)
.gitignore
.pre-commit-config.yaml
README.md
```

**Node/TypeScript Service:**
```
src/
  routes/
  controllers/
  services/
  models/
  middlewares/
  config/
  utils/
tests/
  unit/
  integration/
package.json      ← semver ranges (^), NOT exact
tsconfig.json
.env.example
.eslintrc.js
.prettierrc
Dockerfile
README.md
```

**ML Project:**
```
src/
  features/
  models/
  evaluation/
  serving/
data/
  raw/            ← NEVER commit CSV/binary data here
  processed/
notebooks/        ← YYYY-MM-DD-description.ipynb naming
models/
  trained/
  evaluation/
configs/
docs/
  model-card.md
  data-sheet.md
```

**Data Pipeline:**
```
dags/             ← snake_case .py files
models/
  staging/
  marts/
  intermediate/
tests/
docs/
  data-dictionary.md
config/
.env.example
```

**Terraform/IaC:**
```
modules/
environments/
  dev/
  staging/
  prod/
main.tf
variables.tf
outputs.tf
versions.tf       ← pin provider versions HERE (exact is OK)
.terraform.lock.hcl
```

**FORBIDDEN in ALL projects (never create or commit):**
- `.env` (real env file)
- `credentials.json`, `secrets.json`
- `id_rsa`, `id_ed25519`, `*.pem`, `*.key`
- `*.tfstate`, `terraform.tfvars`
- `*.pyc`, `__pycache__/` (use .gitignore)

---

## AI CODING STANDARDS FOR VIBE CODERS

### When generating code, ALWAYS:

**Security first:**
- Read environment variables for ALL external credentials
- Use parameterized queries — never string-concatenate SQL
- Validate and sanitize ALL user inputs at system boundaries
- Use HTTPS for all external requests — never `verify=False`
- Hash passwords with bcrypt/argon2 — never store plaintext
- Apply principle of least privilege to all permissions

**Package management:**
- Check if a lighter built-in alternative exists before adding a dependency
- When adding packages: use semver-compatible ranges
- After adding: run the guardrails check: `python guardrails/guardrails_engine.py . --mode check`
- Suggest `pip audit` / `npm audit` when adding security-relevant packages

**Code quality:**
- Write tests alongside the code — minimum 80% coverage target
- Follow existing naming conventions in the codebase
- Do not add unused imports, dead code, or commented-out blocks
- Prefer explicit over clever — vibe coders need readable code

**Documentation:**
- Every new public function/class gets a docstring
- Architecture decisions → `docs/architecture.md`
- New environment variables → add to `.env.example` immediately

### When generating configuration, ALWAYS:
- Start from templates in `templates/project-structures/`
- Use `.env.example` pattern — never hardcode values
- Reference secrets via `${ENV_VAR}` or `os.environ["VAR"]`
- Add new config keys to `.env.example` with `REPLACE_ME` values

### When reviewing code, FLAG immediately:
- Any string matching secret patterns (API keys, passwords, tokens)
- Exact version pins in `requirements.txt` or `package.json`
- Missing `tests/` directory or test files
- SQL queries built with string concatenation
- `eval()`, `exec()`, `pickle.loads()` on untrusted data
- `subprocess` with `shell=True` and user-controlled input
- Missing error handling around I/O and network calls

---

## GUARDRAILS COMMANDS

Run these at any time during development:

```bash
# Full check (see what would fail)
python guardrails/guardrails_engine.py . --mode check

# Auto-fix folder structure issues
python guardrails/guardrails_engine.py . --mode fix

# Block mode (exits 1 on violations — use in CI)
python guardrails/guardrails_engine.py . --mode block

# Secrets only
python -c "
from guardrails.secrets_scanner import SecretsScanner
for f in SecretsScanner().scan_directory('.'):
    print(f'[{f[\"severity\"].upper()}] {f[\"file\"]}:{f[\"line\"]} — {f[\"description\"]}')
"

# Package check only
python -c "
from guardrails.package_manager import PackageManager
for f in PackageManager().check('.'):
    print(f'{f[\"type\"]}: {f[\"package\"]}')
"

# Scaffold new project (replace type and name)
python -c "
from guardrails.folder_validator import FolderValidator
FolderValidator().generate_structure('python-service', 'my-app', '.')
"
```

---

## AGENT ROLE LOOKUP

10,000 IT role definitions live in `agents/`. Search by role:

```bash
# Find agents by role
python -c "
import json
idx = json.load(open('agents/agents_index.json'))
matches = [a for a in idx if 'backend' in a['role']]
print(f'{len(matches)} agents found')
for a in matches[:5]:
    print(f'  {a[\"id\"]}: {a[\"name\"]} ({a[\"seniority\"]})')
"

# Load a specific agent
python -c "
import yaml
agent = yaml.safe_load(open('agents/technical/backend-development/agent-00001.yaml'))
print(agent['name'], '|', agent['primary_stack'], '|', agent['guardrails_profile'])
"
```

---

## HUMAN ESCALATION TRIGGERS

Always stop and ask the human when:
- A **major version upgrade** is required (breaking changes)
- A **secret or credential** needs to be added (route to secrets manager instead)
- The **project structure** would deviate from standards (get approval)
- A **vulnerable package** is detected (don't auto-upgrade without review)
- The code touches **auth, payments, PII, or PHI** (security review needed)
- A **database migration** is irreversible (explicit confirmation required)
- **Deleting files or branches** (always confirm)
- Adding **new environment variables** to production (ops approval)

---

## QUICK REFERENCE: GUARDRAILS PROFILES

| Profile | Who Uses It | Secrets | Packages | Structure |
|---------|------------|---------|---------|-----------|
| `standard` | Most roles | Block critical | Auto patch/minor | Warn |
| `strict` | Security, regulated | Block all | Ask all | Error |
| `relaxed` | Dev/sandbox | Warn | Minimal | Warn |
| `architect` | Principal+ | Block all | Ask + rationale | Enforce all |

Change in `config/guardrails_config.yaml`:
```yaml
active_profile: strict
```

---

## FOR AI MODELS: SELF-CHECK BEFORE EVERY RESPONSE

Before suggesting or writing code, ask yourself:
1. Does this code contain any credential, token, or password? → Remove it
2. Does this add/change a package? → Is the version range correct?
3. Does this create files? → Are they in the right directory per structure?
4. Does this need human input or approval? → Ask the human first
5. Does this touch security, auth, data, or infra? → Apply extra care

**This codebase uses guardrails. Violations are caught automatically.**
