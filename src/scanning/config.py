"""Configuration for the web scraper + Snowflake pipeline.

All settings can be overridden via environment variables.
Copy .env.example to .env and fill in your Snowflake credentials.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class SnowflakeConfig:
    """Snowflake connection settings loaded from environment variables."""

    account: str = field(default_factory=lambda: os.environ["SNOWFLAKE_ACCOUNT"])
    user: str = field(default_factory=lambda: os.environ["SNOWFLAKE_USER"])
    password: str = field(default_factory=lambda: os.environ["SNOWFLAKE_PASSWORD"])
    database: str = field(default_factory=lambda: os.getenv("SNOWFLAKE_DATABASE", "FUTURE_AGENTS_DB"))
    schema: str = field(default_factory=lambda: os.getenv("SNOWFLAKE_SCHEMA", "KNOWLEDGE"))
    warehouse: str = field(default_factory=lambda: os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"))
    role: str = field(default_factory=lambda: os.getenv("SNOWFLAKE_ROLE", ""))
    # Optional: use private key auth instead of password
    private_key_path: str = field(default_factory=lambda: os.getenv("SNOWFLAKE_PRIVATE_KEY_PATH", ""))

    def as_connector_kwargs(self) -> dict:
        kwargs: dict = {
            "account": self.account,
            "user": self.user,
            "database": self.database,
            "schema": self.schema,
            "warehouse": self.warehouse,
        }
        if self.role:
            kwargs["role"] = self.role
        if self.private_key_path:
            import base64
            from cryptography.hazmat.backends import default_backend
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
            with open(self.private_key_path, "rb") as f:
                private_key = load_pem_private_key(f.read(), password=None, backend=default_backend())
            from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
            kwargs["private_key"] = private_key.private_bytes(
                Encoding.DER, PrivateFormat.PKCS8, NoEncryption()
            )
        else:
            kwargs["password"] = self.password
        return kwargs


@dataclass
class CrawlerConfig:
    """Tuning knobs for the BFS crawler."""

    # How many link-hops deep to follow from a seed URL (0 = seed only)
    max_depth: int = field(default_factory=lambda: int(os.getenv("CRAWLER_MAX_DEPTH", "3")))

    # Hard cap on total pages crawled per session
    max_pages: int = field(default_factory=lambda: int(os.getenv("CRAWLER_MAX_PAGES", "500")))

    # Pages crawled concurrently
    concurrency: int = field(default_factory=lambda: int(os.getenv("CRAWLER_CONCURRENCY", "5")))

    # Seconds to wait between requests to the same domain (polite crawling)
    request_delay_seconds: float = field(
        default_factory=lambda: float(os.getenv("CRAWLER_REQUEST_DELAY", "1.0"))
    )

    # HTTP request timeout in seconds
    request_timeout_seconds: int = field(
        default_factory=lambda: int(os.getenv("CRAWLER_TIMEOUT", "15"))
    )

    # Only follow links that stay on the same domain as the seed URL
    stay_on_domain: bool = field(
        default_factory=lambda: os.getenv("CRAWLER_STAY_ON_DOMAIN", "true").lower() == "true"
    )

    # Skip URLs matching these substrings (e.g. binary files)
    skip_extensions: tuple[str, ...] = field(
        default_factory=lambda: (
            ".pdf", ".docx", ".xlsx", ".zip", ".tar", ".gz",
            ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
            ".mp4", ".mp3", ".avi", ".mov", ".woff", ".woff2",
            ".css", ".js", ".json", ".xml",
        )
    )

    # User-Agent string sent with every request
    user_agent: str = field(
        default_factory=lambda: os.getenv(
            "CRAWLER_USER_AGENT",
            "FutureAgents-Scraper/1.0 (+https://github.com/techivault5/future-agents)",
        )
    )

    # Respect robots.txt (recommended: True)
    respect_robots_txt: bool = field(
        default_factory=lambda: os.getenv("CRAWLER_RESPECT_ROBOTS", "true").lower() == "true"
    )

    # Batch size for Snowflake inserts
    snowflake_batch_size: int = field(
        default_factory=lambda: int(os.getenv("SNOWFLAKE_BATCH_SIZE", "50"))
    )


@dataclass
class ScannerConfig:
    """Top-level config combining all sub-configs."""

    snowflake: SnowflakeConfig = field(default_factory=SnowflakeConfig)
    crawler: CrawlerConfig = field(default_factory=CrawlerConfig)

    @classmethod
    def from_env(cls) -> "ScannerConfig":
        """Load config from environment variables (with .env file support)."""
        _load_dotenv()
        return cls()


def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader — reads KEY=VALUE lines without external deps."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
