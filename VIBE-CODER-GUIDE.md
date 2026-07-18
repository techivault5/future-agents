# Vibe Coder Guide — Coding Safely with AI

> You move fast, you trust your AI. These guardrails make sure fast doesn't mean reckless.
> Read this once. The tools enforce it automatically after that.

---

## The 5 Rules of AI-Assisted Coding

### Rule 1: No Secrets in Code. Ever.

AI models (Claude, Copilot, Cursor) will helpfully suggest code with real-looking API keys.
They might autocomplete `api_key = "sk-..."` from your context. **Don't commit it.**

```python
# ❌ What AI might suggest (looks helpful, is dangerous)
client = OpenAI(api_key="sk-proj-abc123yourkeyhere")

# ✅ What you should always use
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
```

**The guardrail catches this automatically.** If you try to commit a secret, the pre-commit
hook stops you and explains what to do instead.

**If you accidentally committed a secret:**
1. Rotate the credential immediately (generate a new key)
2. Remove it from code and history: `git filter-repo` or BFG Repo Cleaner
3. Add the key name to `.env.example` with `REPLACE_ME`

---

### Rule 2: Let AI Write Code, Not Choose Versions

AI assistants often pin packages to exact versions they were trained on.
These are frequently outdated and block security patches.

```
# ❌ AI-generated (trained on old data)
requests==2.28.0          ← blocks patches, often outdated

# ✅ What you want
requests~=2.31            ← gets bug fixes automatically
```

**The guardrail flags exact pins** and suggests the right range. Accept the suggestion.
For major upgrades, the system asks you before doing anything.

---

### Rule 3: Structure First, Code Second

AI assistants will generate files wherever is convenient.
Left unchecked, you end up with `utils.py` in the root, tests scattered everywhere,
and no docs folder. Future-you (and your teammates) will hate this.

Use the scaffolding tool before starting any new project:

```bash
python guardrails/folder_validator.py generate python-service my-project .
```

This creates the standard layout instantly. AI tools then fill in the right places.

---

### Rule 4: Ask When Uncertain — AI Will Confirm

The guardrails system is set up to pause and ask you when decisions matter:
- "This is a major version upgrade. Have you reviewed the changelog?"
- "A secret was detected. Have you rotated it?"
- "This file structure deviates from standards. Has your lead approved this?"

**Don't skip these prompts.** They exist because AI assistants sometimes confidently do
the wrong thing. A 10-second confirmation prevents hours of cleanup.

---

### Rule 5: Run the Check Before You Push

```bash
python guardrails/guardrails_engine.py . --mode check
```

Takes a few seconds. Shows you exactly what's wrong before your CI does.
The CI will run this too — but catching it locally is faster.

---

## Your AI Toolchain Setup

### Claude Code (this tool)
- `CLAUDE.md` in your project root → Claude reads this every session
- `.claude/hooks/session-start.sh` → runs guardrails automatically on session start
- Works in Claude Code web, desktop, and CLI

### Cursor
- `.cursor/rules/guardrails.mdc` → Cursor uses this as system context
- Rules are applied to every completion and chat in the project

### GitHub Copilot
- `.github/copilot-instructions.md` → Copilot reads this for context
- Instructs Copilot to follow your team's guardrail rules

### VS Code (any AI extension)
- `.vscode/settings.json` → configures linting, formatting, test runner

### Pre-commit (git level)
- `.pre-commit-config.yaml` → runs guardrails before every `git commit`
- Catches secrets and structure issues before they ever reach GitHub

---

## Daily Workflow for Vibe Coders

```
Morning:
  git pull                                    ← sync latest
  python guardrails/guardrails_engine.py .    ← check state

During coding:
  Let AI generate code freely
  Review suggestions before accepting
  Run check after significant changes

Before committing:
  git diff --staged                           ← review what's going in
  python guardrails/guardrails_engine.py . --mode check
  git add specific-files (not git add -A)
  git commit                                  ← pre-commit hook runs

Before pushing:
  python guardrails/guardrails_engine.py . --mode block   ← final gate
  git push
```

---

## Common AI Coding Mistakes & Guardrail Fixes

| AI Does This | Guardrail Says | Fix |
|---|---|---|
| `password = "abc123"` in code | 🚫 BLOCK: Secret detected | Use `os.environ["PASSWORD"]` |
| `requests==2.28.0` in requirements | ⚠️ WARN: Exact pin | Change to `requests~=2.28` |
| Creates `helper.py` in project root | ⚠️ WARN: Wrong location | Move to `src/utils/helper.py` |
| `npm install lodash@4.17.11` (old/vuln) | 🚫 BLOCK: Vulnerable package | Upgrade to latest |
| `"lodash": "latest"` in package.json | ⚠️ WARN: Version wildcard | Use `"^4.17.0"` |
| No `tests/` directory | ⚠️ WARN: Missing required path | Run `--mode fix` to create |
| Notebook named `analysis.ipynb` | ⚠️ WARN: Naming convention | Rename `2026-03-08-analysis.ipynb` |
| `eval(user_input)` | 🔴 FLAG: Security risk | Rewrite without eval |
| SQL string concatenation | 🔴 FLAG: Injection risk | Use parameterized queries |
| `verify=False` in requests | 🔴 FLAG: TLS disabled | Remove or use proper cert |

---

## Finding the Right Agent for Your Task

10,000 IT role definitions are in `agents/`. Each defines skills, tools, and guardrails profile
appropriate for that role. Use them as context for AI tasks:

```bash
# Search agents by keyword
python -c "
import json
idx = json.load(open('agents/agents_index.json'))
keyword = 'security'  # change this
matches = [a for a in idx if keyword in a['role'] or keyword in a['name'].lower()]
print(f'{len(matches)} agents for \"{keyword}\"')
for a in matches[:8]:
    print(f'  {a[\"seniority\"]:15} {a[\"name\"]}')
"
```

Load an agent's context into your AI session to get role-appropriate suggestions.

---

## Getting Help

```bash
# What guardrails failed?
cat .guardrails-report.json | python -m json.tool

# What did humans approve/deny?
cat .guardrails-human-log.jsonl

# Scaffold a fresh project
python guardrails/folder_validator.py  # see FolderValidator.generate_structure()

# Full check with verbose output
GUARDRAILS_INTERACTIVE=true python guardrails/guardrails_engine.py . --mode check
```

---

## Quick Install in Any Project

```bash
# From this repo
bash scripts/install.sh /path/to/your/project python-service

# Or copy just the CLAUDE.md + guardrails/ to any project
cp -r guardrails/ CLAUDE.md config/ skills/ /your/project/
pip install pyyaml packaging
```

Once installed, every Claude Code session, every Cursor session, every Copilot suggestion
is guided by the same rules. One install, everywhere.
