"""Pydantic models for web scraping data."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator


class ScrapeStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class ScrapedPage(BaseModel):
    """A single scraped web page with extracted text and metadata."""

    id: str = Field(description="SHA-256 of the URL (hex)")
    url: str = Field(description="Canonical URL of the page")
    source_url: Optional[str] = Field(None, description="URL that linked to this page; None for seeds")
    domain: str = Field(description="Hostname, e.g. 'docs.python.org'")
    title: Optional[str] = Field(None, description="Page <title> text")
    text_content: Optional[str] = Field(None, description="Cleaned visible text, whitespace-normalised")
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    crawl_depth: int = Field(0, ge=0, description="0 = seed URL")
    word_count: int = Field(0, ge=0)
    links_found: int = Field(0, ge=0, description="Number of outbound links extracted")
    status: ScrapeStatus = ScrapeStatus.SUCCESS
    error_message: Optional[str] = None
    http_status: Optional[int] = None
    content_hash: Optional[str] = Field(None, description="SHA-256 of text_content for dedup")
    crawl_session: str = Field(description="UUID of the crawl session")

    def to_snowflake_row(self) -> dict:
        """Return a flat dict ready for Snowflake write_pandas / execute_many."""
        return {
            "ID": self.id,
            "URL": self.url,
            "SOURCE_URL": self.source_url,
            "DOMAIN": self.domain,
            "TITLE": self.title,
            "TEXT_CONTENT": self.text_content,
            "SCRAPED_AT": self.scraped_at.strftime("%Y-%m-%d %H:%M:%S"),
            "CRAWL_DEPTH": self.crawl_depth,
            "WORD_COUNT": self.word_count,
            "LINKS_FOUND": self.links_found,
            "STATUS": self.status.value,
            "ERROR_MESSAGE": self.error_message,
            "HTTP_STATUS": self.http_status,
            "CONTENT_HASH": self.content_hash,
            "CRAWL_SESSION": self.crawl_session,
        }


class CrawlSession(BaseModel):
    """Tracks metadata for a single agent crawl run."""

    session_id: str
    seed_urls: list[str]
    max_depth: int
    max_pages: int
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None
    pages_scraped: int = 0
    pages_failed: int = 0
    status: str = "running"  # running | completed | failed

    def to_snowflake_row(self) -> dict:
        return {
            "SESSION_ID": self.session_id,
            "SEED_URLS": str(self.seed_urls),  # stored as string; Snowflake ARRAY variant
            "MAX_DEPTH": self.max_depth,
            "MAX_PAGES": self.max_pages,
            "STARTED_AT": self.started_at.strftime("%Y-%m-%d %H:%M:%S"),
            "FINISHED_AT": self.finished_at.strftime("%Y-%m-%d %H:%M:%S") if self.finished_at else None,
            "PAGES_SCRAPED": self.pages_scraped,
            "PAGES_FAILED": self.pages_failed,
            "STATUS": self.status,
        }


class KnowledgeQuery(BaseModel):
    """Parameters other agents pass when reading from the web knowledge store."""

    query: Optional[str] = Field(None, description="Full-text search terms")
    domain: Optional[str] = Field(None, description="Filter to a specific domain")
    min_word_count: int = Field(0, description="Skip very short pages")
    max_depth: Optional[int] = Field(None, description="Only pages at or above this crawl depth")
    limit: int = Field(50, ge=1, le=1000, description="Max rows returned")
    session_id: Optional[str] = Field(None, description="Restrict to a specific crawl session")
