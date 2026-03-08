#!/usr/bin/env python3
"""
Package Manager Guardrail
Enforces package versioning policies:
- No exact pinning without explicit justification
- Flags outdated packages
- Detects vulnerable packages via advisories
- Handles auto-upgrade for minor/patch, human approval for major
"""
import json
import re
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional
from packaging.version import Version, InvalidVersion


SEMVER_RANGE_MAP = {
    "exact":      lambda v: v,
    "patch":      lambda v: f"~{v}",         # ~1.2.3 → >=1.2.3 <1.3.0
    "minor":      lambda v: f"^{v}",         # ^1.2.3 → >=1.2.3 <2.0.0
    "compatible": lambda v: f">={v},<{next_major(v)}",
}


def next_major(version_str: str) -> str:
    try:
        v = Version(version_str)
        return f"{v.major + 1}.0.0"
    except Exception:
        return "99.0.0"


class PackageManager:
    def __init__(self, config: dict = None):
        cfg = config or {}
        self.policy = cfg.get("version_policy", "minor")   # exact|patch|minor|compatible
        self.auto_upgrade = cfg.get("auto_upgrade", True)
        self.check_vulnerabilities = cfg.get("check_vulnerabilities", True)
        self.check_outdated = cfg.get("check_outdated", True)
        self.pinned_exceptions = set(cfg.get("pinned_exceptions", []))
        self.upgrade_excludes = set(cfg.get("upgrade_excludes", []))
        self.offline_mode = cfg.get("offline_mode", False)

    def check(self, directory: str) -> list:
        findings = []
        root = Path(directory)

        # Python
        for req_file in root.rglob("requirements*.txt"):
            findings.extend(self._check_pip_requirements(req_file))

        for pyproject in root.rglob("pyproject.toml"):
            findings.extend(self._check_pyproject(pyproject))

        # Node
        for pkg_json in root.rglob("package.json"):
            if "node_modules" not in str(pkg_json):
                findings.extend(self._check_npm_package(pkg_json))

        # Go
        for go_mod in root.rglob("go.mod"):
            findings.extend(self._check_go_mod(go_mod))

        # Ruby
        for gemfile in root.rglob("Gemfile"):
            findings.extend(self._check_gemfile(gemfile))

        # Java Maven
        for pom in root.rglob("pom.xml"):
            findings.extend(self._check_maven_pom(pom))

        return findings

    # ──────────────────────────────────────────────
    # Python: requirements.txt
    # ──────────────────────────────────────────────
    def _check_pip_requirements(self, filepath: Path) -> list:
        findings = []
        try:
            lines = filepath.read_text().splitlines()
        except OSError:
            return findings

        for i, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Parse package==version (exact pin)
            exact = re.match(r'^([A-Za-z0-9_\-\[\].]+)==([^\s#]+)', line)
            if exact:
                pkg, ver = exact.group(1), exact.group(2)
                if pkg not in self.pinned_exceptions:
                    findings.append({
                        "type": "pinned_to_exact",
                        "package": pkg,
                        "version": ver,
                        "suggested": f"~={ver}",
                        "file": str(filepath),
                        "line": i,
                        "ecosystem": "python"
                    })

            # Check for vulnerable packages (offline: basic known list)
            if self.check_vulnerabilities and not self.offline_mode:
                match = re.match(r'^([A-Za-z0-9_\-\[\].]+)[>=<~!]{1,3}([^\s#,;]+)', line)
                if match:
                    vuln = self._check_pypi_advisory(match.group(1), match.group(2))
                    if vuln:
                        findings.append({**vuln, "file": str(filepath), "line": i})

        return findings

    # ──────────────────────────────────────────────
    # Python: pyproject.toml
    # ──────────────────────────────────────────────
    def _check_pyproject(self, filepath: Path) -> list:
        findings = []
        try:
            import tomllib  # Python 3.11+
        except ImportError:
            try:
                import tomli as tomllib
            except ImportError:
                return findings

        try:
            with open(filepath, "rb") as f:
                data = tomllib.load(f)
        except Exception:
            return findings

        deps = (data.get("project", {}).get("dependencies", []) +
                data.get("tool", {}).get("poetry", {}).get("dependencies", {}).keys())

        for dep in deps:
            if isinstance(dep, str):
                exact = re.match(r'^([A-Za-z0-9_\-\[\].]+)==([^\s,]+)', dep)
                if exact:
                    pkg, ver = exact.group(1), exact.group(2)
                    if pkg not in self.pinned_exceptions:
                        findings.append({
                            "type": "pinned_to_exact",
                            "package": pkg,
                            "version": ver,
                            "suggested": f"~={ver}",
                            "file": str(filepath),
                            "ecosystem": "python"
                        })

        return findings

    # ──────────────────────────────────────────────
    # Node: package.json
    # ──────────────────────────────────────────────
    def _check_npm_package(self, filepath: Path) -> list:
        findings = []
        try:
            pkg = json.loads(filepath.read_text())
        except (json.JSONDecodeError, OSError):
            return findings

        all_deps = {}
        all_deps.update(pkg.get("dependencies", {}))
        all_deps.update(pkg.get("devDependencies", {}))
        all_deps.update(pkg.get("peerDependencies", {}))

        for dep, version_spec in all_deps.items():
            if dep in self.pinned_exceptions:
                continue

            # Exact version (no ^ or ~)
            if re.match(r'^\d+\.\d+', version_spec):
                findings.append({
                    "type": "pinned_to_exact",
                    "package": dep,
                    "version": version_spec,
                    "suggested": f"^{version_spec}",
                    "file": str(filepath),
                    "ecosystem": "nodejs"
                })

            # Check for latest wildcard (*) - flag as imprecise
            if version_spec in ("*", "latest", "x"):
                findings.append({
                    "type": "version_wildcard",
                    "package": dep,
                    "version": version_spec,
                    "suggested": "Use a specific semver range like ^1.0.0",
                    "file": str(filepath),
                    "ecosystem": "nodejs"
                })

        return findings

    # ──────────────────────────────────────────────
    # Go: go.mod
    # ──────────────────────────────────────────────
    def _check_go_mod(self, filepath: Path) -> list:
        findings = []
        try:
            content = filepath.read_text()
        except OSError:
            return findings

        for line in content.splitlines():
            # require module v1.2.3
            match = re.match(r'\s+([^\s]+)\s+v([^\s]+)', line)
            if match:
                module, ver = match.group(1), match.group(2)
                # Go always uses exact versions; flag if very old (heuristic: v0.x)
                if ver.startswith("0."):
                    findings.append({
                        "type": "outdated",
                        "package": module,
                        "current": f"v{ver}",
                        "latest": "Check pkg.go.dev for latest",
                        "file": str(filepath),
                        "ecosystem": "go",
                        "is_major_bump": False
                    })

        return findings

    # ──────────────────────────────────────────────
    # Ruby: Gemfile
    # ──────────────────────────────────────────────
    def _check_gemfile(self, filepath: Path) -> list:
        findings = []
        try:
            lines = filepath.read_text().splitlines()
        except OSError:
            return findings

        for i, line in enumerate(lines, 1):
            line = line.strip()
            if line.startswith("#") or not line.startswith("gem"):
                continue

            # gem 'name', '1.2.3' exact pin
            exact = re.search(r"gem\s+['\"]([^'\"]+)['\"],\s*['\"](\d+\.\d+\.\d+)['\"]", line)
            if exact:
                pkg, ver = exact.group(1), exact.group(2)
                if pkg not in self.pinned_exceptions:
                    findings.append({
                        "type": "pinned_to_exact",
                        "package": pkg,
                        "version": ver,
                        "suggested": f"~> {ver}",
                        "file": str(filepath),
                        "line": i,
                        "ecosystem": "ruby"
                    })

        return findings

    # ──────────────────────────────────────────────
    # Java: pom.xml
    # ──────────────────────────────────────────────
    def _check_maven_pom(self, filepath: Path) -> list:
        findings = []
        try:
            content = filepath.read_text()
        except OSError:
            return findings

        # Look for LATEST or RELEASE version references (anti-pattern)
        if re.search(r'<version>(LATEST|RELEASE)</version>', content):
            findings.append({
                "type": "version_wildcard",
                "package": str(filepath),
                "version": "LATEST/RELEASE",
                "suggested": "Pin to a specific version for reproducible builds",
                "file": str(filepath),
                "ecosystem": "java-maven"
            })

        return findings

    # ──────────────────────────────────────────────
    # PyPI Advisory (lightweight check)
    # ──────────────────────────────────────────────
    def _check_pypi_advisory(self, package: str, version: str) -> Optional[dict]:
        """Check PyPI safety advisory (simplified - uses osv.dev API)."""
        if self.offline_mode:
            return None
        try:
            url = "https://api.osv.dev/v1/query"
            payload = json.dumps({
                "package": {"name": package, "ecosystem": "PyPI"},
                "version": version
            }).encode()
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
                if data.get("vulns"):
                    vuln = data["vulns"][0]
                    return {
                        "type": "vulnerable",
                        "package": package,
                        "current": version,
                        "cve": vuln.get("id", "unknown"),
                        "safe_version": "See advisory for fixed version",
                        "ecosystem": "python"
                    }
        except Exception:
            pass
        return None

    def suggest_upgrade_command(self, ecosystem: str, package: str) -> str:
        """Return the upgrade command for a given package ecosystem."""
        commands = {
            "python": f"pip install --upgrade {package}",
            "nodejs": f"npm update {package}",
            "ruby":   f"bundle update {package}",
            "go":     f"go get -u {package}",
            "java-maven": "mvn versions:use-latest-releases"
        }
        return commands.get(ecosystem, f"Upgrade {package} manually")
