#!/usr/bin/env python3
"""Quick CLI for the TokenSaverAgent — use from VS Code terminal.

Usage
-----
    python scripts/ask.py "What is a ReAct agent?"
    python scripts/ask.py --stats
    python scripts/ask.py --list
    python scripts/ask.py --clear
    python scripts/ask.py --fresh "Explain prompt caching"

The first call fetches from Claude and caches. Every subsequent identical (or
near-identical) question is answered from cache at zero token cost.

Set ANTHROPIC_API_KEY in your environment before first use:
    export ANTHROPIC_API_KEY=sk-ant-...
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from future_agents.agents.token_saver_agent import TokenSaverAgent  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Token-saving LLM CLI")
    parser.add_argument("question", nargs="?", help="Question to ask")
    parser.add_argument("--fresh", "-f", action="store_true", help="Bypass cache")
    parser.add_argument("--stats", "-s", action="store_true", help="Show token savings stats")
    parser.add_argument("--list", "-l", action="store_true", help="List cached questions")
    parser.add_argument("--clear", action="store_true", help="Clear all cached entries")
    parser.add_argument("--forget", metavar="QUESTION", help="Remove one question from cache")
    parser.add_argument("--model", default="claude-opus-4-7", help="Claude model to use")
    args = parser.parse_args()

    agent = TokenSaverAgent(model=args.model)

    if args.stats:
        s = agent.stats()
        print(f"Cached entries : {s['cached_entries']}")
        print(f"Cache hits     : {s['total_hits']}")
        print(f"Tokens used    : {s['tokens_used']:,}")
        print(f"Tokens saved   : {s['tokens_saved']:,}")
        print(f"Savings        : {s['savings_pct']}%")
        print(f"Memory file    : {s['memory_file']}")
        return

    if args.list:
        entries = agent.list_cached()
        if not entries:
            print("Cache is empty.")
            return
        for i, e in enumerate(entries, 1):
            print(f"{i:3}. [{e['tokens_used']} tok, {e['hit_count']} hits] {e['question']}")
        return

    if args.clear:
        n = agent.clear()
        print(f"Cleared {n} cached entries.")
        return

    if args.forget:
        removed = agent.forget(args.forget)
        print("Removed." if removed else "Not found in cache.")
        return

    if not args.question:
        parser.print_help()
        sys.exit(1)

    result = agent.ask(args.question, force_fresh=args.fresh)

    print(result.answer)
    print()
    if result.cached:
        print(f"✓ cached — 0 tokens used, ~{result.savings} tokens saved")
    else:
        print(f"↓ fresh — {result.tokens} tokens used, cached for next time")


if __name__ == "__main__":
    main()
