#!/usr/bin/env python3
"""
Secrets Scanner
Detects hard-coded secrets, credentials, API keys, tokens, and sensitive values
in source code, config files, and environment files.
"""
import re
from pathlib import Path


# ─────────────────────────────────────────────────────────────────
# SECRET PATTERNS
# Each entry: (rule_id, description, regex_pattern, severity)
# ─────────────────────────────────────────────────────────────────
SECRET_PATTERNS = [
    # API Keys - Cloud providers
    ("AWS_ACCESS_KEY",      "AWS Access Key ID",
     r"(?i)(AKIA|AGPA|AROA|AIPA|ANPA|ANVA|ASIA)[A-Z0-9]{16}", "critical"),
    ("AWS_SECRET_KEY",      "AWS Secret Access Key",
     r"(?i)aws.{0,20}secret.{0,20}['\"][0-9a-zA-Z/+]{40}['\"]", "critical"),
    ("GCP_API_KEY",         "Google Cloud API Key",
     r"AIza[0-9A-Za-z\-_]{35}", "critical"),
    ("AZURE_CLIENT_SECRET", "Azure Client Secret",
     r"(?i)azure.{0,20}(secret|password|credential).{0,20}['\"][^'\"]{20,}['\"]", "critical"),

    # Tokens - Auth & Communication
    ("GITHUB_TOKEN",        "GitHub Token",
     r"gh[pousr]_[A-Za-z0-9_]{36,}", "critical"),
    ("GITLAB_TOKEN",        "GitLab Token",
     r"glpat-[A-Za-z0-9\-]{20}", "critical"),
    ("SLACK_TOKEN",         "Slack API Token",
     r"xox[baprs]-([0-9a-zA-Z]{10,48})", "critical"),
    ("SLACK_WEBHOOK",       "Slack Webhook URL",
     r"https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+", "critical"),
    ("DISCORD_WEBHOOK",     "Discord Webhook URL",
     r"https://discord(?:app)?\.com/api/webhooks/[0-9]+/[A-Za-z0-9_\-]+", "high"),
    ("TELEGRAM_BOT_TOKEN",  "Telegram Bot Token",
     r"[0-9]{8,10}:[A-Za-z0-9_\-]{35}", "high"),

    # Database connection strings
    ("DB_CONNECTION_STRING", "Database Connection String with Password",
     r"(?i)(postgres(?:ql)?|mysql|mongodb|redis|mssql(?:\+\w+)?|sqlserver|oracle(?:\+\w+)?)://[^:@\s]+:[^@\s]+@[^\s/]+", "critical"),
    ("SQLSERVER_ADO_CONNSTR", "SQL Server ADO.NET Connection String with Password",
     r"(?i)(Server|Data Source)=[^;]+;.*?Password\s*=[^;]{4,}", "critical"),
    ("SQLSERVER_SA_PASS",    "SQL Server SA / Trusted Connection with inline password",
     r"(?i)(User Id|UID)\s*=\s*\w+\s*;\s*Password\s*=\s*[^;\"']{4,}", "critical"),
    ("DB_PASSWORD_INLINE",   "Database Password in Config",
     r"(?i)(db_pass|database_password|db_password|PGPASSWORD|MSSQL_SA_PASSWORD|SA_PASSWORD)\s*[=:]\s*['\"]?[^'\"]{6,}['\"]?", "critical"),

    # Generic credentials
    ("GENERIC_SECRET",      "Generic Secret Assignment",
     r"(?i)(secret|password|passwd|pwd|token|api[_-]?key|auth[_-]?key)\s*[=:]\s*['\"][^'\"]{8,}['\"]", "high"),
    ("PRIVATE_KEY_HEADER",  "Private Key Block",
     r"-----BEGIN (RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY", "critical"),
    ("CERTIFICATE",         "Certificate/Key File",
     r"-----BEGIN CERTIFICATE-----", "medium"),

    # JWT
    ("JWT_TOKEN",           "Hardcoded JWT Token",
     r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}", "high"),

    # OAuth / Auth services
    ("STRIPE_KEY",          "Stripe API Key",
     r"sk_(live|test)_[A-Za-z0-9]{24,}", "critical"),
    ("SENDGRID_KEY",        "SendGrid API Key",
     r"SG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43}", "critical"),
    ("TWILIO_SID",          "Twilio Account SID",
     r"AC[a-z0-9]{32}", "high"),
    ("TWILIO_TOKEN",        "Twilio Auth Token",
     r"(?i)twilio.{0,20}(token|secret).{0,20}['\"][a-z0-9]{32}['\"]", "critical"),
    ("OPENAI_KEY",          "OpenAI API Key",
     r"sk-[A-Za-z0-9]{32,}", "critical"),
    ("ANTHROPIC_KEY",       "Anthropic API Key",
     r"sk-ant-[A-Za-z0-9\-_]{40,}", "critical"),
    ("HUGGINGFACE_TOKEN",   "HuggingFace Token",
     r"hf_[A-Za-z0-9]{30,}", "high"),

    # Cloud storage / CDN
    ("S3_BUCKET_URL_WITH_KEY", "S3 URL with embedded credentials",
     r"https?://[A-Za-z0-9]+:[A-Za-z0-9/+]{20,}@s3\.amazonaws\.com", "critical"),

    # Containers / Registries
    ("DOCKER_AUTH",         "Docker Registry Auth",
     r"\"auth\"\s*:\s*\"[A-Za-z0-9+/=]{20,}\"", "high"),

    # Sensitive env-var patterns
    ("ENV_SECRET",          "Secret in .env file",
     r"^(?!#).*(SECRET|PASSWORD|TOKEN|KEY|PASS|CREDENTIAL)\s*=\s*.{6,}$", "high"),
]

