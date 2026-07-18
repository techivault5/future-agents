#!/usr/bin/env python3
"""
Folder Structure Validator
Enforces standard industry project structures. Detects missing required paths,
wrong file placements, and naming convention violations.
"""
import re
from pathlib import Path
from typing import Optional


# ─────────────────────────────────────────────────────────────────
# STANDARD INDUSTRY STRUCTURES
# ─────────────────────────────────────────────────────────────────

STRUCTURES = {

    "python-service": {
        "detect": ["setup.py", "pyproject.toml", "requirements.txt"],
        "detect_any": True,
        "required": [
            "src/",
            "tests/",
            "docs/",
            ".github/workflows/",
            "Dockerfile",
            ".env.example",
            "README.md",
            "pyproject.toml",
            ".gitignore",
            ".pre-commit-config.yaml",
        ],
        "recommended": [
            "src/{package_name}/__init__.py",
            "tests/unit/",
            "tests/integration/",
            "tests/conftest.py",
            "docs/architecture.md",
            "CHANGELOG.md",
            "CONTRIBUTING.md",
            "Makefile",
            ".dockerignore",
        ],
        "naming_rules": [
            {"pattern": r"^src/[a-z][a-z0-9_]*/$", "applies_to": "src/**/", "description": "Python packages must use snake_case"},
            {"pattern": r"^tests/test_.*\.py$",     "applies_to": "tests/**/*.py", "description": "Test files must start with test_"},
        ],
        "forbidden": [
            "credentials.json",
            "secrets.json",
            ".env",
            "id_rsa",
            "id_ed25519",
        ]
    },

    "node-service": {
        "detect": ["package.json"],
        "detect_any": False,
        "required": [
            "src/",
            "tests/",
            "package.json",
            "tsconfig.json",
            ".env.example",
            "Dockerfile",
            "README.md",
            ".gitignore",
            ".eslintrc.js",
            ".github/workflows/",
        ],
        "recommended": [
            "src/index.ts",
            "src/routes/",
            "src/controllers/",
            "src/services/",
            "src/models/",
            "src/middlewares/",
            "src/config/",
            "src/utils/",
            "tests/unit/",
            "tests/integration/",
            ".prettierrc",
            "jest.config.js",
            "CHANGELOG.md",
            "Makefile",
        ],
        "naming_rules": [
            {"pattern": r"^[a-z][a-zA-Z0-9]*\.(ts|js)$", "applies_to": "src/**/*.ts", "description": "TypeScript files must use camelCase"},
            {"pattern": r"^[a-z][a-z0-9-]*\/$", "applies_to": "src/*/",             "description": "Directories must use kebab-case"},
        ],
        "forbidden": [
            ".env",
            "credentials.json",
            "private.key",
            "*.pem",
        ]
    },

    "fullstack-app": {
        "detect": ["package.json", "next.config.js", "nuxt.config.ts", "vite.config.ts"],
        "detect_any": True,
        "required": [
            "frontend/",
            "backend/",
            "docker-compose.yml",
            "README.md",
            ".gitignore",
            ".env.example",
            "Makefile",
            ".github/workflows/",
        ],
        "recommended": [
            "frontend/src/",
            "frontend/tests/",
            "backend/src/",
            "backend/tests/",
            "docs/",
            "docs/architecture.md",
            "docs/api/",
            "CHANGELOG.md",
            "CONTRIBUTING.md",
            ".dockerignore",
        ],
        "naming_rules": [],
        "forbidden": [".env", "*.pem", "credentials.json"]
    },

    "data-pipeline": {
        "detect": ["dbt_project.yml", "airflow.cfg", "Pipfile", "pyproject.toml"],
        "detect_any": True,
        "required": [
            "dags/",
            "models/",
            "tests/",
            "docs/",
            "config/",
            "README.md",
            ".gitignore",
            ".env.example",
            "requirements.txt",
            ".github/workflows/",
        ],
        "recommended": [
            "dags/utils/",
            "models/staging/",
            "models/marts/",
            "models/intermediate/",
            "tests/unit/",
            "tests/integration/",
            "docs/data-dictionary.md",
            "CHANGELOG.md",
            "Makefile",
        ],
        "naming_rules": [
            {"pattern": r"^[a-z][a-z0-9_]*\.py$",   "applies_to": "dags/**/*.py",    "description": "DAG files must use snake_case"},
            {"pattern": r"^[a-z][a-z0-9_]*\.sql$",  "applies_to": "models/**/*.sql", "description": "dbt models must use snake_case"},
        ],
        "forbidden": [".env", "credentials.json", "*.key", "*.pem"]
    },

    "ml-project": {
        "detect": ["requirements.txt", "environment.yml", "pyproject.toml"],
        "detect_any": True,
        "required": [
            "src/",
            "data/",
            "models/",
            "notebooks/",
            "tests/",
            "configs/",
            "docs/",
            "README.md",
            ".gitignore",
            ".env.example",
            "Dockerfile",
            ".github/workflows/",
        ],
        "recommended": [
            "data/raw/",
            "data/processed/",
            "data/features/",
            "models/trained/",
            "models/evaluation/",
            "notebooks/exploration/",
            "notebooks/experiments/",
            "src/features/",
            "src/models/",
            "src/evaluation/",
            "src/serving/",
            "configs/training.yaml",
            "configs/serving.yaml",
            "docs/model-card.md",
            "docs/data-sheet.md",
            "CHANGELOG.md",
            "Makefile",
        ],
        "naming_rules": [
            {"pattern": r"^\d{4}-\d{2}-\d{2}-.*\.ipynb$", "applies_to": "notebooks/**/*.ipynb",
             "description": "Notebooks must start with YYYY-MM-DD date prefix"},
        ],
        "forbidden": [".env", "credentials.json", "*.key", "data/raw/*.csv"]
    },

    "sqlserver-service": {
        "detect": ["*.csproj", "*.sln"],
        "detect_any": True,
        "required": [
            "src/",
            "tests/",
            "migrations/",
            "docs/",
            ".github/workflows/",
            ".env.example",
            "README.md",
            ".gitignore",
            "docker-compose.yml",
        ],
        "recommended": [
            "src/db/",
            "src/db/migrations/",
            "src/models/",
            "src/repositories/",
            "src/services/",
            "tests/unit/",
            "tests/integration/",
            "scripts/",
            "docs/data-dictionary.md",
            "docs/architecture.md",
            "Dockerfile",
            "CHANGELOG.md",
            "Makefile",
        ],
        "naming_rules": [
            {"pattern": r"^V\d{3}__.*\.sql$", "applies_to": "migrations/**/*.sql",
             "description": "Migration scripts must follow Flyway naming: V001__description.sql"},
        ],
        "forbidden": [
            ".env",
            "credentials.json",
            "appsettings.Production.json",  # secrets belong in KV / env vars
            "*.pfx",
            "*.key",
        ]
    },

    "generic-project": {
        "detect": [],
        "detect_any": True,
        "required": [
            "README.md",
            ".gitignore",
            ".env.example",
        ],
        "recommended": [
            "docs/",
            "CHANGELOG.md",
            "CONTRIBUTING.md",
            ".github/workflows/",
        ],
        "naming_rules": [],
        "forbidden": [".env", "*.pem", "credentials.json"]
    },

    "infra-terraform": {
        "detect": ["main.tf", "variables.tf", "outputs.tf"],
        "detect_any": True,
        "required": [
            "modules/",
            "environments/",
            "main.tf",
            "variables.tf",
            "outputs.tf",
            "versions.tf",
            "README.md",
            ".gitignore",
            ".terraform.lock.hcl",
            ".github/workflows/",
        ],
        "recommended": [
            "environments/dev/",
            "environments/staging/",
            "environments/prod/",
            "modules/networking/",
            "modules/compute/",
            "modules/storage/",
            "docs/architecture.md",
            "CHANGELOG.md",
            "Makefile",
        ],
        "naming_rules": [
            {"pattern": r"^[a-z][a-z0-9_-]*\.tf$", "applies_to": "**/*.tf", "description": "Terraform files must use snake_case or kebab-case"},
        ],
        "forbidden": ["*.tfstate", "*.tfvars", "secrets.auto.tfvars", "terraform.tfvars"]
    },

    "microservice-docker": {
        "detect": ["Dockerfile", "docker-compose.yml"],
        "detect_any": True,
        "required": [
            "Dockerfile",
            "docker-compose.yml",
            "src/",
            "tests/",
            "docs/",
            "README.md",
            ".gitignore",
            ".dockerignore",
            ".env.example",
            ".github/workflows/",
        ],
        "recommended": [
            "docs/api-spec.yaml",
            "docs/architecture.md",
            "CHANGELOG.md",
            "Makefile",
            "healthcheck.sh",
        ],
        "naming_rules": [],
        "forbidden": [".env", "*.pem", "credentials.json"]
    }
}

