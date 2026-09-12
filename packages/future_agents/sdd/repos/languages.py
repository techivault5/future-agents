"""Language and toolchain matrix — the pipeline works on any repo.

A repo is detected from its manifests and file extensions, never assumed. Each
language carries the commands a contributor actually runs (install, test, lint,
format, typecheck, build, audit), the layout its ecosystem expects, and the
dependency-pinning style the guardrails enforce for it.

Adding a language is one `Toolchain` entry — nothing else in the pipeline
changes, because every stage reads commands from here rather than hard-coding
`pytest`.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Iterable, Optional

from pydantic import BaseModel, Field

# Directories that never say anything about what a repo is written in.
IGNORED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "vendor",
        "target",
        "build",
        "dist",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".tox",
        ".gradle",
        ".idea",
        ".vscode",
        "bin",
        "obj",
        "Pods",
        ".terraform",
        "coverage",
        ".next",
        ".nuxt",
        ".svelte-kit",
        "site-packages",
        ".cache",
    }
)


class LayoutEntry(BaseModel):
    """One directory or file a conforming repo of this kind must have."""

    path: str
    kind: str = "dir"  # dir | file
    purpose: str = ""
    template: str = ""  # starter content for files
    required: bool = True


class Toolchain(BaseModel):
    """Everything the pipeline needs to work in one language."""

    language: str
    display_name: str
    manifests: tuple[str, ...] = ()  # presence proves the language
    extensions: tuple[str, ...] = ()
    package_manager: str = ""
    install: str = ""
    test: str = ""
    lint: str = ""
    format: str = ""
    typecheck: str = ""
    build: str = ""
    audit: str = ""
    run: str = ""
    # Guardrails: how dependencies must be ranged in this ecosystem.
    pin_style: str = ""
    pin_rule: str = ""
    test_glob: str = ""
    layout: tuple[LayoutEntry, ...] = ()
    # Starter manifest written only when a repo has none — `{name}` is the repo.
    manifest_file: str = ""
    manifest_template: str = ""
    ci_image: str = "ubuntu-latest"
    notes: str = ""

    def commands(self) -> dict[str, str]:
        """Non-empty commands, in the order a contributor runs them."""
        ordered = [
            ("install", self.install),
            ("format", self.format),
            ("lint", self.lint),
            ("typecheck", self.typecheck),
            ("test", self.test),
            ("build", self.build),
            ("audit", self.audit),
        ]
        return {name: cmd for name, cmd in ordered if cmd}


def _common(src: str, tests: str, test_purpose: str = "test suite") -> tuple[LayoutEntry, ...]:
    return (
        LayoutEntry(path=src, purpose="source"),
        LayoutEntry(path=tests, purpose=test_purpose),
        LayoutEntry(path="docs", purpose="architecture notes and runbooks"),
        LayoutEntry(
            path="README.md",
            kind="file",
            purpose="what this is, how to run it",
            template="# {name}\n\n{description}\n\n## Run\n\n```bash\n{install}\n{test}\n```\n",
        ),
        LayoutEntry(
            path=".env.example",
            kind="file",
            purpose="every env var, with REPLACE_ME placeholders — never .env",
            template="# Copy to .env (gitignored) and fill in.\n# EXAMPLE_API_KEY=REPLACE_ME\n",
        ),
        LayoutEntry(path=".gitignore", kind="file", purpose="never commit secrets or build output"),
    )


TOOLCHAINS: tuple[Toolchain, ...] = (
    Toolchain(
        language="python",
        manifest_file="pyproject.toml",
        manifest_template="""[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "{name}"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=7.0", "ruff~=0.16.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
""",
        display_name="Python",
        manifests=("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile"),
        extensions=(".py", ".pyi"),
        package_manager="pip",
        install="pip install -e '.[dev]'",
        test="pytest -q",
        lint="ruff check .",
        format="ruff format .",
        typecheck="mypy .",
        build="python -m build",
        audit="pip-audit",
        run="python -m {module}",
        pin_style="~=",
        pin_rule="compatible-release ranges; exact pins only for build tooling",
        test_glob="tests/test_*.py",
        layout=_common("src", "tests")
        + (
            LayoutEntry(path="tests/unit", required=False),
            LayoutEntry(path="tests/integration", required=False),
        ),
    ),
    Toolchain(
        language="typescript",
        manifest_file="package.json",
        manifest_template="""{{
  "name": "{name}",
  "version": "0.1.0",
  "private": true,
  "scripts": {{
    "build": "tsc -p .",
    "test": "node --test",
    "lint": "eslint .",
    "format": "prettier --write ."
  }},
  "devDependencies": {{
    "typescript": "^5.4.0"
  }}
}}
""",
        display_name="TypeScript",
        manifests=("tsconfig.json",),
        extensions=(".ts", ".tsx"),
        package_manager="npm",
        install="npm ci",
        test="npm test",
        lint="npm run lint",
        format="npm run format",
        typecheck="tsc --noEmit",
        build="npm run build",
        audit="npm audit --omit=dev",
        pin_style="^",
        pin_rule="caret ranges in package.json; lockfile committed",
        test_glob="tests/**/*.test.ts",
        layout=_common("src", "tests")
        + (
            LayoutEntry(path="src/routes", required=False),
            LayoutEntry(path="src/services", required=False),
            LayoutEntry(path="tsconfig.json", kind="file", purpose="strict mode on"),
        ),
    ),
    Toolchain(
        language="javascript",
        manifest_file="package.json",
        manifest_template="""{{
  "name": "{name}",
  "version": "0.1.0",
  "private": true,
  "scripts": {{
    "test": "node --test",
    "lint": "eslint ."
  }}
}}
""",
        display_name="JavaScript",
        manifests=("package.json",),
        extensions=(".js", ".jsx", ".mjs", ".cjs"),
        package_manager="npm",
        install="npm ci",
        test="npm test",
        lint="npx eslint .",
        format="npx prettier --write .",
        build="npm run build",
        audit="npm audit --omit=dev",
        pin_style="^",
        pin_rule="caret ranges in package.json; lockfile committed",
        test_glob="tests/**/*.test.js",
        layout=_common("src", "tests"),
    ),
    Toolchain(
        language="go",
        manifest_file="go.mod",
        manifest_template="""module example.com/{name}

go 1.22
""",
        display_name="Go",
        manifests=("go.mod",),
        extensions=(".go",),
        package_manager="go modules",
        install="go mod download",
        test="go test ./...",
        lint="golangci-lint run",
        format="gofmt -l -w .",
        build="go build ./...",
        audit="govulncheck ./...",
        pin_style="exact",
        pin_rule="go.mod pins exactly by design; keep go.sum committed",
        test_glob="**/*_test.go",
        layout=_common("internal", "internal") + (LayoutEntry(path="cmd", purpose="entrypoints"),),
        notes="Test files live beside the code; the tests/ dir is optional.",
    ),
    Toolchain(
        language="rust",
        manifest_file="Cargo.toml",
        manifest_template="""[package]
name = "{name}"
version = "0.1.0"
edition = "2021"

[dependencies]
""",
        display_name="Rust",
        manifests=("Cargo.toml",),
        extensions=(".rs",),
        package_manager="cargo",
        install="cargo fetch",
        test="cargo test",
        lint="cargo clippy -- -D warnings",
        format="cargo fmt --all",
        build="cargo build --release",
        audit="cargo audit",
        pin_style="^",
        pin_rule="caret by default in Cargo.toml; Cargo.lock committed for binaries",
        test_glob="tests/*.rs",
        layout=_common("src", "tests"),
    ),
    Toolchain(
        language="java",
        manifest_file="pom.xml",
        manifest_template="""<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>{name}</artifactId>
  <version>0.1.0</version>
  <properties>
    <maven.compiler.release>21</maven.compiler.release>
  </properties>
</project>
""",
        display_name="Java",
        manifests=("pom.xml", "build.gradle", "build.gradle.kts"),
        extensions=(".java",),
        package_manager="maven",
        install="mvn -B dependency:go-offline",
        test="mvn -B test",
        lint="mvn -B checkstyle:check",
        format="mvn -B spotless:apply",
        build="mvn -B package",
        audit="mvn -B org.owasp:dependency-check-maven:check",
        pin_style="exact",
        pin_rule="exact versions are correct in pom.xml; never <version>LATEST</version>",
        test_glob="src/test/java/**/*Test.java",
        layout=(
            LayoutEntry(path="src/main/java", purpose="source"),
            LayoutEntry(path="src/test/java", purpose="test suite"),
            LayoutEntry(path="src/main/resources", purpose="config"),
            LayoutEntry(path="docs", purpose="architecture notes and runbooks"),
            LayoutEntry(path="README.md", kind="file"),
            LayoutEntry(path=".env.example", kind="file"),
            LayoutEntry(path=".gitignore", kind="file"),
        ),
    ),
    Toolchain(
        language="kotlin",
        manifest_file="build.gradle.kts",
        manifest_template="""plugins {{
    kotlin("jvm") version "2.0.0"
}}

repositories {{ mavenCentral() }}

dependencies {{
    testImplementation(kotlin("test"))
}}
""",
        display_name="Kotlin",
        manifests=("build.gradle.kts", "settings.gradle.kts"),
        extensions=(".kt", ".kts"),
        package_manager="gradle",
        install="./gradlew dependencies",
        test="./gradlew test",
        lint="./gradlew ktlintCheck",
        format="./gradlew ktlintFormat",
        build="./gradlew build",
        pin_style="exact",
        pin_rule="version catalog (libs.versions.toml) is the single place versions live",
        test_glob="src/test/kotlin/**/*Test.kt",
        layout=(
            LayoutEntry(path="src/main/kotlin", purpose="source"),
            LayoutEntry(path="src/test/kotlin", purpose="test suite"),
            LayoutEntry(path="docs"),
            LayoutEntry(path="README.md", kind="file"),
            LayoutEntry(path=".gitignore", kind="file"),
        ),
    ),
    Toolchain(
        language="csharp",
        display_name="C#/.NET",
        manifests=("*.csproj", "*.sln", "Directory.Build.props"),
        extensions=(".cs",),
        package_manager="nuget",
        install="dotnet restore",
        test="dotnet test",
        lint="dotnet format --verify-no-changes",
        format="dotnet format",
        build="dotnet build -c Release",
        audit="dotnet list package --vulnerable",
        pin_style="exact",
        pin_rule="PackageReference pins exactly; centralise in Directory.Packages.props",
        test_glob="tests/**/*Tests.cs",
        layout=_common("src", "tests"),
    ),
    Toolchain(
        language="ruby",
        manifest_file="Gemfile",
        manifest_template="""source "https://rubygems.org"

gem "rspec", "~> 3.13"
""",
        display_name="Ruby",
        manifests=("Gemfile", "*.gemspec"),
        extensions=(".rb",),
        package_manager="bundler",
        install="bundle install",
        test="bundle exec rspec",
        lint="bundle exec rubocop",
        format="bundle exec rubocop -a",
        audit="bundle audit check --update",
        pin_style="~>",
        pin_rule="pessimistic constraint (~>) in the Gemfile; Gemfile.lock committed",
        test_glob="spec/**/*_spec.rb",
        layout=_common("lib", "spec"),
    ),
    Toolchain(
        language="php",
        manifest_file="composer.json",
        manifest_template="""{{
  "name": "example/{name}",
  "require": {{}},
  "require-dev": {{
    "phpunit/phpunit": "^11.0"
  }}
}}
""",
        display_name="PHP",
        manifests=("composer.json",),
        extensions=(".php",),
        package_manager="composer",
        install="composer install",
        test="./vendor/bin/phpunit",
        lint="./vendor/bin/phpcs",
        format="./vendor/bin/php-cs-fixer fix",
        typecheck="./vendor/bin/phpstan analyse",
        audit="composer audit",
        pin_style="^",
        pin_rule="caret ranges in composer.json; composer.lock committed",
        test_glob="tests/**/*Test.php",
        layout=_common("src", "tests"),
    ),
    Toolchain(
        language="swift",
        manifest_file="Package.swift",
        manifest_template="""// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "{name}",
    targets: [
        .target(name: "{name}"),
        .testTarget(name: "{name}Tests", dependencies: ["{name}"]),
    ]
)
""",
        display_name="Swift",
        manifests=("Package.swift",),
        extensions=(".swift",),
        package_manager="swiftpm",
        install="swift package resolve",
        test="swift test",
        lint="swiftlint",
        format="swift-format format -i -r Sources",
        build="swift build -c release",
        pin_style="from:",
        pin_rule="`.upToNextMajor(from:)` in Package.swift; Package.resolved committed",
        test_glob="Tests/**/*Tests.swift",
        layout=(
            LayoutEntry(path="Sources", purpose="source"),
            LayoutEntry(path="Tests", purpose="test suite"),
            LayoutEntry(path="docs"),
            LayoutEntry(path="README.md", kind="file"),
            LayoutEntry(path=".gitignore", kind="file"),
        ),
    ),
    Toolchain(
        language="cpp",
        manifest_file="CMakeLists.txt",
        manifest_template="""cmake_minimum_required(VERSION 3.20)
