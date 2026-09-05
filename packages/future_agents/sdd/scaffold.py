"""Repo scaffolding — the structure every repository must have, in any language.

`plan()` computes what is missing without touching disk; `apply()` writes only
the missing entries. Nothing is ever overwritten, and the forbidden files
(`.env`, key material, state files) are never created — the guardrails engine
would reject them and so does this.

The layout comes from `languages.Toolchain`, so a new language gets a correct
scaffold without a line of new scaffolding code.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from future_agents.sdd.languages import GENERIC, RepoProfile, Toolchain, detect_repo, toolchain_for
from future_agents.sdd.personas import DEFAULT_PERSONA, Persona

# Never created by scaffolding, in any language, for any reason.
FORBIDDEN = (
    ".env",
    "credentials.json",
    "secrets.json",
    "id_rsa",
    "id_ed25519",
    "terraform.tfvars",
)

_BASE_GITIGNORE = """# Secrets — never commit
.env
*.pem
*.key
credentials.json
secrets.json

# Build output and caches
dist/
build/
coverage/
*.log
.DS_Store
"""

_LANG_GITIGNORE = {
    "python": "__pycache__/\n*.pyc\n.venv/\n.pytest_cache/\n.mypy_cache/\n*.egg-info/\n",
    "typescript": "node_modules/\n.next/\n*.tsbuildinfo\n",
    "javascript": "node_modules/\n.next/\n",
    "go": "bin/\nvendor/\n",
    "rust": "target/\n",
    "java": "target/\n.gradle/\n*.class\n",
    "kotlin": "build/\n.gradle/\n",
    "csharp": "bin/\nobj/\n",
    "ruby": ".bundle/\nvendor/bundle/\n",
    "php": "vendor/\n",
    "swift": ".build/\n",
    "cpp": "build/\n*.o\n*.so\n",
    "scala": "target/\n.bloop/\n.metals/\n",
    "elixir": "_build/\ndeps/\n",
    "dart": ".dart_tool/\nbuild/\n",
    "terraform": "*.tfstate\n*.tfstate.*\n.terraform/\n*.tfvars\n",
    "sql": "target/\ndbt_packages/\nlogs/\n",
}


class ScaffoldAction(BaseModel):
    path: str
    kind: str  # dir | file
    action: str  # create | exists
    purpose: str = ""
    required: bool = True
    content: str = ""


class ScaffoldPlan(BaseModel):
    root: str
    language: str
    persona: str = ""
    actions: list[ScaffoldAction] = Field(default_factory=list)

    @property
    def missing(self) -> list[ScaffoldAction]:
        return [a for a in self.actions if a.action == "create"]

    @property
    def missing_required(self) -> list[ScaffoldAction]:
        return [a for a in self.missing if a.required]

    def summary(self) -> str:
        return (
            f"{self.language}: {len(self.missing)} to create, "
            f"{len(self.actions) - len(self.missing)} already present"
        )


class RepoScaffolder:
    """Computes and applies the required structure for a repository."""

    def __init__(self, persona: Optional[Persona] = None) -> None:
        self.persona = persona or DEFAULT_PERSONA

    def plan(
        self,
        root: str | Path,
        profile: Optional[RepoProfile] = None,
        language: Optional[str] = None,
        name: str = "",
        description: str = "",
    ) -> ScaffoldPlan:
        root_path = Path(root)
        if language:
            chain = toolchain_for(language) or GENERIC
            detected = profile or RepoProfile(root=str(root_path), primary_language=chain.language)
        else:
            detected = profile or detect_repo(root_path)
            chain = detected.toolchain()

        repo_name = name or root_path.resolve().name
        actions: list[ScaffoldAction] = []
        seen: set[str] = set()

        def add(
            path: str, kind: str, purpose: str, content: str = "", required: bool = True
        ) -> None:
            if path in seen or Path(path).name in FORBIDDEN:
                return
            seen.add(path)
            exists = _satisfied(root_path, path, purpose)
            actions.append(
                ScaffoldAction(
                    path=path,
                    kind=kind,
                    action="exists" if exists else "create",
                    purpose=purpose,
                    required=required,
                    content="" if exists else content,
                )
            )

        for entry in chain.layout:
            content = (
                entry.template.format(
                    name=repo_name,
                    description=description or f"{chain.display_name} service.",
                    install=chain.install or "# install",
                    test=chain.test or "# test",
                )
                if entry.template
                else _file_content(entry.path, repo_name, description, chain)
            )
            add(entry.path, entry.kind, entry.purpose, content, entry.required)

        # A repo with no manifest is a new repo: give it a minimal, correct one.
        if chain.manifest_file and chain.manifest_template:
            add(
                chain.manifest_file,
                "file",
                f"{chain.package_manager or chain.display_name} manifest",
                chain.manifest_template.format(name=_safe_name(repo_name)),
            )

        # Universal governance surface, whatever the language.
        add(
            "README.md",
            "file",
            "what this is, how to run it",
            _readme(repo_name, description, chain),
        )
        add(".gitignore", "file", "never commit secrets or build output", _gitignore(chain))
        add(".env.example", "file", "every env var with REPLACE_ME placeholders", _env_example())
        add(
            "docs/architecture.md",
            "file",
            "the shape of the system",
            _architecture(repo_name, chain),
        )
        add(
            "docs/runbook.md",
            "file",
            "what breaks, how you see it, how you undo it",
            _runbook(repo_name, chain),
        )
        add(
            "docs/adr/0001-record-architecture-decisions.md",
            "file",
            "decisions that would be expensive to reverse",
            _adr(),
        )
        add(
            ".github/workflows/ci.yml",
            "file",
            "lint → test → guardrails, the golden topology",
            _ci_workflow(repo_name, chain),
        )
        for extra in _polyglot_extras(detected, chain):
            add(
                f".github/workflows/ci-{extra.language}.yml",
                "file",
                f"secondary toolchain: {extra.display_name}",
                _ci_workflow(f"{repo_name}-{extra.language}", extra),
                required=False,
            )

        return ScaffoldPlan(
            root=str(root_path),
            language=chain.language,
            persona=self.persona.id,
            actions=actions,
        )

    def apply(self, plan: ScaffoldPlan, dry_run: bool = True) -> list[str]:
        """Create only what is missing. Returns the paths written."""
        written: list[str] = []
        root = Path(plan.root)
        for action in plan.missing:
            target = root / action.path
            if dry_run:
                written.append(action.path)
                continue
            if action.kind == "dir":
                target.mkdir(parents=True, exist_ok=True)
                gitkeep = target / ".gitkeep"
                if not any(target.iterdir()):
                    gitkeep.write_text("")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(action.content or "")
            written.append(action.path)
        return written

    def validate(self, root: str | Path, profile: Optional[RepoProfile] = None) -> list[str]:
        """Required entries a repository is missing — the structure gate."""
        return [a.path for a in self.plan(root, profile=profile).missing_required]


# A monorepo keeps its source under packages/ or apps/, not src/. Treat any
# conventional root as satisfying the requirement rather than littering the repo.
_ALIASES = {
    "source": ("src", "lib", "packages", "apps", "internal", "cmd", "Sources", "app", "R"),
    "test suite": ("tests", "test", "spec", "__tests__", "Tests"),
}


def _satisfied(root: Path, path: str, purpose: str) -> bool:
    if (root / path).exists():
        return True
    aliases = _ALIASES.get(purpose, ())
    if not aliases or "/" in path:
        return False
    return any((root / alias).is_dir() for alias in aliases)


# ── Content ───────────────────────────────────────────────────────────────────


def _safe_name(name: str) -> str:
    """Manifest-safe project name — module paths and package names are picky."""
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name).strip("-_")
    return cleaned.lower() or "project"


def _polyglot_extras(profile: RepoProfile, primary: Toolchain) -> list[Toolchain]:
    extras: list[Toolchain] = []
    for signal in profile.languages:
        if signal.language == primary.language or signal.score < 50:
            continue
        chain = toolchain_for(signal.language)
        if chain and chain.test:
            extras.append(chain)
    return extras[:3]


def _file_content(path: str, name: str, description: str, chain: Toolchain) -> str:
    if path.endswith(".gitignore"):
        return _gitignore(chain)
    if path.endswith("README.md"):
        return _readme(name, description, chain)
    if path.endswith(".env.example"):
        return _env_example()
    if path.endswith("data-dictionary.md"):
        return (
            "# Data dictionary\n\n"
            "| Model | Column | Type | Meaning | Source |\n|---|---|---|---|---|\n"
        )
    if path.endswith("versions.tf"):
        return (
            'terraform {\n  required_version = "~> 1.7"\n  required_providers {\n'
            "    # pin every provider here, exactly\n  }\n}\n"
        )
    if path.endswith("tsconfig.json"):
        return '{\n  "compilerOptions": {\n    "strict": true,\n    "target": "ES2022"\n  }\n}\n'
    return ""


def _readme(name: str, description: str, chain: Toolchain) -> str:
    commands = "\n".join(f"{cmd}" for cmd in chain.commands().values()) or "# no toolchain detected"
    return f"""# {name}