# ─────────────────────────────────────────────────────────────────

class FolderValidator:
    def __init__(self, config: dict = None):
        cfg = config or {}
        self.extra_structures = cfg.get("extra_structures", {})
        self.check_recommended = cfg.get("check_recommended", False)
        self.project_type = cfg.get("project_type", None)  # Force a specific template
        self.structures = {**STRUCTURES, **self.extra_structures}

    def detect_project_type(self, directory: str) -> Optional[str]:
        if self.project_type:
            return self.project_type

        root = Path(directory)
        for struct_name, struct_def in self.structures.items():
            detect_files = struct_def.get("detect", [])
            if not detect_files:
                continue
            any_match = struct_def.get("detect_any", False)
            matches = [bool((root / f).exists()) for f in detect_files]
            if any_match and any(matches):
                return struct_name
            if not any_match and all(matches):
                return struct_name

        return "generic-project"

    def validate(self, directory: str) -> list:
        findings = []
        root = Path(directory)
        project_type = self.detect_project_type(directory)
        struct = self.structures.get(project_type, self.structures["generic-project"])

        # 1. Check required paths
        for required_path in struct.get("required", []):
            full_path = root / required_path
            if not full_path.exists():
                findings.append({
                    "type": "missing_required",
                    "path": required_path,
                    "project_type": project_type,
                    "can_auto_create": required_path.endswith("/"),  # dirs only
                    "message": f"Required path '{required_path}' missing for {project_type} project"
                })

        # 2. Check recommended paths (warnings only)
        if self.check_recommended:
            for rec_path in struct.get("recommended", []):
                full_path = root / rec_path
                if not full_path.exists():
                    findings.append({
                        "type": "missing_recommended",
                        "path": rec_path,
                        "project_type": project_type,
                        "can_auto_create": rec_path.endswith("/"),
                        "message": f"Recommended path '{rec_path}' missing"
                    })

        # 3. Check naming conventions
        for rule in struct.get("naming_rules", []):
            applies_to = rule.get("applies_to", "**/*")
            pattern = re.compile(rule["pattern"])
            for path in root.rglob(applies_to.replace("**/", "").replace("/*", "")):
                rel = path.relative_to(root)
                name = path.name
                if not pattern.match(name):
                    findings.append({
                        "type": "naming_convention",
                        "path": str(rel),
                        "expected_pattern": rule["pattern"],
                        "description": rule["description"],
                        "message": f"Naming violation: {rel} — {rule['description']}"
                    })

        # 4. Check forbidden files
        for forbidden in struct.get("forbidden", []):
            # Support glob-like patterns
            if "*" in forbidden:
                suffix = forbidden.replace("*", "")
                for path in root.rglob(f"*{suffix}"):
                    if "node_modules" not in str(path) and ".git" not in str(path):
                        findings.append({
                            "type": "forbidden_file",
                            "path": str(path.relative_to(root)),
                            "message": f"Forbidden file '{path.name}' found. "
                                       f"This file type should not be committed.",
                            "severity": "critical"
                        })
            else:
                if (root / forbidden).exists():
                    findings.append({
                        "type": "forbidden_file",
                        "path": forbidden,
                        "message": f"Forbidden file '{forbidden}' found. "
                                   f"This file must not be committed (use .env.example instead).",
                        "severity": "critical"
                    })

        return findings

    def generate_structure(self, project_type: str, project_name: str,
                           output_dir: str, dry_run: bool = False) -> list:
        """Scaffold a new project with the standard structure."""
        struct = self.structures.get(project_type, self.structures["generic-project"])
        created = []
        root = Path(output_dir) / project_name

        all_paths = struct.get("required", []) + struct.get("recommended", [])

        for p in all_paths:
            full = root / p
            if dry_run:
                created.append(str(full))
                continue
            if p.endswith("/"):
                full.mkdir(parents=True, exist_ok=True)
                created.append(str(full))
                # Add .gitkeep to empty dirs
                gitkeep = full / ".gitkeep"
                if not any(full.iterdir()):
                    gitkeep.touch()
            else:
                full.parent.mkdir(parents=True, exist_ok=True)
                if not full.exists():
                    full.touch()
                    created.append(str(full))

        return created
