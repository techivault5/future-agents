# GitHub Copilot Instructions — IT Agents Guardrails

This project enforces strict guardrails for AI-assisted coding.
Follow these instructions for every suggestion and completion.

## Security Rules

**Secrets:** Never suggest hardcoded credentials, API keys, tokens, or passwords.
Always use environment variables: `os.environ["KEY"]` or `process.env.KEY`.
For examples use placeholders: `REPLACE_ME`, `your-key-here`.

**SQL:** Always use parameterized queries. Never concatenate strings into SQL.
```python
# NEVER: cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
# ALWAYS: cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
```

**HTTP:** Always use HTTPS. Never suggest `verify=False` or `rejectUnauthorized: false`.

**Passwords:** Use bcrypt or argon2. Never suggest MD5, SHA1, or plaintext storage.

## Package Version Rules

```
Python requirements.txt / pyproject.toml:
  ✅ requests~=2.31     ✅ fastapi>=0.111,<1.0
  ❌ requests==2.31.0   ❌ django==4.2.0

Node package.json:
  ✅ "^18.2.0"   ✅ "~18.2.0"
  ❌ "18.2.0"    ❌ "latest"    ❌ "*"
```

For major version bumps (e.g., v1→v2): warn the developer and suggest they
review the changelog before proceeding.

## Project Structure Rules

Suggest file locations that match the project's standard structure:
- Python source code → `src/{package_name}/`
- Python tests → `tests/test_*.py` (unit/) or `tests/integration/`
- Node source → `src/` with `routes/`, `controllers/`, `services/`, `models/`
- ML notebooks → `notebooks/YYYY-MM-DD-description.ipynb`
- Config/secrets → reference environment variables, not hardcoded values
- Documentation → `docs/` directory

Never suggest creating files in the project root unless they are standard
top-level files (README, Dockerfile, pyproject.toml, package.json, etc.)

## Code Quality Rules

- Write tests alongside new functions (80% coverage target)
- Add docstrings to all public functions and classes
- Prefer explicit, readable code over clever one-liners
- Handle errors explicitly — don't swallow exceptions silently
- Log errors with context, not just `print()` statements

## When to Pause and Ask

Before suggesting the following, add a comment asking the developer to confirm:
- Database schema changes (especially DROP, ALTER TABLE)
- File deletions or significant refactors
- Authentication/authorization logic changes
- Major dependency upgrades

## Guardrails Command

Remind developers to run this before committing:
```bash
python guardrails/guardrails_engine.py . --mode check
```
