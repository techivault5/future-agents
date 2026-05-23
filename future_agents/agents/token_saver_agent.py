"""Token Saver Agent — memory-backed, prompt-cached LLM client.

Import and use anywhere to slash token spend:
    from future_agents.agents.token_saver_agent import TokenSaverAgent
    agent = TokenSaverAgent()
    reply = agent.ask("What is the capital of France?")
    print(reply["answer"])   # "Paris"
    print(reply["cached"])   # True on second call — zero tokens spent
    print(reply["tokens"])   # 0 when cached, actual usage otherwise

Memory persists across Python sessions in ~/.cache/future-agents/memory.json.
The Claude system prompt is pinned with prompt caching so it's only billed once
per cache TTL window (5 minutes), regardless of how many questions you ask.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "future-agents"
_DEFAULT_MEMORY_FILE = _DEFAULT_CACHE_DIR / "memory.json"

_DEFAULT_SYSTEM = (
    "You are a concise, expert assistant. Rules:\n"
    "1. Answer in the fewest correct words. No preamble or filler.\n"
    "2. Prefer code over prose for technical answers.\n"
    "3. No 'Let me know if...' endings.\n"
    "4. Use bullet points, not paragraphs.\n"
    "5. Skip restating the question."
)

try:
    import anthropic as _anthropic

    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False


# ── Data models ───────────────────────────────────────────────────────────────


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
    savings: int  # tokens saved vs. a fresh call (estimated)
    model: str


# ── Agent ─────────────────────────────────────────────────────────────────────


class TokenSaverAgent:
    """Memory-backed LLM client that eliminates repeated token spend.

    Features
    --------
    - **Exact-match cache**: identical questions return the stored answer instantly
      (zero API tokens).
    - **Fuzzy cache**: near-duplicate questions (≥80 % keyword overlap) reuse
      cached answers instead of making a fresh call.
    - **Prompt caching**: the system prompt is marked ``cache_control: ephemeral``
      so Claude only bills input tokens for it once per 5-minute window.
    - **Persistent memory**: the cache survives process restarts via a JSON file
      at ``~/.cache/future-agents/memory.json``.
    - **Stats tracking**: ``agent.stats()`` shows total tokens saved so far.
    """

    def __init__(
        self,
        model: str = "claude-opus-4-7",
        system: str = _DEFAULT_SYSTEM,
        memory_file: Path | str | None = None,
        fuzzy_threshold: float = 0.80,
        max_tokens: int = 1024,
    ) -> None:
        self.model = model
        self.system = system
        self.fuzzy_threshold = fuzzy_threshold
        self.max_tokens = max_tokens
        self._memory_file = Path(memory_file or _DEFAULT_MEMORY_FILE)
        self._memory: dict[str, CachedEntry] = {}
        self._total_tokens_used = 0
        self._total_tokens_saved = 0
        self._load()

        self._client: Any = None  # lazy-initialized on first API call
        if not _SDK_AVAILABLE:
            logger.warning(
                "anthropic SDK not installed — only cached answers will work. "
                "Run: pip install anthropic"
            )

    # ── Public API ────────────────────────────────────────────────────────────

    def ask(self, question: str, force_fresh: bool = False) -> AskResult:
        """Ask a question, returning a cached answer when available.

        Parameters
        ----------
        question:    The question or prompt.
        force_fresh: Skip cache and always call the API.

        Returns
        -------
        AskResult with .answer, .cached, .tokens, .savings, .model
        """
        question = question.strip()

        if not force_fresh:
            # 1. Exact match
            exact = self._exact_lookup(question)
            if exact:
                exact.hit_count += 1
                self._total_tokens_saved += exact.tokens_used
                self._save()
                return AskResult(
                    answer=exact.answer,
                    cached=True,
                    tokens=0,
                    savings=exact.tokens_used,
                    model=exact.model,
                )

            # 2. Fuzzy match
            fuzzy = self._fuzzy_lookup(question)
            if fuzzy:
                fuzzy.hit_count += 1
                self._total_tokens_saved += fuzzy.tokens_used
                self._save()
                note = f"[~cached from similar question]\n\n{fuzzy.answer}"
                return AskResult(
                    answer=note,
                    cached=True,
                    tokens=0,
                    savings=fuzzy.tokens_used,
                    model=fuzzy.model,
                )

        # 3. Fresh API call
        return self._call_api(question)

    def forget(self, question: str) -> bool:
        """Remove a specific question from the cache."""
        key = self._hash(question)
        if key in self._memory:
            del self._memory[key]
            self._save()
            return True
        return False

    def clear(self) -> int:
        """Clear all cached entries. Returns count removed."""
        count = len(self._memory)
        self._memory.clear()
        self._save()
        return count

    def stats(self) -> dict[str, Any]:
        """Return token-savings statistics."""
        entries = list(self._memory.values())
        return {
            "cached_entries": len(entries),
            "total_hits": sum(e.hit_count for e in entries),
            "tokens_used": self._total_tokens_used,
            "tokens_saved": self._total_tokens_saved,
            "savings_pct": (
                round(
                    self._total_tokens_saved
                    / max(1, self._total_tokens_used + self._total_tokens_saved)
                    * 100,
                    1,
                )
            ),
            "memory_file": str(self._memory_file),
        }

    def list_cached(self) -> list[dict[str, Any]]:
        """List all cached questions (truncated for readability)."""
        return [
            {
                "question": e.question[:80] + ("…" if len(e.question) > 80 else ""),
                "tokens_used": e.tokens_used,
                "hit_count": e.hit_count,
                "created_at": e.created_at,
            }
            for e in self._memory.values()
        ]

    # ── Internals ─────────────────────────────────────────────────────────────

    def _call_api(self, question: str) -> AskResult:
        if not _SDK_AVAILABLE:
            raise RuntimeError(
                "anthropic SDK not installed. Run: pip install anthropic\n"
                "Or set ANTHROPIC_API_KEY and install the package."
            )
        if self._client is None:
            self._client = _anthropic.Anthropic()

        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[
                {
                    "type": "text",
                    "text": self.system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": question}],
        )

        answer = "".join(
            b.text for b in response.content if hasattr(b, "text") and b.type == "text"
        )
        tokens = response.usage.input_tokens + response.usage.output_tokens
        self._total_tokens_used += tokens

        # Cache for next time
        entry = CachedEntry(
            question=question,
            answer=answer,
            model=self.model,
            tokens_used=tokens,
        )
        self._memory[self._hash(question)] = entry
        self._save()

        return AskResult(
            answer=answer,
            cached=False,
            tokens=tokens,
            savings=0,
            model=self.model,
        )

    def _exact_lookup(self, question: str) -> CachedEntry | None:
        return self._memory.get(self._hash(question))

    def _fuzzy_lookup(self, question: str) -> CachedEntry | None:
        q_words = self._keywords(question)
        if not q_words:
            return None
        best_score = 0.0
        best_entry: CachedEntry | None = None
        for entry in self._memory.values():
            e_words = self._keywords(entry.question)
            if not e_words:
                continue
            overlap = len(q_words & e_words) / max(len(q_words | e_words), 1)
            if overlap > best_score:
                best_score = overlap
                best_entry = entry
        return best_entry if best_score >= self.fuzzy_threshold else None

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.lower().strip().encode()).hexdigest()[:16]

    @staticmethod
    def _keywords(text: str) -> set[str]:
        stop = {
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
        }
        return {w for w in re.findall(r"\b[a-z]{2,}\b", text.lower()) if w not in stop}

    def _load(self) -> None:
        if not self._memory_file.exists():
            return
        try:
            raw = json.loads(self._memory_file.read_text())
            self._total_tokens_used = raw.get("_tokens_used", 0)
            self._total_tokens_saved = raw.get("_tokens_saved", 0)
            for key, val in raw.items():
                if key.startswith("_"):
                    continue
                self._memory[key] = CachedEntry(**val)
        except Exception as exc:
            logger.warning("Could not load memory file: %s", exc)

    def _save(self) -> None:
        self._memory_file.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {
            "_tokens_used": self._total_tokens_used,
            "_tokens_saved": self._total_tokens_saved,
        }
        for key, entry in self._memory.items():
            data[key] = asdict(entry)
        self._memory_file.write_text(json.dumps(data, indent=2))