project({name} CXX)

set(CMAKE_CXX_STANDARD 20)
enable_testing()
add_subdirectory(src)
""",
        display_name="C/C++",
        manifests=("CMakeLists.txt", "meson.build", "conanfile.txt", "vcpkg.json"),
        extensions=(".c", ".h", ".cc", ".cpp", ".hpp", ".cxx"),
        package_manager="cmake/conan",
        install="cmake -S . -B build",
        test="ctest --test-dir build --output-on-failure",
        lint="clang-tidy -p build",
        format="clang-format -i $(git ls-files '*.c' '*.h' '*.cpp' '*.hpp')",
        build="cmake --build build -j",
        pin_style="exact",
        pin_rule="pin dependency versions in conanfile/vcpkg.json; commit the lockfile",
        test_glob="tests/**/*.cpp",
        layout=_common("src", "tests") + (LayoutEntry(path="include", purpose="public headers"),),
    ),
    Toolchain(
        language="scala",
        manifest_file="build.sbt",
        manifest_template="""name := "{name}"
version := "0.1.0"
scalaVersion := "3.4.2"

libraryDependencies += "org.scalatest" %% "scalatest" % "3.2.19" % Test
""",
        display_name="Scala",
        manifests=("build.sbt",),
        extensions=(".scala",),
        package_manager="sbt",
        install="sbt update",
        test="sbt test",
        lint="sbt scalafixAll --check",
        format="sbt scalafmtAll",
        build="sbt assembly",
        pin_style="exact",
        pin_rule="exact versions in build.sbt; centralise in Dependencies.scala",
        test_glob="src/test/scala/**/*Spec.scala",
        layout=(
            LayoutEntry(path="src/main/scala", purpose="source"),
            LayoutEntry(path="src/test/scala", purpose="test suite"),
            LayoutEntry(path="docs"),
            LayoutEntry(path="README.md", kind="file"),
        ),
    ),
    Toolchain(
        language="elixir",
        manifest_file="mix.exs",
        manifest_template="""defmodule {name}.MixProject do
  use Mix.Project

  def project do
    [app: :{name}, version: "0.1.0", elixir: "~> 1.16", deps: deps()]
  end

  defp deps, do: []
