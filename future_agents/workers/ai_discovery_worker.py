"""AI Discovery Worker — uses Claude to discover new patterns and capabilities."""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Any

from future_agents.core.events import Event, EventBus
from future_agents.infrastructure.knowledge_store import KnowledgeStore
from future_agents.infrastructure.metric_tracker import MetricTracker
from future_agents.models.knowledge import KnowledgeEntry
from future_agents.patterns.library import PatternLibrary
from future_agents.workers.base_worker import BaseWorker, WorkerResult

logger = logging.getLogger(__name__)

try:
    import anthropic

    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False


class AIDiscoveryWorker(BaseWorker):
    """Uses Claude to analyse the codebase and discover new agentic patterns.

    Each cycle:
    1. Scans agent source files via AST to extract class structure.
    2. Queries Claude (ReAct-style with adaptive thinking) for pattern recommendations.
    3. Stores discoveries as KnowledgeEntries in the 'ai_discovery' domain.
    4. Checks PatternLibrary for gaps and suggests new patterns to implement.
    """

    def __init__(
        self,
        knowledge_store: KnowledgeStore,
        metrics: MetricTracker,
        event_bus: EventBus,
        source_root: Path,
        pattern_library: PatternLibrary | None = None,
        model: str = "claude-opus-4-7",
        interval_seconds: int = 3600,
        **kwargs: Any,
    ) -> None:
        super().__init__(interval_seconds=interval_seconds, **kwargs)
        self.knowledge_store = knowledge_store
        self.metrics = metrics
        self.event_bus = event_bus
        self.source_root = source_root
        self.pattern_library = pattern_library or PatternLibrary()
        self.model = model
        self._cycle_count = 0

    @property
    def worker_type(self) -> str:
        return "ai_discovery"

    async def run(self) -> WorkerResult:
        if not _ANTHROPIC_AVAILABLE:
            return WorkerResult(
                worker_id=self.worker_id,
                success=False,
                errors=["anthropic package not installed; run: pip install anthropic"],
            )

        self._cycle_count += 1
        agent_summary = self._scan_agents()
        pattern_summary = self._pattern_summary()

        prompt = (
            f"You are analysing a Python multi-agent system. Here is what exists:\n\n"
            f"## Agent Implementations\n{agent_summary}\n\n"
            f"## Known Agentic Patterns\n{pattern_summary}\n\n"
            f"Please:\n"
            f"1. Identify 2-3 new agentic patterns or capabilities that would improve this system.\n"
            f"2. For each suggestion, explain what it does and why it would help.\n"
            f"3. Identify any underutilised patterns already in the library.\n"
            f"4. Suggest concrete implementation steps for the highest-priority suggestion.\n"
            f"Be specific and actionable."
        )

        try:
            client = anthropic.Anthropic()
            response = client.messages.create(
                model=self.model,
                max_tokens=3000,
                thinking={"type": "adaptive"},
                messages=[{"role": "user", "content": prompt}],
            )
            discoveries = "\n".join(b.text for b in response.content if hasattr(b, "text"))
            total_tokens = response.usage.input_tokens + response.usage.output_tokens
        except Exception as exc:
            logger.exception("AIDiscoveryWorker Claude call failed")
            return WorkerResult(
                worker_id=self.worker_id,
                success=False,
                errors=[str(exc)],
            )

        entry = KnowledgeEntry(
            title=f"AI Discovery — Cycle {self._cycle_count}",
            domain="ai_discovery",
            content=discoveries,
            tags=["ai-discovery", "patterns", "recommendations", "ai-generated"],
            source_agent=self.worker_id,
            confidence=0.85,
        )
        self.knowledge_store.add(entry)

        await self.event_bus.emit(
            Event(
                type="worker.ai_discovery.cycle_complete",
                source=self.worker_id,
                data={"cycle": self._cycle_count, "total_tokens": total_tokens},
            )
        )
        self.metrics.increment("workers.ai_discovery.runs")
        self.metrics.increment("workers.ai_discovery.tokens_used", float(total_tokens))

        return WorkerResult(
            worker_id=self.worker_id,
            success=True,
            data={
                "cycle": self._cycle_count,
                "entry_id": entry.id,
                "total_tokens": total_tokens,
            },
        )

    def _scan_agents(self) -> str:
        agents_dir = self.source_root / "future_agents" / "agents"
        if not agents_dir.exists():
            return "No agents directory found."
        lines = []
        for py_file in sorted(agents_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                tree = ast.parse(py_file.read_text())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                base_names = [
                    b.id if isinstance(b, ast.Name) else (b.attr if isinstance(b, ast.Attribute) else "")
                    for b in node.bases
                ]
                if "BaseAgent" in base_names:
                    lines.append(f"- {node.name} ({py_file.name})")
        return "\n".join(lines) if lines else "No BaseAgent subclasses found."

    def _pattern_summary(self) -> str:
        summary = self.pattern_library.summary()
        lines = []
        for category, names in summary.items():
            lines.append(f"- {category}: {', '.join(names)}")
        return "\n".join(lines) if lines else "No patterns registered."
