"""Web Scraper Agent — crawls sites and stores knowledge in Snowflake.

Extends BaseAgent so it integrates with the existing multi-agent system.
Other agents can read the knowledge via the `web.knowledge.query` intent.

Intents handled:
    web.scrape        — crawl one or more seed URLs and persist to Snowflake
    web.knowledge.query — search the web knowledge store
    web.session.status  — check the status of a previous crawl session
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from future_agents.core.base_agent import BaseAgent, TaskContext, TaskResult
from future_agents.models.feedback import ExecutionOutcome

from scanning.config import ScannerConfig
from scanning.crawler import Crawler
from scanning.models import CrawlSession, KnowledgeQuery, ScrapedPage
from scanning.snowflake_client import SnowflakeClient

logger = logging.getLogger(__name__)


class WebScraperAgent(BaseAgent):
    """Crawls websites and stores extracted text in Snowflake for other agents.

    Example task context for ``web.scrape``::

        TaskContext(
            intent="web.scrape",
            parameters={
                "urls": ["https://docs.python.org/3/", "https://peps.python.org/"],
                "max_depth": 2,       # optional, overrides config
                "max_pages": 100,     # optional, overrides config
                "stay_on_domain": True,
            },
        )

    Example task context for ``web.knowledge.query``::

        TaskContext(
            intent="web.knowledge.query",
            parameters={
                "query": "asyncio event loop",
                "domain": "docs.python.org",
                "limit": 20,
            },
        )
    """

    def __init__(
        self,
        config: ScannerConfig | None = None,
        snowflake_client: SnowflakeClient | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._config = config or ScannerConfig.from_env()
        # Allow injecting a pre-built client (useful for testing)
        self._sf: SnowflakeClient | None = snowflake_client
        self._active_sessions: dict[str, CrawlSession] = {}

    # ------------------------------------------------------------------
    # BaseAgent contract
    # ------------------------------------------------------------------

    @property
    def agent_type(self) -> str:
        return "web_scraper"

    @property
    def capabilities(self) -> list[str]:
        return [
            "web.scrape",
            "web.knowledge.query",
            "web.session.status",
        ]

    async def initialize(self) -> None:
        await super().initialize()
        if self._sf is None:
            self._sf = SnowflakeClient(self._config.snowflake)
            self._sf.ensure_schema()
        logger.info("WebScraperAgent ready — Snowflake schema verified")

    async def shutdown(self) -> None:
        if self._sf:
            self._sf.close()
        await super().shutdown()

    async def assess_self(self) -> dict[str, Any]:
        summary = self._sf.get_domain_summary() if self._sf else []
        return {
            "active_sessions": len(self._active_sessions),
            "domains_crawled": len(summary),
            "total_pages": sum(r.get("TOTAL_PAGES", 0) for r in summary),
        }

    # ------------------------------------------------------------------
    # Task routing
    # ------------------------------------------------------------------

    async def _execute(self, context: TaskContext) -> TaskResult:
        handlers = {
            "web.scrape": self._handle_scrape,
            "web.knowledge.query": self._handle_query,
            "web.session.status": self._handle_session_status,
        }
        handler = handlers.get(context.intent)
        if not handler:
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.FAILURE,
                errors=[f"Unknown intent: {context.intent}"],
            )
        return await handler(context)

    # ------------------------------------------------------------------
    # Intent: web.scrape
    # ------------------------------------------------------------------

    async def _handle_scrape(self, context: TaskContext) -> TaskResult:
        params = context.parameters
        urls: list[str] = params.get("urls", [])

        if not urls:
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.FAILURE,
                errors=["Parameter 'urls' is required and must be a non-empty list"],
            )

        # Allow per-task overrides of crawler tuning
        cfg = self._config.crawler
        if "max_depth" in params:
            cfg.max_depth = int(params["max_depth"])
        if "max_pages" in params:
            cfg.max_pages = int(params["max_pages"])
        if "stay_on_domain" in params:
            cfg.stay_on_domain = bool(params["stay_on_domain"])

        session_id = uuid.uuid4().hex
        session = CrawlSession(
            session_id=session_id,
            seed_urls=urls,
            max_depth=cfg.max_depth,
            max_pages=cfg.max_pages,
        )
        self._active_sessions[session_id] = session

        try:
            self._sf.insert_session(session)
        except Exception as exc:
            logger.warning("Could not persist crawl session: %s", exc)

        logger.info(
            "Starting crawl session=%s seeds=%d depth=%d pages=%d",
            session_id, len(urls), cfg.max_depth, cfg.max_pages,
        )

        await self.emit("web.scrape.started", {"session_id": session_id, "seeds": urls})

        # Determine which URLs are already in Snowflake (skip re-crawl)
        from scanning.html_parser import url_id
        seed_ids = [url_id(u) for u in urls]
        try:
            existing = self._sf.already_crawled(seed_ids)
        except Exception:
            existing = set()

        crawler = Crawler(
            config=cfg,
            session_id=session_id,
            already_crawled=existing,
        )

        batch: list[ScrapedPage] = []
        total_scraped = 0
        total_failed = 0

        async for page in crawler.crawl(urls):
            batch.append(page)

            if len(batch) >= cfg.snowflake_batch_size:
                stored = self._flush_batch(batch)
                total_scraped += stored
                batch = []

        # Flush remaining
        if batch:
            stored = self._flush_batch(batch)
            total_scraped += stored

        stats = crawler.stats
        total_failed = stats["failed"]

        # Update session record
        session.finished_at = datetime.now(timezone.utc)
        session.pages_scraped = stats["scraped"]
        session.pages_failed = stats["failed"]
        session.status = "completed"
        self._active_sessions.pop(session_id, None)

        try:
            self._sf.update_session(session)
        except Exception as exc:
            logger.warning("Could not update crawl session: %s", exc)

        await self.emit(
            "web.scrape.completed",
            {
                "session_id": session_id,
                "pages_scraped": stats["scraped"],
                "pages_failed": stats["failed"],
            },
        )

        logger.info(
            "Crawl complete session=%s scraped=%d failed=%d",
            session_id, stats["scraped"], stats["failed"],
        )

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={
                "session_id": session_id,
                "pages_scraped": stats["scraped"],
                "pages_failed": stats["failed"],
                "seeds": urls,
            },
        )

    def _flush_batch(self, batch: list[ScrapedPage]) -> int:
        try:
            return self._sf.upsert_pages(batch)
        except Exception as exc:
            logger.error("Snowflake batch insert failed: %s", exc)
            return 0

    # ------------------------------------------------------------------
    # Intent: web.knowledge.query  (read path for other agents)
    # ------------------------------------------------------------------

    async def _handle_query(self, context: TaskContext) -> TaskResult:
        params = context.parameters
        query = KnowledgeQuery(
            query=params.get("query"),
            domain=params.get("domain"),
            min_word_count=params.get("min_word_count", 0),
            max_depth=params.get("max_depth"),
            limit=params.get("limit", 50),
            session_id=params.get("session_id"),
        )

        try:
            results = self._sf.query_knowledge(query)
        except Exception as exc:
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.FAILURE,
                errors=[f"Snowflake query failed: {exc}"],
            )

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={"results": results, "count": len(results)},
        )

    # ------------------------------------------------------------------
    # Intent: web.session.status
    # ------------------------------------------------------------------

    async def _handle_session_status(self, context: TaskContext) -> TaskResult:
        session_id = context.parameters.get("session_id")
        active = self._active_sessions.get(session_id) if session_id else None

        if active:
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.SUCCESS,
                data={"session": active.model_dump(mode="json"), "state": "running"},
            )

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={"state": "not_found_or_completed", "session_id": session_id},
        )
