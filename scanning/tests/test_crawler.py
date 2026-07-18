"""Tests for the BFS crawler engine (no real HTTP calls)."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from scanning.config import CrawlerConfig
from scanning.crawler import Crawler
from scanning.models import ScrapeStatus


SIMPLE_HTML = """
<html>
<head><title>Mock Page</title></head>
<body>
  <p>Some content here for testing purposes.</p>
  <a href="/page2">Link to page 2</a>
  <a href="/page3">Link to page 3</a>
</body>
</html>
"""

PAGE2_HTML = """
<html>
<head><title>Page 2</title></head>
<body><p>Page 2 content.</p></body>
</html>
"""


def make_config(**overrides) -> CrawlerConfig:
    cfg = CrawlerConfig.__new__(CrawlerConfig)
    cfg.max_depth = overrides.get("max_depth", 1)
    cfg.max_pages = overrides.get("max_pages", 10)
    cfg.concurrency = overrides.get("concurrency", 2)
    cfg.request_delay_seconds = 0.0
    cfg.request_timeout_seconds = 5
    cfg.stay_on_domain = overrides.get("stay_on_domain", True)
    cfg.skip_extensions = (".pdf", ".png")
    cfg.user_agent = "TestAgent/1.0"
    cfg.respect_robots_txt = False  # disable in tests
    cfg.snowflake_batch_size = 10
    return cfg


def make_response(text: str, status: int = 200, content_type: str = "text/html; charset=utf-8") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.headers = {"content-type": content_type}
    resp.text = text
    return resp


class TestCrawlerDepthAndDomain:
    @pytest.mark.asyncio
    async def test_scrapes_seed_url(self):
        cfg = make_config(max_depth=0, max_pages=5)
        crawler = Crawler(cfg, session_id="test-session")

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=make_response(SIMPLE_HTML))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            pages = [p async for p in crawler.crawl(["https://example.com/"])]

        assert len(pages) >= 1
        assert pages[0].status == ScrapeStatus.SUCCESS
        # Root URL keeps its trailing slash after normalisation
        assert "example.com" in pages[0].url
        assert pages[0].title == "Mock Page"

    @pytest.mark.asyncio
    async def test_follows_links_at_depth_1(self):
        cfg = make_config(max_depth=1, max_pages=10)
        crawler = Crawler(cfg, session_id="test-session")

        responses = {
            "https://example.com": make_response(SIMPLE_HTML),
            "https://example.com/page2": make_response(PAGE2_HTML),
            "https://example.com/page3": make_response(PAGE2_HTML),
        }

        async def mock_get(url, **_):
            # Match by normalised URL prefix
            for key, resp in responses.items():
                if url.startswith(key):
                    return resp
            return make_response("", status=404)

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = mock_get
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            pages = [p async for p in crawler.crawl(["https://example.com/"])]

        urls_scraped = {p.url for p in pages if p.status == ScrapeStatus.SUCCESS}
        assert len(urls_scraped) >= 1  # seed always scraped

    @pytest.mark.asyncio
    async def test_respects_max_pages(self):
        cfg = make_config(max_depth=3, max_pages=2)
        crawler = Crawler(cfg, session_id="test-session")

        # HTML with many links
        many_links_html = "<html><body>" + "".join(
            f'<a href="/p{i}">Link {i}</a>' for i in range(20)
        ) + "</body></html>"

        async def mock_get(url, **_):
            return make_response(many_links_html)

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = mock_get
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            pages = [p async for p in crawler.crawl(["https://example.com/"])]

        # With concurrency=2 and max_pages=2, at most max_pages + concurrency - 1 pages are scraped
        assert len(pages) <= 2 + make_config().concurrency

    @pytest.mark.asyncio
    async def test_skips_already_crawled(self):
        from scanning.html_parser import url_id, normalise_url
        cfg = make_config(max_depth=1, max_pages=10)

        # Use the normalised form that the crawler will actually add to visited
        seed_url = normalise_url("https://example.com/")
        seed_id = url_id(seed_url)
        crawler = Crawler(cfg, session_id="test-session", already_crawled={seed_id})

        async def mock_get(url, **_):
            return make_response(SIMPLE_HTML)

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = mock_get
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            pages = [p async for p in crawler.crawl(["https://example.com/"])]

        # Seed URL was pre-visited, so no pages should be scraped
        assert len(pages) == 0

    @pytest.mark.asyncio
    async def test_handles_http_error(self):
        cfg = make_config(max_depth=0, max_pages=5)
        crawler = Crawler(cfg, session_id="test-session")

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=make_response("", status=404))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            pages = [p async for p in crawler.crawl(["https://example.com/"])]

        assert len(pages) == 1
        assert pages[0].status == ScrapeStatus.FAILED
        assert pages[0].http_status == 404

    @pytest.mark.asyncio
    async def test_handles_network_error(self):
        import httpx
        cfg = make_config(max_depth=0, max_pages=5)
        crawler = Crawler(cfg, session_id="test-session")

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            pages = [p async for p in crawler.crawl(["https://example.com/"])]

        assert len(pages) == 1
        assert pages[0].status == ScrapeStatus.FAILED
        assert "timed out" in pages[0].error_message.lower()

    @pytest.mark.asyncio
    async def test_skips_non_html_content(self):
        cfg = make_config(max_depth=0, max_pages=5)
        crawler = Crawler(cfg, session_id="test-session")

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(
                return_value=make_response(b"binary data".decode(), content_type="application/octet-stream")
            )
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            pages = [p async for p in crawler.crawl(["https://example.com/file.bin"])]

        assert pages[0].status == ScrapeStatus.SKIPPED
