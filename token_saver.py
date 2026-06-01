#!/usr/bin/env python3
"""token_saver.py — Drop this ONE file into any project to cut LLM token spend.

SHARE THIS FILE
---------------
Copy just this file. Only stdlib + the `anthropic` package are required.
Memory persists at ~/.cache/token-saver/memory.json across all your projects.

QUICK START
-----------
    pip install anthropic
    export ANTHROPIC_API_KEY=sk-ant-...

    # CLI
    python token_saver.py "What is a ReAct agent?"
    python token_saver.py --stats
    python token_saver.py --list
    python token_saver.py --fresh "force a fresh API call"
    python token_saver.py --forget "question to evict"
    python token_saver.py --clear

    # Python import
    from token_saver import TokenSaverAgent
    agent = TokenSaverAgent()
    r = agent.ask("What is prompt caching?")
    print(r.answer)   # concise answer
    print(r.cached)   # True = zero tokens spent
    print(r.tokens)   # 0 if cached, actual count otherwise
    print(agent.stats())

HOW IT SAVES TOKENS
--------------------
1. Exact cache  — identical question → returns stored answer instantly (0 tokens).
2. Fuzzy cache  — ≥80% keyword overlap → reuses cached answer (0 tokens).
3. Prompt cache — system prompt marked cache_control: ephemeral, billed once per
                  5-minute window regardless of how many questions you ask.
4. Terse system — built-in system prompt forces short, no-filler answers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__version__ = "1.0.0"
__all__ = ["TokenSaverAgent", "AskResult", "CachedEntry"]

logger = logging.getLogger(__name__)

_MEMORY_FILE = Path.home() / ".cache" / "token-saver" / "memory.json"

_SYSTEM = (
    "You are a concise, expert assistant. Hard rules:\n"
    "1. Answer in the fewest correct words. No preamble ('Sure!', 'Great question!', etc.).\n"
    "2. No postamble ('Let me know if...', 'Hope that helps!', etc.).\n"
    "3. Prefer code over prose for technical answers.\n"
    "4. Bullet points over paragraphs.\n"
    "5. Never restate the question."
)

try:
    import anthropic as _anthropic

    _SDK_OK = True
except ImportError:
    _SDK_OK = False


# ── Models ────────────────────────────────────────────────────────────────────


@dataclass
class CachedEntry:
    question: str
    answer: str
    model: str
    tokens_used: int
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    hit_count: int = 0


@dataclass
class AskResult:
    answer: str
    cached: bool
    tokens: int
    savings: int
    model: str


# ── Agent ─────────────────────────────────────────────────────────────────────


class TokenSaverAgent:
    """Memory-backed, prompt-cached LLM client — drop this file anywhere.

    Parameters
    ----------
    model           : Claude model string (default: claude-opus-4-7)
    system          : System prompt (default: built-in terse prompt)
    memory_file     : Path to persistent JSON cache (default: ~/.cache/token-saver/memory.json)
    fuzzy_threshold : Keyword-overlap ratio required for a fuzzy cache hit (default: 0.80)
    max_tokens      : Max tokens in Claude's response (default: 1024)
    """

    def __init__(
        self,
        model: str = "claude-opus-4-7",
        system: str = _SYSTEM,
        memory_file: Path | str | None = None,
        fuzzy_threshold: float = 0.80,
        max_tokens: int = 1024,
    ) -> None:
        self.model = model
        self.system = system
        self.fuzzy_threshold = fuzzy_threshold
        self.max_tokens = max_tokens
        self._path = Path(memory_file or _MEMORY_FILE)
        self._cache: dict[str, CachedEntry] = {}
        self._tokens_used = 0
        self._tokens_saved = 0
        self._client: Any = None  # lazy — created on first API call
        self._load()
        if not _SDK_OK:
            logger.warning("anthropic not installed — run: pip install anthropic")

    # ── Public ────────────────────────────────────────────────────────────────

    def ask(self, question: str, force_fresh: bool = False) -> AskResult:
        """Return an answer, using the cache when possible.

        Hits (in order):
          1. Exact match  → stored answer, 0 tokens
          2. Fuzzy match  → stored answer, 0 tokens, prefixed with [~cached]
          3. Fresh API call → real tokens, answer stored for next time
        """
        q = question.strip()
        if not force_fresh:
            hit = self._exact(q)
            if hit:
                hit.hit_count += 1
                self._tokens_saved += hit.tokens_used
                self._save()
                return AskResult(
                    answer=hit.answer,
                    cached=True,
                    tokens=0,
                    savings=hit.tokens_used,
                    model=hit.model,
                )
            hit = self._fuzzy(q)
            if hit:
                hit.hit_count += 1
                self._tokens_saved += hit.tokens_used
                self._save()
                return AskResult(
                    answer=f"[~cached from similar question]\n\n{hit.answer}",
                    cached=True,
                    tokens=0,
                    savings=hit.tokens_used,
                    model=hit.model,
                )
        return self._api(q)

    def forget(self, question: str) -> bool:
        """Remove one question from the cache. Returns True if it existed."""
        key = _hash(question)
        if key not in self._cache:
            return False
        del self._cache[key]
        self._save()
        return True

    def clear(self) -> int:
        """Remove all cached entries. Returns count deleted."""
        n = len(self._cache)
        self._cache.clear()
        self._save()
        return n

    def stats(self) -> dict[str, Any]:
        """Token-savings summary."""
        total = self._tokens_used + self._tokens_saved
        return {
            "cached_entries": len(self._cache),
            "total_hits": sum(e.hit_count for e in self._cache.values()),
            "tokens_used": self._tokens_used,
            "tokens_saved": self._tokens_saved,
            "savings_pct": round(self._tokens_saved / max(1, total) * 100, 1),
            "memory_file": str(self._path),
        }

    def list_cached(self, max_q_len: int = 80) -> list[dict[str, Any]]:
        """List all cached entries (questions truncated to max_q_len chars)."""
        return [
            {
                "question": e.question[:max_q_len] + ("…" if len(e.question) > max_q_len else ""),
                "tokens_used": e.tokens_used,
                "hit_count": e.hit_count,
                "created_at": e.created_at,
            }
            for e in self._cache.values()
        ]

    # ── Private ───────────────────────────────────────────────────────────────

    def _api(self, question: str) -> AskResult:
        if not _SDK_OK:
            raise RuntimeError(
                "anthropic package not installed.\n"
                "  pip install anthropic\n"
                "  export ANTHROPIC_API_KEY=sk-ant-..."
            )
        if self._client is None:
            self._client = _anthropic.Anthropic()

        resp = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[{"type": "text", "text": self.system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": question}],
        )
        answer = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        tokens = resp.usage.input_tokens + resp.usage.output_tokens
        self._tokens_used += tokens

        entry = CachedEntry(question=question, answer=answer, model=self.model, tokens_used=tokens)
        self._cache[_hash(question)] = entry
        self._save()
        return AskResult(answer=answer, cached=False, tokens=tokens, savings=0, model=self.model)

    def _exact(self, q: str) -> CachedEntry | None:
        return self._cache.get(_hash(q))

    def _fuzzy(self, q: str) -> CachedEntry | None:
        qw = _keywords(q)
        if not qw:
            return None
        best, best_e = 0.0, None
        for e in self._cache.values():
            ew = _keywords(e.question)
            if not ew:
                continue
            score = len(qw & ew) / max(len(qw | ew), 1)
            if score > best:
                best, best_e = score, e
        return best_e if best >= self.fuzzy_threshold else None

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
            self._tokens_used = raw.get("__tokens_used__", 0)
            self._tokens_saved = raw.get("__tokens_saved__", 0)
            for k, v in raw.items():
                if k.startswith("__"):
                    continue
                self._cache[k] = CachedEntry(**v)
        except Exception as exc:
            logger.warning("Could not load memory: %s", exc)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {
            "__tokens_used__": self._tokens_used,
            "__tokens_saved__": self._tokens_saved,
        }
        for k, e in self._cache.items():
            data[k] = asdict(e)
        self._path.write_text(json.dumps(data, indent=2))


# ── Helpers ───────────────────────────────────────────────────────────────────

_STOP = {
    "a",
    "an",
    "the",
    "is",
    "it",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "and",
    "or",
    "but",
    "how",
    "what",
    "why",
    "when",
    "where",
    "which",
    "who",
    "does",
    "do",
    "i",
    "my",
    "me",
    "you",
    "your",
    "be",
    "are",
    "was",
    "were",
    "this",
    "that",
    "with",
    "from",
    "by",
    "as",
    "if",
}


def _hash(text: str) -> str:
    return hashlib.sha256(text.lower().strip().encode()).hexdigest()[:16]


def _keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"\b[a-z]{2,}\b", text.lower()) if w not in _STOP}


# ── CLI ───────────────────────────────────────────────────────────────────────


def _cli() -> None:  # pragma: no cover
    p = argparse.ArgumentParser(
        prog="token_saver",
        description="Token-saving LLM CLI — ask once, cache forever.",
    )
    p.add_argument("question", nargs="?", help="Question to ask")
    p.add_argument("--fresh", "-f", action="store_true", help="Bypass cache for this call")
    p.add_argument("--stats", "-s", action="store_true", help="Show token-savings stats")
    p.add_argument("--list", "-l", action="store_true", help="List cached questions")
    p.add_argument("--clear", action="store_true", help="Delete all cached entries")
    p.add_argument("--forget", metavar="Q", help="Remove one question from cache")
    p.add_argument("--model", default="claude-opus-4-7", help="Claude model to use")
    p.add_argument("--version", action="version", version=f"token_saver {__version__}")
    args = p.parse_args()

    agent = TokenSaverAgent(model=args.model)

    if args.stats:
        s = agent.stats()
        print(f"Entries  : {s['cached_entries']}")
        print(f"Hits     : {s['total_hits']}")
        print(f"Used     : {s['tokens_used']:,} tokens")
        print(f"Saved    : {s['tokens_saved']:,} tokens")
        print(f"Savings  : {s['savings_pct']}%")
        print(f"File     : {s['memory_file']}")
        return

    if args.list:
        rows = agent.list_cached()
        if not rows:
            print("Cache is empty.")
            return
        for i, r in enumerate(rows, 1):
            print(f"{i:3}. [{r['tokens_used']}t · {r['hit_count']} hits] {r['question']}")
        return

    if args.clear:
        n = agent.clear()
        print(f"Cleared {n} entries.")
        return

    if args.forget:
        print("Removed." if agent.forget(args.forget) else "Not found in cache.")
        return

    if not args.question:
        p.print_help()
        sys.exit(1)

    result = agent.ask(args.question, force_fresh=args.fresh)
    print(result.answer)
    print()
    tag = (
        f"✓ cached — 0 tokens, saved ~{result.savings}"
        if result.cached
        else f"↓ fresh — {result.tokens} tokens used, cached for next time"
    )
    print(tag)


if __name__ == "__main__":
    _cli()
