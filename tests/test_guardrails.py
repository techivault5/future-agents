"""
Tests for the IT Agents Guardrails engine.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Make guardrails importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from guardrails.secrets_scanner import SecretsScanner
from guardrails.package_manager import PackageManager
from guardrails.folder_validator import FolderValidator


# ─────────────────────────────────────────────────────────────────
# SECRETS SCANNER
# ─────────────────────────────────────────────────────────────────

class TestSecretsScanner:

    def setup_method(self):
        self.scanner = SecretsScanner()

    def test_detects_aws_access_key(self, tmp_path):
        (tmp_path / "config.py").write_text('KEY = "AKIAIOSFODNN7TESTKEY1"')
        findings = self.scanner.scan_directory(str(tmp_path))
        assert any(f["rule_id"] == "AWS_ACCESS_KEY" for f in findings)

    def test_detects_openai_key(self, tmp_path):
        (tmp_path / "app.py").write_text('client = OpenAI(api_key="sk-abcdefghijklmnopqrstuvwxyz123456")')
        findings = self.scanner.scan_directory(str(tmp_path))
        assert any(f["rule_id"] == "OPENAI_KEY" for f in findings)

    def test_detects_private_key(self, tmp_path):
        (tmp_path / "key.pem").write_text("-----BEGIN RSA PRIVATE KEY-----\nMIIE...")
        findings = self.scanner.scan_directory(str(tmp_path))
        assert any(f["rule_id"] == "PRIVATE_KEY_HEADER" for f in findings)

    def test_ignores_placeholder_values(self, tmp_path):
        (tmp_path / "env.example").write_text('OPENAI_API_KEY=REPLACE_ME\nSTRIPE_KEY=your-key-here')
        findings = self.scanner.scan_directory(str(tmp_path))
        critical = [f for f in findings if f["severity"] == "critical"]
        assert len(critical) == 0

    def test_ignores_env_example_files(self, tmp_path):
        (tmp_path / ".env.example").write_text('DB_PASS=changeme\nAPI_KEY=your-secret-here')
        findings = self.scanner.scan_directory(str(tmp_path))
        assert all(f["is_example_file"] for f in findings)

    def test_skips_commented_lines(self, tmp_path):
        (tmp_path / "app.py").write_text(
            '# api_key = "AKIAIOSFODNN7EXAMPLE1"\n'
            '# This is just a comment\n'
        )
        findings = self.scanner.scan_directory(str(tmp_path))
        critical = [f for f in findings if f["severity"] == "critical"]
        assert len(critical) == 0

    def test_scan_string(self):
        content = 'token = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"'
        findings = self.scanner.scan_string(content, "inline")
        assert any(f["rule_id"] == "GITHUB_TOKEN" for f in findings)

    def test_detects_db_connection_string(self, tmp_path):
        (tmp_path / "settings.py").write_text(
            'DATABASE_URL = "postgresql://admin:s3cr3tpass@db.prod-internal.com/mydb"'
        )
        findings = self.scanner.scan_directory(str(tmp_path))
        assert any(f["rule_id"] == "DB_CONNECTION_STRING" for f in findings)

    def test_detects_sqlserver_url(self, tmp_path):
        (tmp_path / "db.py").write_text(
            'CONN = "mssql+pyodbc://sa:Str0ngPass!@sqlprod:1433/mydb"'
        )
        findings = self.scanner.scan_directory(str(tmp_path))
        assert any(f["rule_id"] == "DB_CONNECTION_STRING" for f in findings)

    def test_detects_sqlserver_ado_connstr(self, tmp_path):
        (tmp_path / "appsettings.json").write_text(
            '{"ConnectionStrings": {"Default": "Server=prod.sql;Database=app;User Id=sa;Password=Str0ngPass!;Encrypt=True"}}'
        )
        findings = self.scanner.scan_directory(str(tmp_path))
        assert any(f["rule_id"] in ("SQLSERVER_ADO_CONNSTR", "SQLSERVER_SA_PASS") for f in findings)

    def test_detects_mssql_sa_password_env(self, tmp_path):
        (tmp_path / "deploy.sh").write_text('export MSSQL_SA_PASSWORD=Str0ngPass123!')
        findings = self.scanner.scan_directory(str(tmp_path))
        assert any(f["rule_id"] in ("MSSQL_SA_PASSWORD", "DB_PASSWORD_INLINE") for f in findings)

    def test_ignores_sqlserver_env_example(self, tmp_path):
        (tmp_path / ".env.example").write_text("MSSQL_SA_PASSWORD=REPLACE_ME\n")
        findings = self.scanner.scan_directory(str(tmp_path))
        critical = [f for f in findings if f["severity"] == "critical"]
        assert len(critical) == 0


# ─────────────────────────────────────────────────────────────────
# PACKAGE MANAGER
# ─────────────────────────────────────────────────────────────────

class TestPackageManager:

    def setup_method(self):
        self.pm = PackageManager({"offline_mode": True})

    def test_detects_exact_pin_python(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("requests==2.31.0\nflask==3.0.0\n")
        findings = self.pm.check(str(tmp_path))
        exact = [f for f in findings if f["type"] == "pinned_to_exact"]
        assert len(exact) == 2
        assert any(f["package"] == "requests" for f in exact)

    def test_accepts_compatible_range_python(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("requests~=2.31\nflask>=3.0,<4.0\n")
        findings = self.pm.check(str(tmp_path))
        exact = [f for f in findings if f["type"] == "pinned_to_exact"]
        assert len(exact) == 0

    def test_detects_exact_pin_node(self, tmp_path):
        pkg = {"dependencies": {"react": "18.2.0", "lodash": "4.17.21"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        findings = self.pm.check(str(tmp_path))
        exact = [f for f in findings if f["type"] == "pinned_to_exact"]
        assert len(exact) == 2

    def test_detects_wildcard_node(self, tmp_path):
        pkg = {"dependencies": {"react": "latest", "lodash": "*"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        findings = self.pm.check(str(tmp_path))
        wildcards = [f for f in findings if f["type"] == "version_wildcard"]
        assert len(wildcards) == 2

    def test_accepts_semver_node(self, tmp_path):
        pkg = {"dependencies": {"react": "^18.2.0", "lodash": "~4.17.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        findings = self.pm.check(str(tmp_path))
        problems = [f for f in findings if f["type"] in ("pinned_to_exact", "version_wildcard")]
        assert len(problems) == 0

    def test_detects_maven_latest(self, tmp_path):
        pom = "<project><dependencies><dependency><version>LATEST</version></dependency></dependencies></project>"
        (tmp_path / "pom.xml").write_text(pom)
        findings = self.pm.check(str(tmp_path))
        assert any(f["type"] == "version_wildcard" for f in findings)

    def test_pinned_exception_skipped(self, tmp_path):
        pm = PackageManager({"offline_mode": True, "pinned_exceptions": ["setuptools"]})
        (tmp_path / "requirements.txt").write_text("setuptools==68.0.0\n")
        findings = pm.check(str(tmp_path))
        assert len(findings) == 0


# ─────────────────────────────────────────────────────────────────
# FOLDER VALIDATOR
# ─────────────────────────────────────────────────────────────────

class TestFolderValidator:

    def setup_method(self):
        self.validator = FolderValidator()

    def test_detects_missing_required_paths(self, tmp_path):
        # Create a minimal python-service without required dirs
        (tmp_path / "pyproject.toml").touch()
        findings = self.validator.validate(str(tmp_path))
        missing = [f for f in findings if f["type"] == "missing_required"]
        required_paths = {f["path"] for f in missing}
        assert "src/" in required_paths
        assert "tests/" in required_paths

    def test_passes_complete_python_service(self, tmp_path):
        # Scaffold a complete structure
        for d in ["src/", "tests/", "docs/", ".github/workflows/"]:
            (tmp_path / d).mkdir(parents=True, exist_ok=True)
        for f in ["Dockerfile", ".env.example", "README.md", "pyproject.toml",
                  ".gitignore", ".pre-commit-config.yaml"]:
            (tmp_path / f).touch()
        findings = self.validator.validate(str(tmp_path))
        missing = [f for f in findings if f["type"] == "missing_required"]
        assert len(missing) == 0

    def test_detects_forbidden_env_file(self, tmp_path):
        (tmp_path / "pyproject.toml").touch()
        (tmp_path / ".env").write_text("SECRET=realvalue")
        findings = self.validator.validate(str(tmp_path))
        forbidden = [f for f in findings if f["type"] == "forbidden_file"]
        assert any(".env" in f["path"] for f in forbidden)

    def test_auto_detects_project_type(self, tmp_path):
        (tmp_path / "pyproject.toml").touch()
        detected = self.validator.detect_project_type(str(tmp_path))
        assert detected == "python-service"

    def test_auto_detects_node_project(self, tmp_path):
        (tmp_path / "package.json").write_text('{"name": "test"}')
        detected = self.validator.detect_project_type(str(tmp_path))
        assert detected == "node-service"

    def test_generate_structure(self, tmp_path):
        created = self.validator.generate_structure(
            "generic-project", "my-project", str(tmp_path)
        )
        assert (tmp_path / "my-project" / "README.md").exists()
        assert (tmp_path / "my-project" / ".gitignore").exists()
        assert (tmp_path / "my-project" / ".env.example").exists()

    def test_force_project_type(self, tmp_path):
        validator = FolderValidator({"project_type": "node-service"})
        (tmp_path / "pyproject.toml").touch()  # would normally detect python
        detected = validator.detect_project_type(str(tmp_path))
        assert detected == "node-service"


# ─────────────────────────────────────────────────────────────────
# AGENTS INDEX
# ─────────────────────────────────────────────────────────────────

class TestAgentsIndex:

    def test_agents_index_exists(self):
        index_path = Path(__file__).parent.parent / "agents" / "agents_index.json"
        assert index_path.exists(), "agents_index.json must exist"

    def test_agents_index_has_10000_entries(self):
        index_path = Path(__file__).parent.parent / "agents" / "agents_index.json"
        if index_path.exists():
            idx = json.loads(index_path.read_text())
            assert len(idx) == 10000, f"Expected 10000 agents, got {len(idx)}"

    def test_agents_have_required_fields(self):
        index_path = Path(__file__).parent.parent / "agents" / "agents_index.json"
        if index_path.exists():
            idx = json.loads(index_path.read_text())
            for agent in idx[:100]:  # spot-check first 100
                assert "id" in agent
                assert "name" in agent
                assert "role" in agent
                assert "type" in agent
                assert "seniority" in agent
