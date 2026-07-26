# /pr-guardian — Auto-resolve, fix, and merge open PRs

Run `scripts/pr_guardian.py` to process all open PRs:
- **Dirty (merge conflicts)** → merge main in, resolve conflicts, fix lint, push
- **Blocked (lint failing)** → run ruff --fix + format, push  
- **Clean + all green** → merge automatically

## Usage

```
/pr-guardian
```

## What Claude should do when this skill is invoked

1. Run: `python scripts/pr_guardian.py`
2. Report results per PR (conflicts resolved / lint fixed / merged / skipped)
3. If any PR was pushed, confirm CI is running via GitHub MCP check_runs

## GitHub Actions automation

The workflow `.github/workflows/pr-guardian.yml` runs automatically:
- Every 20 minutes (cron)
- On every PR event (opened, synchronize, reopened)
- On check_run completion
- On workflow_dispatch (manual trigger)

Optional: add `ANTHROPIC_API_KEY` as a repo secret for AI-powered conflict
resolution on complex merge conflicts that the regex resolver can't handle.