end
""",
        display_name="Elixir",
        manifests=("mix.exs",),
        extensions=(".ex", ".exs"),
        package_manager="hex",
        install="mix deps.get",
        test="mix test",
        lint="mix credo --strict",
        format="mix format",
        typecheck="mix dialyzer",
        audit="mix deps.audit",
        pin_style="~>",
        pin_rule="`~>` in mix.exs; mix.lock committed",
        test_glob="test/**/*_test.exs",
        layout=_common("lib", "test"),
    ),
    Toolchain(
        language="dart",
        manifest_file="pubspec.yaml",
        manifest_template="""name: {name}
environment:
  sdk: ^3.4.0
dev_dependencies:
  test: ^1.25.0
""",
        display_name="Dart/Flutter",
        manifests=("pubspec.yaml",),
        extensions=(".dart",),
        package_manager="pub",
        install="dart pub get",
        test="dart test",
        lint="dart analyze",
        format="dart format .",
        build="flutter build apk",
        pin_style="^",
        pin_rule="caret ranges in pubspec.yaml; pubspec.lock committed for apps",
        test_glob="test/**/*_test.dart",
        layout=_common("lib", "test"),
    ),
    Toolchain(
        language="r",
        display_name="R",
        manifests=("DESCRIPTION", "renv.lock"),
        extensions=(".R", ".r", ".Rmd"),
        package_manager="renv",
        install="Rscript -e 'renv::restore()'",
        test="Rscript -e 'testthat::test_dir(\"tests\")'",
        lint="Rscript -e 'lintr::lint_dir()'",
        format="Rscript -e 'styler::style_dir()'",
        pin_style="renv.lock",
        pin_rule="renv.lock is the pin; commit it",
        test_glob="tests/testthat/test-*.R",
        layout=_common("R", "tests"),
    ),
    Toolchain(
        language="sql",
        manifest_file="dbt_project.yml",
        manifest_template="""name: "{name}"
