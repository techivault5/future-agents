#!/usr/bin/env python3
"""Finance Advisor knowledge gatherer.

Loads the curated knowledge base (knowledge/*.json) into a KnowledgeStore
and builds the Finance Advisor AgentDefinition. Optionally refreshes the
latest uploads from curated YouTube finance channels via the YouTube Data
API v3 (requires YOUTUBE_API_KEY).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
ROOT = PROJECT_DIR.parent.parent
sys.path.insert(0, str(ROOT))

from future_agents.definitions.loader import DefinitionLoader  # noqa: E402
from future_agents.definitions.schema import AgentDefinition  # noqa: E402
from future_agents.infrastructure.knowledge_store import KnowledgeStore  # noqa: E402
from future_agents.models.knowledge import KnowledgeEntry  # noqa: E402

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = PROJECT_DIR / "knowledge"
AGENT_FILE = PROJECT_DIR / "agent.json"

YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3/search"

# Channels to refresh via --youtube; matched against the curated catalog
YOUTUBE_QUERIES = [
    "The Money Guy Show",
    "Caleb Hammer Financial Audit",
    "The Ramsey Show",
    "I Will Teach You To Be Rich",
    "The Financial Diet",
    "Two Cents PBS",
    "The Plain Bagel",
]


def load_knowledge(store: KnowledgeStore | None = None) -> KnowledgeStore:
    """Load all knowledge/*.json files into a KnowledgeStore."""
    store = store or KnowledgeStore()
    for path in sorted(KNOWLEDGE_DIR.glob("*.json")):
        data = json.loads(path.read_text())
        domain = data["domain"]
        for raw in data["entries"]:
            store.add(
                KnowledgeEntry(
                    title=raw["title"],
                    domain=domain,
                    content=raw["content"],
                    tags=raw.get("tags", []),
                    confidence=raw.get("confidence", 0.8),
                    source_agent="finance_advisor.gather",
                )
            )
    return store


def build_advisor() -> AgentDefinition:
    """Load the Finance Advisor agent definition."""
    return DefinitionLoader().load_file(AGENT_FILE)


def fetch_youtube_latest(api_key: str, query: str, max_results: int = 3) -> list[dict]:
    """Fetch latest matching videos for a channel query via YouTube Data API v3."""
    params = urllib.parse.urlencode(
        {
            "part": "snippet",
            "q": query,
            "type": "video",
            "order": "date",
            "maxResults": max_results,
            "key": api_key,
        }
    )
    try:
        with urllib.request.urlopen(f"{YOUTUBE_API_URL}?{params}", timeout=30) as resp:
            payload = json.load(resp)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as err:
        logger.warning("YouTube fetch failed for %r: %s", query, err)
        return []
    videos = []
    for item in payload.get("items", []):
        snippet = item.get("snippet", {})
        video_id = item.get("id", {}).get("videoId")
        if not video_id:
            continue
        videos.append(
            {
                "title": snippet.get("title", ""),
                "channel": snippet.get("channelTitle", ""),
                "published_at": snippet.get("publishedAt", ""),
                "description": snippet.get("description", ""),
                "url": f"https://www.youtube.com/watch?v={video_id}",
            }
        )
    return videos


def refresh_youtube(store: KnowledgeStore) -> int:
    """Pull latest uploads from curated channels into the store.

    Requires YOUTUBE_API_KEY. Returns number of entries added.
    """
    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    if not api_key:
        logger.warning("YOUTUBE_API_KEY not set — skipping YouTube refresh")
        return 0
    added = 0
    for query in YOUTUBE_QUERIES:
        for video in fetch_youtube_latest(api_key, query):
            store.add(
                KnowledgeEntry(
                    title=f"[video] {video['title']}",
                    domain="finance.youtube",
                    content=(
                        f"{video['channel']} — {video['published_at']}\n"
                        f"{video['description']}\n{video['url']}"
                    ),
                    tags=["youtube", "video", "latest"],
                    confidence=0.6,  # unvetted; curated entries carry higher confidence
                    source_agent="finance_advisor.youtube_refresh",
                )
            )
            added += 1
    return added


def main() -> int:
    parser = argparse.ArgumentParser(description="Finance Advisor knowledge gatherer")
    parser.add_argument("--search", help="Search the knowledge base")
    parser.add_argument("--domain", help="Filter search/list by domain")
    parser.add_argument("--youtube", action="store_true", help="Refresh latest channel uploads")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    store = load_knowledge()
    if args.youtube:
        added = refresh_youtube(store)
        print(f"YouTube refresh: {added} entries added")

    if args.search:
        results = store.search(args.search, domain=args.domain)
        print(f"{len(results)} result(s) for {args.search!r}:")
        for entry in results:
            print(f"\n## {entry.title}  [{entry.domain}] (confidence={entry.confidence})")
            print(entry.content)
    else:
        stats = store.stats()
        defn = build_advisor()
        warnings = DefinitionLoader().validate(defn)
        print(f"Agent: {defn.name} v{defn.version} — {len(defn.skills)} skills")
        for warning in warnings:
            print(f"  warn: {warning}")
        print(f"Knowledge: {stats['total_entries']} entries across {len(stats['domains'])} domains")
        for domain in sorted(stats["domains"]):
            print(f"  {domain}: {len(store.by_domain(domain))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