{description or f"A {chain.display_name} project."}

## Run

```bash
{commands}
```

## Layout

{chr(10).join(f"- `{e.path}` — {e.purpose}" for e in chain.layout if e.purpose)}

## Conventions

- Secrets come from the environment or a secrets manager. `.env` is never committed;
  `.env.example` always is, with `REPLACE_ME` placeholders.
- Dependencies use {chain.pin_style or "the ecosystem default"} ranges: {chain.pin_rule}
- Every change ships with a test and a line in `docs/runbook.md` if it can break in production.
"""


def _gitignore(chain: Toolchain) -> str:
    extra = _LANG_GITIGNORE.get(chain.language, "")
    return _BASE_GITIGNORE + (f"\n# {chain.display_name}\n{extra}" if extra else "")


def _env_example() -> str:
    return (
        "# Copy to .env (gitignored) and fill in real values.\n"
        "# Every variable the app reads must appear here.\n"
        "# EXAMPLE_API_KEY=REPLACE_ME\n"
        "# DATABASE_URL=REPLACE_ME\n"
    )


def _architecture(name: str, chain: Toolchain) -> str:
    return f"""# {name} — architecture

## Context

What problem this system solves, and for whom.

## Shape

| Component | Responsibility | Owns |
|---|---|---|
| | | |