version: "0.1.0"
profile: "{name}"
model-paths: ["models"]
test-paths: ["tests"]
""",
        display_name="SQL/dbt",
        manifests=("dbt_project.yml",),
        extensions=(".sql",),
        package_manager="dbt",
        install="dbt deps",
        test="dbt test",
        lint="sqlfluff lint .",
        format="sqlfluff fix .",
        build="dbt build",
        pin_style="range",
        pin_rule="version ranges in packages.yml; package-lock.yml committed",
        test_glob="tests/**/*.sql",
        layout=(
            LayoutEntry(path="models/staging", purpose="raw-shaped models"),
            LayoutEntry(path="models/marts", purpose="business models"),
            LayoutEntry(path="tests", purpose="data tests"),
            LayoutEntry(path="docs/data-dictionary.md", kind="file"),
            LayoutEntry(path="README.md", kind="file"),
        ),
    ),
    Toolchain(
        language="terraform",
        display_name="Terraform/IaC",
        manifests=("main.tf", "versions.tf", "*.tf"),
        extensions=(".tf", ".tfvars"),
        package_manager="terraform",
        install="terraform init -backend=false",
        test="terraform validate",
        lint="tflint",
        format="terraform fmt -recursive",
        build="terraform plan",
        audit="tfsec .",
        pin_style="exact",
        pin_rule="pin provider versions exactly in versions.tf; commit .terraform.lock.hcl",
        test_glob="tests/**/*.tftest.hcl",
        layout=(
            LayoutEntry(path="modules", purpose="reusable modules"),
            LayoutEntry(path="environments/dev"),
            LayoutEntry(path="environments/prod"),
            LayoutEntry(path="versions.tf", kind="file", purpose="provider pins live here"),
            LayoutEntry(path="README.md", kind="file"),
        ),
        notes="State files and *.tfvars are never committed.",
    ),
    Toolchain(
        language="shell",
        display_name="Shell",
        manifests=(),
        extensions=(".sh", ".bash", ".zsh"),
        package_manager="",
        test="bats tests",
        lint="shellcheck $(git ls-files '*.sh')",
        format="shfmt -w .",
        pin_style="n/a",
        pin_rule="pin tool versions in the container image, not in the script",
        test_glob="tests/*.bats",
        layout=_common("scripts", "tests"),
    ),
)

BY_LANGUAGE: dict[str, Toolchain] = {t.language: t for t in TOOLCHAINS}

GENERIC = Toolchain(
    language="unknown",
    display_name="Unrecognised",
    test="",
    pin_style="",
    pin_rule="pin as the ecosystem expects; commit the lockfile",
    layout=_common("src", "tests"),
    notes="No manifest matched. Set the language explicitly in the repo config.",
)


class LanguageSignal(BaseModel):
    language: str
    files: int = 0
    manifests: list[str] = Field(default_factory=list)
    score: float = 0.0


class RepoProfile(BaseModel):
    """What a repository is, decided from evidence on disk."""

    root: str
    primary_language: str = "unknown"
    languages: list[LanguageSignal] = Field(default_factory=list)
    monorepo: bool = False
    has_ci: bool = False
    has_tests: bool = False
    has_containerfile: bool = False

    def toolchain(self) -> Toolchain:
        return BY_LANGUAGE.get(self.primary_language, GENERIC)

    def toolchains(self) -> list[Toolchain]:
        """Every detected language, primary first — a polyglot repo needs them all."""
        seen: list[Toolchain] = []
        for signal in self.languages:
            chain = BY_LANGUAGE.get(signal.language)
            if chain and chain not in seen:
                seen.append(chain)
        return seen or [GENERIC]

    def summary(self) -> str:
        names = ", ".join(f"{s.language}({s.files})" for s in self.languages[:5]) or "none"
        return f"{self.primary_language} — detected: {names}"


def detect_repo(root: str | Path, max_files: int = 20000) -> RepoProfile:
    """Profile a repository from its manifests and file extensions."""
    root_path = Path(root)
    ext_counts: Counter[str] = Counter()
    manifests: dict[str, list[str]] = {}
    file_total = 0
    has_ci = (root_path / ".github" / "workflows").is_dir() or (
        root_path / ".gitlab-ci.yml"
    ).is_file()
    has_container = any(
        (root_path / name).is_file() for name in ("Dockerfile", "Containerfile", "compose.yaml")
    )
    workspace_markers = 0

    for path in _walk(root_path, max_files):
        file_total += 1
        name = path.name
        suffix = path.suffix
        if suffix:
            ext_counts[suffix] += 1
        for chain in TOOLCHAINS:
            for manifest in chain.manifests:
                if _manifest_match(name, manifest):
                    manifests.setdefault(chain.language, []).append(
                        str(path.relative_to(root_path))
                    )
                    if path.parent != root_path:
                        workspace_markers += 1

    signals: list[LanguageSignal] = []
    for chain in TOOLCHAINS:
        files = sum(ext_counts.get(ext, 0) for ext in chain.extensions)
        found = manifests.get(chain.language, [])
        if not files and not found:
            continue
        # A manifest is stronger evidence than a pile of files: a repo with one
        # go.mod and 400 .json fixtures is a Go repo.
        score = files + 50.0 * len(found)
        signals.append(
            LanguageSignal(language=chain.language, files=files, manifests=found[:5], score=score)
        )

    signals.sort(key=lambda s: s.score, reverse=True)
    primary = signals[0].language if signals else "unknown"
    # TypeScript repos always carry package.json; don't let JS outrank TS.
    if primary == "javascript" and any(s.language == "typescript" for s in signals):
        primary = "typescript"

    return RepoProfile(
        root=str(root_path),
        primary_language=primary,
        languages=signals,
        monorepo=workspace_markers >= 2,
        has_ci=has_ci,
        has_tests=any((root_path / d).is_dir() for d in ("tests", "test", "spec", "__tests__")),
        has_containerfile=has_container,
    )


def _walk(root: Path, max_files: int) -> Iterable[Path]:
    seen = 0
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except (OSError, PermissionError):
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name in IGNORED_DIRS or entry.name.startswith("."):
                    if entry.name != ".github":
                        continue
                stack.append(entry)
                continue
            seen += 1
            if seen > max_files:
                return
            yield entry


def _manifest_match(name: str, pattern: str) -> bool:
    if pattern.startswith("*"):
        return name.endswith(pattern[1:])
    return name == pattern


def toolchain_for(language: str) -> Optional[Toolchain]:
    return BY_LANGUAGE.get(language.lower())


def language_matrix() -> list[dict[str, str]]:
    """Flat matrix for docs, API and UI — one source, no drifting tables."""
    return [
        {
            "language": t.display_name,
            "manifests": ", ".join(t.manifests) or "—",
            "install": t.install or "—",
            "test": t.test or "—",
            "lint": t.lint or "—",
            "format": t.format or "—",
            "build": t.build or "—",
            "audit": t.audit or "—",
            "pin_style": t.pin_style or "—",
            "pin_rule": t.pin_rule,
        }
        for t in TOOLCHAINS
    ]