# Files to always skip (binary, generated, etc.)
SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".ico",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".pyc", ".pyo", ".class", ".o", ".so", ".dll", ".exe",
    ".woff", ".woff2", ".ttf", ".eot",
    ".mp4", ".mp3", ".wav", ".avi", ".mov",
    ".lock",  # package-lock etc – check separately
    ".sum",   # go.sum
}

# Files to always skip by name
SKIP_FILES = {
    ".git", ".gitignore", ".gitattributes",
    "node_modules", "__pycache__", ".pytest_cache",
    "dist", "build", ".next", ".nuxt", "target",
    "vendor", "venv", ".venv", "env",
}

# Files that may intentionally contain example/dummy secrets
EXAMPLE_FILE_PATTERNS = [
    r"\.example$", r"\.sample$", r"\.template$",
    r"test_", r"_test\.", r"spec\.", r"fixture",
    r"README", r"CHANGELOG", r"CONTRIBUTING",
    r"\.md$", r"\.rst$"
]

ALLOWLIST_VALUES = {
    "example", "your-secret-here", "changeme", "placeholder",
    "xxxxxxxx", "00000000", "password123", "secret123",
    "<your-key>", "${", "#{", "$(", "%{",
    "REPLACE_ME", "YOUR_KEY_HERE", "INSERT_KEY",
}


class SecretsScanner:
    def __init__(self, config: dict = None):
        cfg = config or {}
        self.max_file_size_kb = cfg.get("max_file_size_kb", 500)
        self.extra_patterns = cfg.get("extra_patterns", [])
        self.allowlist = set(cfg.get("allowlist_values", [])) | ALLOWLIST_VALUES
        self.allowlist_files = cfg.get("allowlist_files", [])
        self.patterns = self._compile_patterns()

    def _compile_patterns(self) -> list:
        compiled = []
        for rule_id, desc, pattern, severity in SECRET_PATTERNS:
            try:
                compiled.append((rule_id, desc, re.compile(pattern, re.MULTILINE), severity))
            except re.error:
                pass  # skip bad patterns
        for extra in self.extra_patterns:
            try:
                compiled.append((
                    extra["id"],
                    extra["description"],
                    re.compile(extra["pattern"], re.MULTILINE),
                    extra.get("severity", "high")
                ))
            except (KeyError, re.error):
                pass
        return compiled

    def _should_skip(self, path: Path) -> bool:
        parts = set(path.parts)
        if parts & SKIP_FILES:
            return True
        if path.suffix.lower() in SKIP_EXTENSIONS:
            return True
        if path.stat().st_size > self.max_file_size_kb * 1024:
            return True
        if str(path) in self.allowlist_files:
            return True
        return False

    def _is_example_file(self, path: Path) -> bool:
        name = path.name
        for pat in EXAMPLE_FILE_PATTERNS:
            if re.search(pat, name, re.IGNORECASE):
                return True
        return False

    def _is_allowlisted_value(self, value: str) -> bool:
        val_lower = value.lower()
        for allowed in self.allowlist:
            if allowed.lower() in val_lower:
                return True
        return False

    def scan_file(self, filepath: str) -> list:
        path = Path(filepath)
        findings = []

        if self._should_skip(path):
            return findings

        is_example = self._is_example_file(path)

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except (OSError, PermissionError):
            return findings

        lines = content.splitlines()

        for rule_id, desc, pattern, severity in self.patterns:
            for match in pattern.finditer(content):
                matched_value = match.group(0)

                # Skip obvious placeholders
                if self._is_allowlisted_value(matched_value):
                    continue

                # Find line number
                line_num = content[:match.start()].count("\n") + 1
                line_content = lines[line_num - 1].strip() if line_num <= len(lines) else ""

                # Skip commented lines
                if line_content.startswith("#") or line_content.startswith("//"):
                    continue

                effective_severity = "low" if is_example else severity

                findings.append({
                    "rule_id": rule_id,
                    "description": desc,
                    "file": str(path),
                    "line": line_num,
                    "matched": matched_value[:60] + "..." if len(matched_value) > 60
                              else matched_value,
                    "severity": effective_severity,
                    "is_example_file": is_example
                })

        return findings

    def scan_directory(self, directory: str) -> list:
        all_findings = []
        root = Path(directory)

        for path in root.rglob("*"):
            if path.is_file():
                findings = self.scan_file(str(path))
                all_findings.extend(findings)

        return all_findings

    def scan_string(self, content: str, source_name: str = "<string>") -> list:
        """Scan a string directly (e.g., from environment variable or stdin)."""
        findings = []

        for rule_id, desc, pattern, severity in self.patterns:
            for match in pattern.finditer(content):
                matched_value = match.group(0)
                if self._is_allowlisted_value(matched_value):
                    continue
                line_num = content[:match.start()].count("\n") + 1
                findings.append({
                    "rule_id": rule_id,
                    "description": desc,
                    "file": source_name,
                    "line": line_num,
                    "matched": matched_value[:60] + "..." if len(matched_value) > 60
                              else matched_value,
                    "severity": severity,
                    "is_example_file": False
                })

        return findings
