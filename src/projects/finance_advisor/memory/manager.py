"""MemoryManager — one write path, one recall path, across all five types.

Recall is hybrid by default: embedding similarity + keyword overlap + recency
decay + importance, blended with tunable weights. That combination is what the
current crop of memory frameworks (Mem0, Zep, Hindsight) settled on, and it
degrades gracefully — with the hashing embedder you still get lexical recall,
with a local transformer you additionally get semantic recall.

Consolidation promotes repeated episodic observations into durable semantic
facts, and `forget()` applies TTL plus low-value pruning so the store does not
grow without bound.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone

from projects.finance_advisor.memory.aliases import expand
from projects.finance_advisor.memory.backends import InMemoryBackend, MemoryBackend
from projects.finance_advisor.memory.embeddings import Embedder, HashingEmbedder, cosine, tokenize
from projects.finance_advisor.memory.types import (
    MemoryRecord,
    MemoryRelation,
    MemoryType,
    RecallHit,
)

logger = logging.getLogger(__name__)

# Recall blend weights; sum need not be 1.0, scores are comparable within a query.
W_SIMILARITY = 0.55
W_KEYWORD = 0.20
W_RECENCY = 0.15
W_IMPORTANCE = 0.10

WORKING_TTL_SECONDS = 3600  # working memory defaults to one hour


class MemoryManager:
    """Unified read/write/maintain API over a backend and an embedder."""

    def __init__(
        self,
        backend: MemoryBackend | None = None,
        embedder: Embedder | None = None,
        subject: str = "user",
    ) -> None:
        self.backend = backend or InMemoryBackend()
        self.embedder = embedder or HashingEmbedder()
        self.subject = subject

    # ── write ────────────────────────────────────────────────────────────

    def remember(
        self,
        content: str,
        type: MemoryType = MemoryType.SEMANTIC,
        tags: list[str] | None = None,
        importance: float = 0.5,
        sensitive: bool = False,
        source: str = "user",
        ttl_seconds: int | None = None,
        relations: list[MemoryRelation] | None = None,
    ) -> MemoryRecord:
        """Write one memory, embedding it for later semantic recall."""
        if type is MemoryType.WORKING and ttl_seconds is None:
            ttl_seconds = WORKING_TTL_SECONDS
        record = MemoryRecord(
            type=type,
            content=content,
            subject=self.subject,
            tags=tags or [],
            importance=importance,
            sensitive=sensitive,
            source=source,
            ttl_seconds=ttl_seconds,
            relations=relations or [],
            embedding=self.embedder.embed(content),
        )
        self.backend.put(record)
        logger.debug("remembered %s (%s)", record.id, record.type.value)
        return record

    def link(self, record_id: str, predicate: str, target: str, weight: float = 1.0) -> bool:
        """Add a typed relation to an existing record. False if it is missing."""
        record = self.backend.get(record_id)
        if record is None:
            return False
        record.relations.append(MemoryRelation(predicate=predicate, target=target, weight=weight))
        self.backend.put(record)
        return True

    # ── read ─────────────────────────────────────────────────────────────

    def recall(
        self,
        query: str,
        types: list[MemoryType] | None = None,
        tags: list[str] | None = None,
        limit: int = 5,
        min_score: float = 0.0,
        include_expired: bool = False,
    ) -> list[RecallHit]:
        """Rank memories against `query` and return the best `limit` hits."""
        candidates = self.backend.scan(subject=self.subject, types=types, tags=tags)
        now = datetime.now(timezone.utc)
        # Alias expansion bridges finance synonyms the lexical embedder misses
        # ("income" -> "take_home"); a transformer embedder needs it far less.
        expanded = expand(tokenize(query))
        query_vec = self.embedder.embed(" ".join(expanded))
        query_tokens = set(expanded)

        hits: list[RecallHit] = []
        for record in candidates:
            if not include_expired and record.is_expired(now):
                continue
            similarity = cosine(query_vec, record.embedding) if record.embedding else 0.0
            record_tokens = set(tokenize(record.content))
            keyword = len(query_tokens & record_tokens) / len(query_tokens) if query_tokens else 0.0
            recency = record.recency_score()
            score = (
                W_SIMILARITY * similarity
                + W_KEYWORD * keyword
                + W_RECENCY * recency
                + W_IMPORTANCE * record.importance
            )
            if score >= min_score:
                hits.append(
                    RecallHit(
                        record=record,
                        score=round(score, 4),
                        similarity=round(similarity, 4),
                        keyword=round(keyword, 4),
                        recency=round(recency, 4),
                    )
                )

        hits.sort(key=lambda h: h.score, reverse=True)
        top = hits[:limit]
        for hit in top:
            hit.record.touch()
            self.backend.put(hit.record)
        return top

    def context_block(self, query: str, limit: int = 5, redact: bool = True) -> str:
        """Render recalled memories as a prompt-ready block, redacted by default."""
        lines = []
        for hit in self.recall(query, limit=limit):
            record = hit.record.redacted() if redact else hit.record
            lines.append(f"- [{record.type.value}] {record.content}")
        return "\n".join(lines) if lines else "- (no prior memories)"

    def profile(self) -> dict[str, str]:
        """Durable semantic facts tagged `profile`, as a flat dict for skills."""
        out: dict[str, str] = {}
        for record in self.backend.scan(subject=self.subject, types=[MemoryType.SEMANTIC]):
            if "profile" not in record.tags:
                continue
            key, _, value = record.content.partition("=")
            if value:
                out[key.strip()] = value.strip()
        return out

    # ── maintain ─────────────────────────────────────────────────────────

    def consolidate(self, min_occurrences: int = 3) -> list[MemoryRecord]:
        """Promote repeated episodic themes into semantic facts.

        A theme is a content token seen in at least `min_occurrences` episodes;
        the resulting semantic record is tagged `consolidated` and linked back
        to the episodes it came from.
        """
        episodes = self.backend.scan(subject=self.subject, types=[MemoryType.EPISODIC])
        if len(episodes) < min_occurrences:
            return []
        counts: Counter[str] = Counter()
        for record in episodes:
            counts.update(set(t for t in tokenize(record.content) if len(t) > 3))

        existing = {
            r.content for r in self.backend.scan(subject=self.subject, types=[MemoryType.SEMANTIC])
        }
        created: list[MemoryRecord] = []
        for token, count in counts.items():
            if count < min_occurrences:
                continue
            content = f"recurring_interest={token} (seen in {count} interactions)"
            if content in existing:
                continue
            sources = [r for r in episodes if token in tokenize(r.content)][:5]
            record = self.remember(
                content,
                type=MemoryType.SEMANTIC,
                tags=["consolidated", "profile"],
                importance=min(0.4 + 0.1 * count, 0.9),
                source="agent",
                relations=[MemoryRelation(predicate="derived_from", target=s.id) for s in sources],
            )
            created.append(record)
        return created

    def forget(self, min_importance: float = 0.15, keep_working: bool = False) -> int:
        """Drop expired records and low-value noise. Returns the count removed."""
        now = datetime.now(timezone.utc)
        removed = 0
        for record in self.backend.scan(subject=self.subject):
            expired = record.is_expired(now)
            if keep_working and record.type is MemoryType.WORKING:
                expired = False
            worthless = record.importance < min_importance and record.access_count == 0
            if expired or worthless:
                if self.backend.delete(record.id):
                    removed += 1
        return removed

    def stats(self) -> dict[str, object]:
        """Counts by type plus store totals, for dashboards and tests."""
        records = self.backend.scan(subject=self.subject)
        by_type = Counter(r.type.value for r in records)
        return {
            "total": len(records),
            "by_type": dict(by_type),
            "sensitive": sum(1 for r in records if r.sensitive),
            "embedder": type(self.embedder).__name__,
            "embedding_dim": getattr(self.embedder, "dim", 0),
            "backend": type(self.backend).__name__,
        }

    def export(self, redact: bool = True) -> list[dict]:
        """Portable JSON dump (embeddings dropped) for backup or transfer."""
        out = []
        for record in self.backend.scan(subject=self.subject):
            item = (record.redacted() if redact else record).model_dump(mode="json")
            item.pop("embedding", None)
            out.append(item)
        return out

    def import_records(self, items: list[dict]) -> int:
        """Load records produced by `export`, re-embedding their content."""
        loaded = 0
        for item in items:
            item.pop("embedding", None)
            record = MemoryRecord.model_validate(item)
            record.embedding = self.embedder.embed(record.content)
            self.backend.put(record)
            loaded += 1
        return loaded
