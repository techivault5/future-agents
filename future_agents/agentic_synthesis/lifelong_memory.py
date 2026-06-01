"""Lifelong Memory — cross-session tiered memory: episodic, semantic, procedural.

Synthesises:
  MemGPT   → tiered memory with eviction policy (main/archival/working)
  Voyager  → persistent skill library that grows over time
  Reflexion → stores verbal traces for future retrieval
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path.home() / ".cache" / "future-agents" / "lifelong_memory.json"

_STOP_WORDS = {
    "a",
    "an",
    "the",
    "is",
    "it",
    "to",
    "for",
    "of",
    "in",
    "on",
    "at",
    "and",
    "or",
    "not",
    "be",
    "was",
    "with",
}


@dataclass
class MemoryEntry:
    key: str
    content: str
    memory_type: str  # "episodic" | "semantic" | "procedural"
    tags: list[str] = field(default_factory=list)
    access_count: int = 0
    importance: float = 0.5  # 0.0-1.0; high importance survives eviction
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_accessed: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        self.access_count += 1
        self.last_accessed = datetime.now(timezone.utc).isoformat()


@dataclass
class MemorySearchResult:
    entry: MemoryEntry
    match_type: str  # "exact" | "keyword" | "tag"
    score: float  # 0.0-1.0


class LifelongMemory:
    """Cross-session tiered memory with keyword + tag retrieval and importance-based eviction.

    Three memory types (inspired by cognitive science + MemGPT):
      episodic   — what happened (task traces, interaction history)
      semantic   — what is known (synthesised facts, patterns)
      procedural — how to do things (reusable tool chains, strategies)
    """

    def __init__(self, memory_path: Path | None = None, max_entries: int = 2000) -> None:
        self._path = memory_path or _DEFAULT_PATH
        self._max = max_entries
        self._entries: dict[str, MemoryEntry] = {}
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
            for k, v in raw.items():
                self._entries[k] = MemoryEntry(**v)
        except Exception:
            self._entries = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps({k: v.__dict__ for k, v in self._entries.items()}, indent=2))

    # ── Core API ──────────────────────────────────────────────────────────────

    def remember(
        self,
        content: str,
        memory_type: str = "episodic",
        tags: list[str] | None = None,
        importance: float = 0.5,
        metadata: dict | None = None,
        persist: bool = True,
    ) -> str:
        """Store content. Returns stable key (SHA-256 prefix). Deduplicates on content."""
        key = hashlib.sha256(content.encode()).hexdigest()[:16]
        if key in self._entries:
            self._entries[key].touch()
            return key

        self._entries[key] = MemoryEntry(
            key=key,
            content=content,
            memory_type=memory_type,
            tags=tags or [],
            importance=max(0.0, min(1.0, importance)),
            metadata=metadata or {},
        )
        self._consolidate()
        if persist:
            self._save()
        return key

    def recall(
        self,
        query: str,
        memory_type: str | None = None,
        tags: list[str] | None = None,
        top_k: int = 5,
    ) -> list[MemorySearchResult]:
        """Retrieve memories ranked by keyword+tag relevance × importance."""
        query_words = set(self._tokenize(query))
        results: list[MemorySearchResult] = []

        for entry in self._entries.values():
            if memory_type and entry.memory_type != memory_type:
                continue

            # Tag match — higher priority
            if tags:
                overlap = set(tags) & set(entry.tags)
                if overlap:
                    entry.touch()
                    results.append(MemorySearchResult(entry=entry, match_type="tag", score=len(overlap) / len(tags)))
                    continue

            # Keyword match (Jaccard similarity)
            entry_words = set(self._tokenize(entry.content))
            if not query_words or not entry_words:
                continue
            jaccard = len(query_words & entry_words) / len(query_words | entry_words)
            if jaccard >= 0.15:
                entry.touch()
                results.append(MemorySearchResult(entry=entry, match_type="keyword", score=jaccard))

        results.sort(key=lambda r: r.score * r.entry.importance, reverse=True)
        return results[:top_k]

    def forget(self, key: str) -> bool:
        if key not in self._entries:
            return False
        del self._entries[key]
        self._save()
        return True

    def by_type(self, memory_type: str) -> list[MemoryEntry]:
        return [e for e in self._entries.values() if e.memory_type == memory_type]

    def stats(self) -> dict:
        by_type: dict[str, int] = {}
        for e in self._entries.values():
            by_type[e.memory_type] = by_type.get(e.memory_type, 0) + 1
        return {
            "total": len(self._entries),
            "by_type": by_type,
            "capacity": self._max,
            "path": str(self._path),
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _tokenize(self, text: str) -> list[str]:
        return [w.strip(".,;:!?\"'()[]") for w in text.lower().split() if w not in _STOP_WORDS and len(w) > 2]

    def _consolidate(self) -> None:
        """Evict lowest-scored entries when over capacity."""
        if len(self._entries) <= self._max:
            return
        scored = sorted(
            self._entries.items(),
            key=lambda kv: kv[1].importance * 0.6 + min(kv[1].access_count / 20.0, 0.4),
        )
        for key, _ in scored[: max(1, len(scored) // 10)]:
            del self._entries[key]
