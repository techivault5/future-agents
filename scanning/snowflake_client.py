"""Snowflake client — handles all DB interactions for the scanning pipeline.

Wraps snowflake-connector-python and exposes a clean async-friendly interface
that the scraper agent calls to persist and query pages.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from scanning.config import SnowflakeConfig
from scanning.models import CrawlSession, KnowledgeQuery, ScrapedPage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy import — only needed at runtime so tests can mock it
# ---------------------------------------------------------------------------
try:
    import snowflake.connector
    from snowflake.connector import DictCursor
    _SNOWFLAKE_AVAILABLE = True
except ImportError:
    _SNOWFLAKE_AVAILABLE = False


class SnowflakeClientError(RuntimeError):
    """Raised when a Snowflake operation fails."""


class SnowflakeClient:
    """Thread-safe Snowflake client for the web knowledge store.

    Usage::

        client = SnowflakeClient(config)
        client.ensure_schema()                    # run schema.sql DDL
        client.upsert_pages(pages)                # batch insert scraped pages
        results = client.query_knowledge(query)   # read by other agents
        client.close()
    """

    def __init__(self, config: SnowflakeConfig) -> None:
        if not _SNOWFLAKE_AVAILABLE:
            raise SnowflakeClientError(
                "snowflake-connector-python is not installed. "
                "Run: pip install snowflake-connector-python"
            )
        self._config = config
        self._conn = None
        self._connect()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        logger.info("Connecting to Snowflake account=%s db=%s", self._config.account, self._config.database)
        self._conn = snowflake.connector.connect(**self._config.as_connector_kwargs())
        logger.info("Snowflake connection established")

    def close(self) -> None:
        if self._conn and not self._conn.is_closed():
            self._conn.close()
            logger.info("Snowflake connection closed")

    def __enter__(self) -> "SnowflakeClient":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    @contextmanager
    def _cursor(self) -> Generator:
        """Yield a DictCursor; roll back on exception."""
        cur = self._conn.cursor(DictCursor)
        try:
            yield cur
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        finally:
            cur.close()

    # ------------------------------------------------------------------
    # Schema bootstrap
    # ------------------------------------------------------------------

    def ensure_schema(self) -> None:
        """Execute schema.sql to create tables and views if they don't exist."""
        schema_path = Path(__file__).parent / "schema.sql"
        sql = schema_path.read_text()

        # Split on semicolons, skip blank statements and comments-only blocks
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        with self._cursor() as cur:
            for stmt in statements:
                # Skip pure-comment blocks and the commented-out CREATE DATABASE lines
                lines = [l for l in stmt.splitlines() if not l.strip().startswith("--")]
                clean = "\n".join(lines).strip()
                if clean:
                    try:
                        cur.execute(clean)
                    except Exception as exc:
                        logger.warning("DDL statement skipped (%s): %.80s", exc, clean)
        logger.info("Snowflake schema verified / created")

    # ------------------------------------------------------------------
    # Crawl session tracking
    # ------------------------------------------------------------------

    def insert_session(self, session: CrawlSession) -> None:
        sql = """
        INSERT INTO CRAWL_SESSIONS
            (SESSION_ID, SEED_URLS, MAX_DEPTH, MAX_PAGES, STARTED_AT, STATUS)
        VALUES
            (%(SESSION_ID)s, PARSE_JSON(%(SEED_URLS)s), %(MAX_DEPTH)s,
             %(MAX_PAGES)s, %(STARTED_AT)s, %(STATUS)s)
        """
        row = session.to_snowflake_row()
        import json
        row["SEED_URLS"] = json.dumps(session.seed_urls)
        with self._cursor() as cur:
            cur.execute(sql, row)

    def update_session(self, session: CrawlSession) -> None:
        sql = """
        UPDATE CRAWL_SESSIONS SET
            FINISHED_AT   = %(FINISHED_AT)s,
            PAGES_SCRAPED = %(PAGES_SCRAPED)s,
            PAGES_FAILED  = %(PAGES_FAILED)s,
            STATUS        = %(STATUS)s
        WHERE SESSION_ID = %(SESSION_ID)s
        """
        with self._cursor() as cur:
            cur.execute(sql, session.to_snowflake_row())

    # ------------------------------------------------------------------
    # Page persistence
    # ------------------------------------------------------------------

    def upsert_pages(self, pages: list[ScrapedPage]) -> int:
        """Insert or replace pages in WEB_KNOWLEDGE. Returns number stored."""
        if not pages:
            return 0

        sql = """
        MERGE INTO WEB_KNOWLEDGE AS target
        USING (
            SELECT
                %(ID)s            AS id,
                %(URL)s           AS url,
                %(SOURCE_URL)s    AS source_url,
                %(DOMAIN)s        AS domain,
                %(TITLE)s         AS title,
                %(TEXT_CONTENT)s  AS text_content,
                %(SCRAPED_AT)s    AS scraped_at,
                %(CRAWL_DEPTH)s   AS crawl_depth,
                %(WORD_COUNT)s    AS word_count,
                %(LINKS_FOUND)s   AS links_found,
                %(STATUS)s        AS status,
                %(ERROR_MESSAGE)s AS error_message,
                %(HTTP_STATUS)s   AS http_status,
                %(CONTENT_HASH)s  AS content_hash,
                %(CRAWL_SESSION)s AS crawl_session
        ) AS source ON target.id = source.id
        WHEN MATCHED THEN UPDATE SET
            url           = source.url,
            source_url    = source.source_url,
            domain        = source.domain,
            title         = source.title,
            text_content  = source.text_content,
            scraped_at    = source.scraped_at,
            crawl_depth   = source.crawl_depth,
            word_count    = source.word_count,
            links_found   = source.links_found,
            status        = source.status,
            error_message = source.error_message,
            http_status   = source.http_status,
            content_hash  = source.content_hash,
            crawl_session = source.crawl_session
        WHEN NOT MATCHED THEN INSERT (
            id, url, source_url, domain, title, text_content,
            scraped_at, crawl_depth, word_count, links_found,
            status, error_message, http_status, content_hash, crawl_session
        ) VALUES (
            source.id, source.url, source.source_url, source.domain,
            source.title, source.text_content, source.scraped_at,
            source.crawl_depth, source.word_count, source.links_found,
            source.status, source.error_message, source.http_status,
            source.content_hash, source.crawl_session
        )
        """
        count = 0
        with self._cursor() as cur:
            for page in pages:
                cur.execute(sql, page.to_snowflake_row())
                count += 1
        logger.debug("Upserted %d pages to Snowflake", count)
        return count

    # ------------------------------------------------------------------
    # Knowledge retrieval (used by other agents)
    # ------------------------------------------------------------------

    def query_knowledge(self, query: KnowledgeQuery) -> list[dict]:
        """Return matching pages from WEB_KNOWLEDGE_LATEST view.

        Other agents call this to access the web knowledge base.
        """
        conditions = ["1=1"]
        params: dict = {}

        if query.domain:
            conditions.append("domain ILIKE %(domain)s")
            params["domain"] = f"%{query.domain}%"

        if query.min_word_count:
            conditions.append("word_count >= %(min_word_count)s")
            params["min_word_count"] = query.min_word_count

        if query.max_depth is not None:
            conditions.append("crawl_depth <= %(max_depth)s")
            params["max_depth"] = query.max_depth

        if query.session_id:
            conditions.append("crawl_session = %(session_id)s")
            params["session_id"] = query.session_id

        if query.query:
            # Snowflake full-text search via CONTAINS (requires search optimization)
            # Fall back to ILIKE for broad compatibility
            conditions.append(
                "(title ILIKE %(fts)s OR text_content ILIKE %(fts)s)"
            )
            params["fts"] = f"%{query.query}%"

        where = " AND ".join(conditions)
        sql = f"""
        SELECT id, url, domain, title, text_content, scraped_at,
               crawl_depth, word_count, links_found, crawl_session
        FROM WEB_KNOWLEDGE_LATEST
        WHERE {where}
        ORDER BY scraped_at DESC
        LIMIT %(limit)s
        """
        params["limit"] = query.limit

        with self._cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def get_page_by_url(self, url: str) -> Optional[dict]:
        """Fetch a single page by exact URL."""
        sql = """
        SELECT * FROM WEB_KNOWLEDGE_LATEST
        WHERE url = %(url)s
        LIMIT 1
        """
        with self._cursor() as cur:
            cur.execute(sql, {"url": url})
            rows = cur.fetchall()
            return rows[0] if rows else None

    def get_domain_summary(self) -> list[dict]:
        """Return per-domain crawl statistics."""
        sql = "SELECT * FROM DOMAIN_CRAWL_SUMMARY ORDER BY total_pages DESC"
        with self._cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()

    def already_crawled(self, url_ids: list[str]) -> set[str]:
        """Return the subset of SHA-256 URL IDs already in the DB."""
        if not url_ids:
            return set()
        placeholders = ", ".join([f"'{uid}'" for uid in url_ids])
        sql = f"SELECT id FROM WEB_KNOWLEDGE WHERE id IN ({placeholders})"
        with self._cursor() as cur:
            cur.execute(sql)
            return {row["ID"] for row in cur.fetchall()}
