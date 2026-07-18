-- ============================================================
-- Snowflake Schema: Web Knowledge Store
-- Used by the web scraper agent to persist crawled page data.
-- Other agents query this table to access extended knowledge.
-- ============================================================

-- Database and schema (adjust to your environment)
-- CREATE DATABASE IF NOT EXISTS FUTURE_AGENTS_DB;
-- CREATE SCHEMA IF NOT EXISTS FUTURE_AGENTS_DB.KNOWLEDGE;

-- ============================================================
-- Core table: one row per unique crawled URL
-- ============================================================
CREATE TABLE IF NOT EXISTS WEB_KNOWLEDGE (
    id             VARCHAR(64)    NOT NULL,          -- SHA-256 of the URL
    url            VARCHAR(4096)  NOT NULL,           -- Full URL scraped
    source_url     VARCHAR(4096),                    -- URL that linked here (NULL = seed)
    domain         VARCHAR(512)   NOT NULL,           -- e.g. "docs.python.org"
    title          VARCHAR(2048),                    -- <title> tag content
    text_content   TEXT,                             -- Cleaned visible text
    scraped_at     TIMESTAMP_NTZ  NOT NULL,          -- When scraping completed
    crawl_depth    INT            NOT NULL DEFAULT 0, -- 0 = seed URL
    word_count     INT            NOT NULL DEFAULT 0,
    links_found    INT            NOT NULL DEFAULT 0, -- Outbound links on page
    status         VARCHAR(32)    NOT NULL DEFAULT 'success', -- success | failed | skipped
    error_message  VARCHAR(2048),                    -- Populated on failure
    http_status    INT,                              -- HTTP response code
    content_hash   VARCHAR(64),                      -- SHA-256 of text_content (dedup)
    crawl_session  VARCHAR(64),                      -- Groups pages from one agent run
    PRIMARY KEY (id)
);

-- ============================================================
-- Index helpers (Snowflake uses clustering keys, not indexes)
-- ============================================================
ALTER TABLE WEB_KNOWLEDGE CLUSTER BY (domain, scraped_at);

-- ============================================================
-- Crawl sessions: one row per agent invocation
-- ============================================================
CREATE TABLE IF NOT EXISTS CRAWL_SESSIONS (
    session_id     VARCHAR(64)    NOT NULL,
    seed_urls      ARRAY,                            -- List of starting URLs
    max_depth      INT            NOT NULL DEFAULT 3,
    max_pages      INT            NOT NULL DEFAULT 500,
    started_at     TIMESTAMP_NTZ  NOT NULL,
    finished_at    TIMESTAMP_NTZ,
    pages_scraped  INT            NOT NULL DEFAULT 0,
    pages_failed   INT            NOT NULL DEFAULT 0,
    status         VARCHAR(32)    NOT NULL DEFAULT 'running', -- running | completed | failed
    PRIMARY KEY (session_id)
);

-- ============================================================
-- Convenience view: latest successful content per URL
-- ============================================================
CREATE OR REPLACE VIEW WEB_KNOWLEDGE_LATEST AS
SELECT *
FROM WEB_KNOWLEDGE
WHERE status = 'success'
QUALIFY ROW_NUMBER() OVER (PARTITION BY url ORDER BY scraped_at DESC) = 1;

-- ============================================================
-- Convenience view: domain-level crawl summary
-- ============================================================
CREATE OR REPLACE VIEW DOMAIN_CRAWL_SUMMARY AS
SELECT
    domain,
    COUNT(*)                                          AS total_pages,
    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END)  AS successful_pages,
    SUM(CASE WHEN status = 'failed'  THEN 1 ELSE 0 END)  AS failed_pages,
    SUM(word_count)                                   AS total_words,
    AVG(word_count)                                   AS avg_words_per_page,
    MAX(scraped_at)                                   AS last_scraped
FROM WEB_KNOWLEDGE
GROUP BY domain;
