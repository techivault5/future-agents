# IT Agents Guardrails — Windsurf Rules

You are an AI coding assistant in a guardrails-enforced project.
These rules apply to every file, every completion, every refactor.

## Non-Negotiable Rules

### 1. Secrets
Never write literal credentials. Always environment variables.
```python
✅ os.environ["API_KEY"]
❌ api_key = "sk-real-key-here"
```

### 2. Package Versions
Use ranges, never exact pins in application manifests.
```
✅ requests~=2.31    ✅ "react": "^18.0.0"
❌ requests==2.31.0  ❌ "react": "18.0.0"
```

### 3. Folder Structure
Source code in `src/`, tests in `tests/`, never scattered in project root.
Follow the layout in `CLAUDE.md` for this project type.

### 4. Security by Default
- Parameterized SQL always
- HTTPS always, never `verify=False`
- bcrypt/argon2 for passwords
- Validate all user inputs

### 5. Human Checkpoints
Pause and confirm before: major upgrades, auth changes, schema migrations,
file deletions, production config changes.

## Guardrails Check
```bash
python3 guardrails/guardrails_engine.py . --mode check
```
