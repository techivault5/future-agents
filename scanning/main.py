"""CLI entry point for the web scraper agent.

Usage examples:

    # Crawl a single site
    python -m scanning.main scrape https://docs.python.org/3/

    # Crawl multiple seeds with custom limits
    python -m scanning.main scrape \
        https://docs.python.org/3/ \
        https://peps.python.org/ \
        --depth 2 \
        --pages 200 \
        --no-stay-on-domain

    # Query the knowledge base
    python -m scanning.main query "asyncio event loop" --domain docs.python.org --limit 10

    # Show per-domain crawl summary
    python -m scanning.main summary
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)


async def cmd_scrape(args: argparse.Namespace) -> None:
    from scanning.config import ScannerConfig
    from scanning.scraper_agent import WebScraperAgent
    from future_agents.core.base_agent import TaskContext

    config = ScannerConfig.from_env()

    if args.depth is not None:
        config.crawler.max_depth = args.depth
    if args.pages is not None:
        config.crawler.max_pages = args.pages
    if args.no_stay_on_domain:
        config.crawler.stay_on_domain = False

    agent = WebScraperAgent(config=config)
    await agent.initialize()

    context = TaskContext(
        intent="web.scrape",
        parameters={"urls": args.urls},
    )

    result = await agent.execute(context)

    if result.outcome.value == "success":
        print(json.dumps(result.data, indent=2, default=str))
    else:
        print("Scrape failed:", result.errors, file=sys.stderr)
        sys.exit(1)

    await agent.shutdown()


async def cmd_query(args: argparse.Namespace) -> None:
    from scanning.config import ScannerConfig
    from scanning.scraper_agent import WebScraperAgent
    from future_agents.core.base_agent import TaskContext

    config = ScannerConfig.from_env()
    agent = WebScraperAgent(config=config)
    await agent.initialize()

    params: dict = {"query": args.query, "limit": args.limit}
    if args.domain:
        params["domain"] = args.domain

    context = TaskContext(intent="web.knowledge.query", parameters=params)
    result = await agent.execute(context)

    if result.outcome.value == "success":
        rows = result.data.get("results", [])
        for row in rows:
            print(f"\n{'='*60}")
            print(f"URL:   {row.get('URL', row.get('url', ''))}")
            print(f"Title: {row.get('TITLE', row.get('title', ''))}")
            snippet = (row.get('TEXT_CONTENT') or row.get('text_content') or '')[:300]
            print(f"Snippet: {snippet}...")
        print(f"\nTotal: {result.data['count']} pages")
    else:
        print("Query failed:", result.errors, file=sys.stderr)
        sys.exit(1)

    await agent.shutdown()


async def cmd_summary(args: argparse.Namespace) -> None:
    from scanning.config import ScannerConfig
    from scanning.snowflake_client import SnowflakeClient

    config = ScannerConfig.from_env()
    client = SnowflakeClient(config.snowflake)
    rows = client.get_domain_summary()
    client.close()

    print(f"{'DOMAIN':<40} {'PAGES':>8} {'OK':>6} {'FAIL':>6} {'WORDS':>10}")
    print("-" * 75)
    for r in rows:
        print(
            f"{str(r.get('DOMAIN','')):<40} "
            f"{r.get('TOTAL_PAGES', 0):>8} "
            f"{r.get('SUCCESSFUL_PAGES', 0):>6} "
            f"{r.get('FAILED_PAGES', 0):>6} "
            f"{r.get('TOTAL_WORDS', 0):>10,}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scanning",
        description="Web scraper agent — crawl sites and store knowledge in Snowflake",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- scrape ---
    sp = sub.add_parser("scrape", help="Crawl one or more URLs and store text in Snowflake")
    sp.add_argument("urls", nargs="+", help="Seed URLs to crawl")
    sp.add_argument("--depth", type=int, default=None, help="Max crawl depth (default: from env/config)")
    sp.add_argument("--pages", type=int, default=None, help="Max pages per session (default: from env/config)")
    sp.add_argument("--no-stay-on-domain", action="store_true", help="Follow links off the seed domain")

    # --- query ---
    qp = sub.add_parser("query", help="Search the web knowledge base")
    qp.add_argument("query", help="Search terms")
    qp.add_argument("--domain", default=None, help="Filter by domain")
    qp.add_argument("--limit", type=int, default=10, help="Max results (default: 10)")

    # --- summary ---
    sub.add_parser("summary", help="Show per-domain crawl statistics")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "scrape": cmd_scrape,
        "query": cmd_query,
        "summary": cmd_summary,
    }
    asyncio.run(dispatch[args.command](args))


if __name__ == "__main__":
    main()
