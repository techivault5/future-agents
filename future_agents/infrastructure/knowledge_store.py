"""Knowledge Store — versioned, searchable knowledge base."""

from __future__ import annotations

import logging
from collections import defaultdict

from future_agents.core.events import Event, EventBus
from future_agents.models.knowledge import KnowledgeEntry

logger = logging.getLogger(__name__)


class KnowledgeStore:
    """Central knowledge store with versioning, tagging, and search.

    All organizational knowledge flows through here — processes, policies,
    capability definitions, skill maps, and learned insights.
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.event_bus = event_bus or EventBus()
        self._entries: dict[str, KnowledgeEntry] = {}
        self._domain_index: dict[str, list[str]] = defaultdict(list)
        self._tag_index: dict[str, list[str]] = defaultdict(list)

    @property
    def size(self) -> int:
        return len(self._entries)

    def add(self, entry: KnowledgeEntry) -> None:
        """Add a knowledge entry to the store."""
        self._entries[entry.id] = entry
        self._domain_index[entry.domain].append(entry.id)
        for tag in entry.tags:
            self._tag_index[tag].append(entry.id)
        logger.info("Knowledge added: %s (domain=%s)", entry.title, entry.domain)

    def get(self, entry_id: str) -> KnowledgeEntry | None:
        """Retrieve a knowledge entry by ID."""
        entry = self._entries.get(entry_id)
        if entry:
            entry.record_access(was_useful=True)
        return entry

    def search(
        self,
        query: str,
        domain: str | None = None,
        tags: list[str] | None = None,
        min_confidence: float = 0.0,
    ) -> list[KnowledgeEntry]:
        """Search knowledge entries by text, domain, and tags.

        Simple substring search — in production you'd swap this for
        vector similarity or full-text search.
        """
        results: list[KnowledgeEntry] = []
        query_lower = query.lower()

        candidates = self._entries.values()
        if domain:
            candidate_ids = set(self._domain_index.get(domain, []))
            candidates = [e for e in candidates if e.id in candidate_ids]

        for entry in candidates:
            if entry.confidence < min_confidence:
                continue
            if tags and not any(t in entry.tags for t in tags):
                continue
            if query_lower in entry.title.lower() or query_lower in entry.content.lower():
                results.append(entry)

        # Sort by usefulness and confidence
        results.sort(key=lambda e: (e.usefulness_score, e.confidence), reverse=True)
        return results

    def by_domain(self, domain: str) -> list[KnowledgeEntry]:
        """Get all entries for a domain."""
        ids = self._domain_index.get(domain, [])
        return [self._entries[eid] for eid in ids if eid in self._entries]

    def by_tag(self, tag: str) -> list[KnowledgeEntry]:
        """Get all entries with a specific tag."""
        ids = self._tag_index.get(tag, [])
        return [self._entries[eid] for eid in ids if eid in self._entries]

    async def update(
        self, entry_id: str, new_content: str, changed_by: str, reason: str
    ) -> bool:
        """Update a knowledge entry with versioning."""
        entry = self._entries.get(entry_id)
        if not entry:
            return False
        entry.update_content(new_content, changed_by, reason)
        if self.event_bus:
            await self.event_bus.emit(
                Event(
                    type="knowledge.updated",
                    source=changed_by,
                    data={
                        "entry_id": entry_id,
                        "version": entry.version,
                        "reason": reason,
                    },
                )
            )
        return True

    def stale_entries(self, min_usefulness: float = 0.3) -> list[KnowledgeEntry]:
        """Find entries that may need updating (low usefulness or access)."""
        return [
            e
            for e in self._entries.values()
            if e.usefulness_score < min_usefulness
        ]

    def stats(self) -> dict:
        """Return store statistics."""
        entries = list(self._entries.values())
        return {
            "total_entries": len(entries),
            "domains": list(self._domain_index.keys()),
            "avg_confidence": (
                sum(e.confidence for e in entries) / len(entries) if entries else 0
            ),
            "avg_usefulness": (
                sum(e.usefulness_score for e in entries) / len(entries) if entries else 0
            ),
            "stale_count": len(self.stale_entries()),
        }
