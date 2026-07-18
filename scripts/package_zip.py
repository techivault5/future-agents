#!/usr/bin/env python3
"""
Package the entire IT Agents Guardrails system as a downloadable ZIP.
Generates all 10,000 agents first, then zips everything.
"""
import os
import sys
import zipfile
import subprocess
from pathlib import Path
from datetime import datetime


EXCLUDE_PATTERNS = {
    "__pycache__", ".pytest_cache", ".git", "*.pyc", "*.pyo",
    ".DS_Store", "Thumbs.db", "*.egg-info", ".guardrails-report.json",
    ".guardrails-human-log.jsonl", "node_modules", ".venv", "venv"
}


def should_exclude(path: Path) -> bool:
    parts = set(path.parts)
    for pattern in EXCLUDE_PATTERNS:
        if "*" in pattern:
            suffix = pattern.replace("*", "")
            if path.name.endswith(suffix):
                return True
        elif pattern in parts or path.name == pattern:
            return True
    return False


def generate_agents(root: Path):
    """Run the agent generator script."""
    print("Generating 10,000 IT agents...")
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "generate_agents.py")],
        cwd=str(root),
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        print(f"Agent generation failed: {result.stderr}")
        return False
    print(result.stdout)
    return True


def create_zip(root: Path, output_path: Path):
    """Create ZIP archive of the entire project."""
    print(f"Creating ZIP archive at {output_path}...")
    count = 0

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file_path in root.rglob("*"):
            if file_path.is_file() and not should_exclude(file_path):
                arcname = file_path.relative_to(root.parent)
                zf.write(file_path, arcname)
                count += 1
                if count % 500 == 0:
                    print(f"  Archived {count} files...")

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"\nZIP created: {output_path}")
    print(f"  Files: {count}")
    print(f"  Size:  {size_mb:.1f} MB")
    return count


def create_manifest(root: Path, zip_path: Path):
    """Write a manifest file describing the ZIP contents."""
    manifest = f"""# IT Agents Guardrails — Package Manifest
Generated: {datetime.utcnow().isoformat()}Z
ZIP File: {zip_path.name}

## Contents

### Agents (10,000 IT role definitions)
- agents/technical/    — 5,500+ technical role agents
- agents/non-technical/ — 4,500+ non-technical role agents
- agents/agents_index.json — searchable index of all agents

### Guardrails Engine
- guardrails/guardrails_engine.py  — Main orchestrator
- guardrails/secrets_scanner.py    — Secret detection
- guardrails/package_manager.py    — Package policy enforcement
- guardrails/folder_validator.py   — Structure validation
- guardrails/human_input_handler.py — Human escalation flows

### Skills
- skills/combined_guardrails.yaml  — Master guardrails skill definitions

### Configuration
- config/guardrails_config.yaml    — Runtime configuration
- config/connective_config.yaml    — Component wiring & integrations

### Templates
- templates/agent-templates/agent_template.yaml
- templates/skill-templates/skill_template.yaml
- templates/project-structures/python-service/
- templates/project-structures/node-service/
- templates/project-structures/ml-project/
- templates/ci/github-actions-guardrails.yml
- templates/ci/gitlab-ci-guardrails.yml
- templates/ci/pre-commit-guardrails.yaml

### Scripts
- scripts/generate_agents.py  — Regenerate all agents
- scripts/package_zip.py      — Rebuild this ZIP

## Quick Start

```bash
# 1. Install dependencies
pip install pyyaml packaging

# 2. Run guardrails check on your project
python guardrails/guardrails_engine.py /path/to/your/project --mode check

# 3. Auto-fix folder structure issues
python guardrails/guardrails_engine.py /path/to/your/project --mode fix

# 4. Block on violations (use in CI)
python guardrails/guardrails_engine.py /path/to/your/project --mode block

# 5. Scaffold a new project
python -c "
from guardrails.folder_validator import FolderValidator
fv = FolderValidator()
fv.generate_structure('python-service', 'my-new-service', '.')
"
```
"""
    manifest_path = root.parent / "IT-AGENTS-GUARDRAILS-MANIFEST.md"
    manifest_path.write_text(manifest)
    print(f"Manifest written to {manifest_path}")


if __name__ == "__main__":
    root = Path(__file__).parent.parent.resolve()
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    zip_name = f"it-agents-guardrails-{timestamp}.zip"
    zip_path = root.parent / zip_name

    print("=" * 60)
    print("IT Agents Guardrails — Package Builder")
    print("=" * 60)

    # Step 1: Generate agents
    if "--skip-generate" not in sys.argv:
        ok = generate_agents(root)
        if not ok:
            print("Continuing without full agent generation...")

    # Step 2: Create ZIP
    count = create_zip(root, zip_path)

    # Step 3: Manifest
    create_manifest(root, zip_path)

    print(f"\n{'=' * 60}")
    print(f"  DONE! Your downloadable ZIP is ready:")
    print(f"  {zip_path}")
    print(f"  {count} files packaged")
    print(f"{'=' * 60}\n")