## Runtime

- Language/toolchain: {chain.display_name}
- Test: `{chain.test or "—"}`
- Build: `{chain.build or "—"}`

## Boundaries

- Trust boundary: where untrusted input enters and how it is validated.
- Data boundary: what leaves this system, and to whom.

## Decisions

Recorded as ADRs in `docs/adr/`.
"""


def _runbook(name: str, chain: Toolchain) -> str:
    return f"""# {name} — runbook

## How you know it is broken

| Signal | Where | Threshold |
|---|---|---|
| | | |

## First response

1. Check the dashboard / logs.
2. Identify the last deploy or flag change.
3. Roll back: (flag flip / previous release / migration down).

## Recovery

Steps that restore service, in order, with the command to run.

## Verify

`{chain.test or "the test suite"}` passes and the signal above is back in range.
"""


def _adr() -> str:
    return """# ADR 0001 — Record architecture decisions

## Status

Accepted

## Context

Decisions that are expensive to reverse need a written reason, or the next
engineer re-litigates them from scratch.

## Decision

Every such decision gets a numbered file in `docs/adr/`: context, decision,
consequences. Superseded ADRs stay, marked superseded.

## Consequences

Slightly more writing now; far less archaeology later.
"""


def _ci_workflow(name: str, chain: Toolchain) -> str:
    """Golden topology: lint → test → guardrails, jobs wired with `needs`."""
    install = f"      - run: {chain.install}\n" if chain.install else ""
    lint = chain.lint or "echo 'no linter configured'"
    test = chain.test or "echo 'no test command configured'"
    return f"""name: {name} ci

on:
  push:
    branches: [main]
  pull_request:

jobs:
  lint:
    runs-on: {chain.ci_image}
    steps:
      - uses: actions/checkout@v4
{install}      - run: {lint}

  test:
    needs: lint
    runs-on: {chain.ci_image}
    steps:
      - uses: actions/checkout@v4
{install}      - run: {test}

  guardrails:
    needs: test
    runs-on: {chain.ci_image}
    steps:
      - uses: actions/checkout@v4
      - run: echo 'wire the guardrails engine here'
"""
