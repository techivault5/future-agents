"""Tests for Pydantic models used in the scanning pipeline."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scanning.models import CrawlSession, KnowledgeQuery, ScrapedPage, ScrapeStatus


class TestScrapedPage:
    def test_creates_with_required_fields(self):
        page = ScrapedPage(
            id="abc123",
            url="https://example.com/",
            domain="example.com",
            crawl_session="sess1",
        )
        assert page.status == ScrapeStatus.SUCCESS
        assert page.word_count == 0
        assert page.links_found == 0
        assert isinstance(page.scraped_at, datetime)

    def test_to_snowflake_row_keys_uppercase(self):
        page = ScrapedPage(
            id="abc123",
            url="https://example.com/",
            domain="example.com",
            title="Test",
            text_content="Hello world",
            crawl_session="sess1",
        )
        row = page.to_snowflake_row()
        assert "ID" in row
        assert "URL" in row
        assert "TEXT_CONTENT" in row
        assert row["URL"] == "https://example.com/"
        assert row["TEXT_CONTENT"] == "Hello world"

    def test_failed_page_preserves_error(self):
        page = ScrapedPage(
            id="x",
            url="https://bad.com/",
            domain="bad.com",
            status=ScrapeStatus.FAILED,
            error_message="HTTP 404",
            http_status=404,
            crawl_session="sess2",
        )
        row = page.to_snowflake_row()
        assert row["STATUS"] == "failed"
        assert row["ERROR_MESSAGE"] == "HTTP 404"
        assert row["HTTP_STATUS"] == 404


class TestCrawlSession:
    def test_creates_with_defaults(self):
        session = CrawlSession(
            session_id="s1",
            seed_urls=["https://example.com"],
            max_depth=3,
            max_pages=100,
        )
        assert session.status == "running"
        assert session.pages_scraped == 0
        assert session.pages_failed == 0

    def test_to_snowflake_row(self):
        session = CrawlSession(
            session_id="s1",
            seed_urls=["https://a.com", "https://b.com"],
            max_depth=2,
            max_pages=50,
        )
        row = session.to_snowflake_row()
        assert row["SESSION_ID"] == "s1"
        assert row["MAX_DEPTH"] == 2
        assert row["STATUS"] == "running"


class TestKnowledgeQuery:
    def test_defaults(self):
        q = KnowledgeQuery()
        assert q.limit == 50
        assert q.min_word_count == 0
        assert q.query is None

    def test_limit_clamped(self):
        with pytest.raises(Exception):
            KnowledgeQuery(limit=0)

        with pytest.raises(Exception):
            KnowledgeQuery(limit=1001)

    def test_valid_query(self):
        q = KnowledgeQuery(query="python asyncio", domain="docs.python.org", limit=20)
        assert q.query == "python asyncio"
        assert q.domain == "docs.python.org"
        assert q.limit == 20
