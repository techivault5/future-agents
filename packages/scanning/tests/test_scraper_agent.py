"""Tests for the WebScraperAgent (Snowflake and HTTP are mocked)."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from future_agents.core.base_agent import TaskContext
from future_agents.models.feedback import ExecutionOutcome
from scanning.config import CrawlerConfig, ScannerConfig, SnowflakeConfig
from scanning.models import ScrapeStatus, ScrapedPage
from scanning.scraper_agent import WebScraperAgent


def make_mock_sf() -> MagicMock:
    sf = MagicMock()
    sf.ensure_schema = MagicMock()
    sf.insert_session = MagicMock()
    sf.update_session = MagicMock()
    sf.upsert_pages = MagicMock(return_value=1)
    sf.already_crawled = MagicMock(return_value=set())
    sf.query_knowledge = MagicMock(return_value=[])
    sf.get_domain_summary = MagicMock(return_value=[])
    sf.close = MagicMock()
    return sf


def make_agent(mock_sf: MagicMock | None = None) -> WebScraperAgent:
    config = ScannerConfig.__new__(ScannerConfig)
    config.snowflake = MagicMock(spec=SnowflakeConfig)
    config.crawler = CrawlerConfig.__new__(CrawlerConfig)
    config.crawler.max_depth = 0
    config.crawler.max_pages = 5
    config.crawler.concurrency = 1
    config.crawler.request_delay_seconds = 0.0
    config.crawler.request_timeout_seconds = 5
    config.crawler.stay_on_domain = True
    config.crawler.skip_extensions = ()
    config.crawler.user_agent = "TestAgent/1.0"
    config.crawler.respect_robots_txt = False
    config.crawler.snowflake_batch_size = 10

    sf = mock_sf or make_mock_sf()
    agent = WebScraperAgent(config=config, snowflake_client=sf)
    return agent


class TestWebScraperAgentScrape:
    @pytest.mark.asyncio
    async def test_scrape_succeeds_with_valid_urls(self):
        mock_sf = make_mock_sf()
        agent = make_agent(mock_sf)
        await agent.initialize()

        simple_html = "<html><head><title>T</title></head><body><p>Hello world.</p></body></html>"

        def make_resp(text, status=200):
            r = MagicMock()
            r.status_code = status
            r.headers = {"content-type": "text/html"}
            r.text = text
            return r

        with patch("httpx.AsyncClient") as MockClient:
            mc = AsyncMock()
            mc.get = AsyncMock(return_value=make_resp(simple_html))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mc)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            ctx = TaskContext(
                intent="web.scrape",
                parameters={"urls": ["https://example.com/"]},
            )
            result = await agent.execute(ctx)

        assert result.outcome == ExecutionOutcome.SUCCESS
        assert "session_id" in result.data
        assert result.data["pages_scraped"] >= 1

    @pytest.mark.asyncio
    async def test_scrape_requires_urls_param(self):
        agent = make_agent()
        await agent.initialize()

        ctx = TaskContext(intent="web.scrape", parameters={})
        result = await agent.execute(ctx)

        assert result.outcome == ExecutionOutcome.FAILURE
        assert any("urls" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_scrape_respects_depth_override(self):
        agent = make_agent()
        await agent.initialize()

        simple_html = "<html><body><p>Test.</p></body></html>"

        with patch("httpx.AsyncClient") as MockClient:
            mc = AsyncMock()
            mc.get = AsyncMock(return_value=MagicMock(
                status_code=200,
                headers={"content-type": "text/html"},
                text=simple_html,
            ))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mc)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            ctx = TaskContext(
                intent="web.scrape",
                parameters={"urls": ["https://example.com/"], "max_depth": 0, "max_pages": 1},
            )
            result = await agent.execute(ctx)

        assert result.outcome == ExecutionOutcome.SUCCESS


class TestWebScraperAgentQuery:
    @pytest.mark.asyncio
    async def test_query_returns_results(self):
        mock_sf = make_mock_sf()
        mock_sf.query_knowledge = MagicMock(return_value=[
            {"URL": "https://example.com", "TITLE": "Example", "TEXT_CONTENT": "Hello world"},
        ])
        agent = make_agent(mock_sf)
        await agent.initialize()

        ctx = TaskContext(
            intent="web.knowledge.query",
            parameters={"query": "hello", "limit": 5},
        )
        result = await agent.execute(ctx)

        assert result.outcome == ExecutionOutcome.SUCCESS
        assert result.data["count"] == 1
        assert result.data["results"][0]["URL"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_query_sf_error_returns_failure(self):
        mock_sf = make_mock_sf()
        mock_sf.query_knowledge = MagicMock(side_effect=RuntimeError("DB down"))
        agent = make_agent(mock_sf)
        await agent.initialize()

        ctx = TaskContext(intent="web.knowledge.query", parameters={"query": "test"})
        result = await agent.execute(ctx)

        assert result.outcome == ExecutionOutcome.FAILURE
        assert any("Snowflake" in e for e in result.errors)


class TestWebScraperAgentMeta:
    def test_agent_type(self):
        agent = make_agent()
        assert agent.agent_type == "web_scraper"

    def test_capabilities(self):
        agent = make_agent()
        assert "web.scrape" in agent.capabilities
        assert "web.knowledge.query" in agent.capabilities

    @pytest.mark.asyncio
    async def test_unknown_intent_returns_failure(self):
        agent = make_agent()
        await agent.initialize()

        ctx = TaskContext(intent="unknown.intent", parameters={})
        result = await agent.execute(ctx)

        assert result.outcome == ExecutionOutcome.FAILURE

    @pytest.mark.asyncio
    async def test_assess_self(self):
        agent = make_agent()
        await agent.initialize()
        assessment = await agent.assess_self()

        assert "total_pages" in assessment
        assert "domains_crawled" in assessment
