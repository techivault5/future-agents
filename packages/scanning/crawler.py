"""BFS web crawler engine.

Crawls a set of seed URLs breadth-first, respects domain scope, depth limits,
page caps, politeness delays, and robots.txt.  Yields ScrapedPage objects as
pages are fetched so callers can flush them to Snowflake in batches.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import AsyncIterator, Callable
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from scanning.config import CrawlerConfig
from scanning.html_parser import (
    ParsedPage,
    domain_of,
    is_same_domain,
    normalise_url,
    parse_html,
    url_id,
)
from scanning.models import ScrapedPage, ScrapeStatus

logger = logging.getLogger(__name__)


class Crawler:
    """Async BFS crawler that yields :class:`ScrapedPage` objects.

    Usage::

        crawler = Crawler(config, session_id="abc123")
        async for page in crawler.crawl(["https://example.com"]):
            print(page.url, page.word_count)
    """

    def __init__(
        self,
        config: CrawlerConfig,
        session_id: str,
        already_crawled: set[str] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> None:
        self._cfg = config
        self._session_id = session_id
        self._visited: set[str] = already_crawled or set()  # set of url_id hashes
        self._robots_cache: dict[str, RobotFileParser] = {}
        self._domain_last_request: dict[str, float] = {}
        self._on_progress = on_progress  # callback(scraped, failed)
        self._scraped = 0
        self._failed = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def crawl(self, seed_urls: list[str]) -> AsyncIterator[ScrapedPage]:
        """Crawl seed_urls breadth-first and yield one ScrapedPage per URL."""
        # Queue items: (url, depth, source_url)
        queue: deque[tuple[str, int, str | None]] = deque()

        seed_domains = {domain_of(u) for u in seed_urls}

        for url in seed_urls:
            normalised = normalise_url(url)
            uid = url_id(normalised)
            if uid not in self._visited:
                self._visited.add(uid)
                queue.append((normalised, 0, None))

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=self._cfg.request_timeout_seconds,
            headers={"User-Agent": self._cfg.user_agent},
        ) as client:
            while queue and (self._scraped + self._failed) < self._cfg.max_pages:
                # BFS: take up to `concurrency` items from the front
                batch = []
                while queue and len(batch) < self._cfg.concurrency:
                    batch.append(queue.popleft())

                tasks = [
                    self._fetch_page(client, url, depth, source_url, seed_domains)
                    for url, depth, source_url in batch
                ]
                results: list[tuple[ScrapedPage, list[str]]] = await asyncio.gather(*tasks)

                for page, child_links in results:
                    yield page

                    if self._on_progress:
                        self._on_progress(self._scraped, self._failed)

                    # Enqueue child links if within depth limit
                    if page.status == ScrapeStatus.SUCCESS and page.crawl_depth < self._cfg.max_depth:
                        for link in child_links:
                            uid = url_id(link)
                            if uid not in self._visited:
                                if not self._cfg.stay_on_domain or any(
                                    is_same_domain(link, d) for d in seed_domains
                                ):
                                    self._visited.add(uid)
                                    queue.append((link, page.crawl_depth + 1, page.url))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_page(
        self,
        client: httpx.AsyncClient,
        url: str,
        depth: int,
        source_url: str | None,
        seed_domains: set[str],
    ) -> tuple[ScrapedPage, list[str]]:
        """Fetch one URL, parse it, return (ScrapedPage, child_links)."""
        domain = domain_of(url)

        # Polite delay per domain
        await self._polite_delay(domain)

        # Robots.txt check
        if self._cfg.respect_robots_txt and not await self._robots_allowed(client, url):
            logger.debug("robots.txt disallows %s", url)
            page = self._make_skipped_page(url, depth, source_url, "robots.txt")
            return page, []

        try:
            response = await client.get(url)
            http_status = response.status_code

            if http_status != 200:
                self._failed += 1
                page = ScrapedPage(
                    id=url_id(url),
                    url=url,
                    source_url=source_url,
                    domain=domain,
                    crawl_depth=depth,
                    status=ScrapeStatus.FAILED,
                    http_status=http_status,
                    error_message=f"HTTP {http_status}",
                    crawl_session=self._session_id,
                )
                return page, []

            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type:
                page = self._make_skipped_page(
                    url, depth, source_url, f"non-HTML content-type: {content_type}"
                )
                return page, []

            html = response.text
            parsed: ParsedPage = parse_html(html, url, self._cfg.skip_extensions)

            self._scraped += 1
            page = ScrapedPage(
                id=url_id(url),
                url=url,
                source_url=source_url,
                domain=domain,
                title=parsed.title,
                text_content=parsed.text,
                crawl_depth=depth,
                word_count=parsed.word_count,
                links_found=len(parsed.links),
                status=ScrapeStatus.SUCCESS,
                http_status=http_status,
                content_hash=parsed.content_hash,
                crawl_session=self._session_id,
            )
            logger.info("[%d] Scraped (%d words, %d links): %s", depth, parsed.word_count, len(parsed.links), url)
            return page, parsed.links

        except httpx.TimeoutException:
            self._failed += 1
            page = ScrapedPage(
                id=url_id(url),
                url=url,
                source_url=source_url,
                domain=domain,
                crawl_depth=depth,
                status=ScrapeStatus.FAILED,
                error_message="Request timed out",
                crawl_session=self._session_id,
            )
            logger.warning("Timeout fetching %s", url)
            return page, []

        except Exception as exc:
            self._failed += 1
            page = ScrapedPage(
                id=url_id(url),
                url=url,
                source_url=source_url,
                domain=domain,
                crawl_depth=depth,
                status=ScrapeStatus.FAILED,
                error_message=str(exc)[:500],
                crawl_session=self._session_id,
            )
            logger.warning("Error fetching %s: %s", url, exc)
            return page, []

    async def _polite_delay(self, domain: str) -> None:
        """Wait if we've recently hit this domain."""
        last = self._domain_last_request.get(domain, 0)
        elapsed = time.monotonic() - last
        if elapsed < self._cfg.request_delay_seconds:
            await asyncio.sleep(self._cfg.request_delay_seconds - elapsed)
        self._domain_last_request[domain] = time.monotonic()

    async def _robots_allowed(self, client: httpx.AsyncClient, url: str) -> bool:
        """Check robots.txt for the given URL. Caches per domain."""
        parsed = urlparse(url)
        domain = parsed.netloc
        robots_url = f"{parsed.scheme}://{domain}/robots.txt"

        if domain not in self._robots_cache:
            rp = RobotFileParser()
            rp.set_url(robots_url)
            try:
                response = await client.get(robots_url)
                if response.status_code == 200:
                    rp.parse(response.text.splitlines())
                else:
                    # No robots.txt or inaccessible — allow everything
                    rp.parse([])
            except Exception:
                rp.parse([])
            self._robots_cache[domain] = rp

        return self._robots_cache[domain].can_fetch(self._cfg.user_agent, url)

    def _make_skipped_page(
        self,
        url: str,
        depth: int,
        source_url: str | None,
        reason: str,
    ) -> ScrapedPage:
        return ScrapedPage(
            id=url_id(url),
            url=url,
            source_url=source_url,
            domain=domain_of(url),
            crawl_depth=depth,
            status=ScrapeStatus.SKIPPED,
            error_message=reason,
            crawl_session=self._session_id,
        )

    @property
    def stats(self) -> dict:
        return {"scraped": self._scraped, "failed": self._failed}
