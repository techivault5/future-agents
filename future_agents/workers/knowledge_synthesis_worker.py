"""Knowledge Synthesis Worker — uses Claude to synthesise KnowledgeStore entries."""

from __future__ import annotations

import logging
from typing import Any

from future_agents.core.events import Event, EventBus
from future_agents.infrastructure.knowledge_store import KnowledgeStore
from future_agents.infrastructure.metric_tracker import MetricTracker
from future_agents.models.knowledge import KnowledgeEntry
from future_agents.workers.base_worker import BaseWorker, WorkerResult

logger = logging.getLogger(__name__)

try:
    import anthropic

    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False


class KnowledgeSynthesisWorker(BaseWorker):
    """Periodically synthesises KnowledgeStore entries into higher-level insights.

    Uses claude-opus-4-7 with adaptive thinking to:
    - Cluster related entries and identify themes.
    - Surface contradictions or tensions.
    - Produce actionable recommendations.
    - Write the synthesis back as a new KnowledgeEntry in the 'synthesis' domain.
    """

    def __init__(
        self,
        knowledge_store: KnowledgeStore,
        metrics: MetricTracker,
        event_bus: EventBus,
        model: str = "claude-opus-4-7",
        min_entries: int = 5,
        interval_seconds: int = 1800,
        **kwargs: Any,
    ) -> None:
        super().__init__(interval_seconds=interval_seconds, **kwargs)
        self.knowledge_store = knowledge_store
        self.metrics = metrics
        self.event_bus = event_bus
        self.model = model
        self.min_entries = min_entries
        self._synthesised_ids: set[str] = set()

    @property
    def worker_type(self) -> str:
        return "knowledge_synthesis"

    async def run(self) -> WorkerResult:
        if not _ANTHROPIC_AVAILABLE:
            return WorkerResult(
                worker_id=self.worker_id,
                success=False,
                errors=["anthropic package not installed; run: pip install anthropic"],
            )

        all_entries = list(self.knowledge_store._entries.values())
        new_entries = [e for e in all_entries if e.id not in self._synthesised_ids]

        if len(new_entries) < self.min_entries:
            return WorkerResult(
                worker_id=self.worker_id,
                success=True,
                data={
                    "skipped": True,
                    "reason": f"Only {len(new_entries)} new entries (min {self.min_entries})",
                },
            )

        batch = new_entries[:20]
        entries_text = "\n\n".join(f"[{e.domain}] {e.title}\n{e.content}" for e in batch)
        prompt = (
            f"Below are {len(batch)} knowledge entries from an AI agent system.\n\n"
            f"{entries_text}\n\n"
            f"Please:\n"
            f"1. Identify the 3 most important themes or insights across these entries.\n"
            f"2. Note any contradictions or tensions.\n"
            f"3. Provide 2-3 concrete, actionable recommendations for the system.\n"
            f"Format your response with clear headings."
        )

        try:
            client = anthropic.Anthropic()
            response = client.messages.create(
                model=self.model,
                max_tokens=2048,
                thinking={"type": "adaptive"},
                messages=[{"role": "user", "content": prompt}],
            )
            synthesis = "\n".join(b.text for b in response.content if hasattr(b, "text"))
            total_tokens = response.usage.input_tokens + response.usage.output_tokens
        except Exception as exc:
            logger.exception("KnowledgeSynthesisWorker Claude call failed")
            return WorkerResult(
                worker_id=self.worker_id,
                success=False,
                errors=[str(exc)],
            )

        entry = KnowledgeEntry(
            title=f"Knowledge Synthesis ({len(batch)} entries)",
            domain="synthesis",
            content=synthesis,
            tags=["synthesis", "ai-generated", "insights"],
            source_agent=self.worker_id,
            confidence=0.9,
        )
        self.knowledge_store.add(entry)
        self._synthesised_ids.update(e.id for e in batch)

        await self.event_bus.emit(
            Event(
                type="worker.knowledge_synthesis.cycle_complete",
                source=self.worker_id,
                data={"entries_processed": len(batch), "total_tokens": total_tokens},
            )
        )
        self.metrics.increment("workers.knowledge_synthesis.runs")
        self.metrics.increment("workers.knowledge_synthesis.entries_processed", float(len(batch)))

        return WorkerResult(
            worker_id=self.worker_id,
            success=True,
            data={
                "entries_processed": len(batch),
                "synthesis_entry_id": entry.id,
                "total_tokens": total_tokens,
            },
        )
