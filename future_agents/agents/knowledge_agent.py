"""Knowledge Agent — manages organizational knowledge and learning."""

from __future__ import annotations

from typing import Any

from future_agents.core.base_agent import BaseAgent, TaskContext, TaskResult
from future_agents.infrastructure.knowledge_store import KnowledgeStore
from future_agents.models.feedback import ExecutionOutcome
from future_agents.models.knowledge import KnowledgeEntry


class KnowledgeAgent(BaseAgent):
    """Manages organizational knowledge capture, retrieval, and maintenance.

    Handles:
    - Adding and updating knowledge entries
    - Searching and retrieving knowledge
    - Identifying stale or low-quality entries
    - Cross-referencing knowledge across domains
    """

    def __init__(self, knowledge_store: KnowledgeStore | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.store = knowledge_store or KnowledgeStore()

    @property
    def agent_type(self) -> str:
        return "knowledge"

    @property
    def capabilities(self) -> list[str]:
        return [
            "knowledge.add",
            "knowledge.search",
            "knowledge.update",
            "knowledge.audit",
        ]

    async def _execute(self, context: TaskContext) -> TaskResult:
        handlers = {
            "knowledge.add": self._add_knowledge,
            "knowledge.search": self._search_knowledge,
            "knowledge.update": self._update_knowledge,
            "knowledge.audit": self._audit_knowledge,
        }
        handler = handlers.get(context.intent)
        if not handler:
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.FAILURE,
                errors=[f"Unknown intent: {context.intent}"],
            )
        return await handler(context, context.parameters)

    async def _add_knowledge(self, context: TaskContext, params: dict) -> TaskResult:
        entry = KnowledgeEntry(
            title=params["title"],
            domain=params.get("domain", "general"),
            content=params["content"],
            tags=params.get("tags", []),
            source_agent=params.get("source_agent", self.agent_id),
            confidence=params.get("confidence", 1.0),
        )
        self.store.add(entry)

        await self.emit(
            "knowledge.added",
            {"entry_id": entry.id, "title": entry.title, "domain": entry.domain},
        )

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={"entry_id": entry.id, "entry": entry.model_dump(mode="json")},
        )

    async def _search_knowledge(self, context: TaskContext, params: dict) -> TaskResult:
        results = self.store.search(
            query=params.get("query", ""),
            domain=params.get("domain"),
            tags=params.get("tags"),
            min_confidence=params.get("min_confidence", 0.0),
        )

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={
                "results": [r.model_dump(mode="json") for r in results],
                "count": len(results),
            },
        )

    async def _update_knowledge(self, context: TaskContext, params: dict) -> TaskResult:
        entry_id = params.get("entry_id", "")
        new_content = params.get("content", "")
        reason = params.get("reason", "manual update")

        success = await self.store.update(entry_id, new_content, self.agent_id, reason)
        if not success:
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.FAILURE,
                errors=[f"Knowledge entry not found: {entry_id}"],
            )

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={"entry_id": entry_id, "updated": True},
        )

    async def _audit_knowledge(self, context: TaskContext, params: dict) -> TaskResult:
        stale = self.store.stale_entries(min_usefulness=params.get("min_usefulness", 0.3))
        stats = self.store.stats()

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={
                "stats": stats,
                "stale_entries": [{"id": e.id, "title": e.title, "usefulness": e.usefulness_score} for e in stale],
            },
            suggestions=[f"Review stale entry: {e.title}" for e in stale[:5]],
        )

    async def assess_self(self) -> dict[str, Any]:
        stats = self.store.stats()
        return {
            "store_size": stats["total_entries"],
            "domains": stats["domains"],
            "avg_confidence": stats["avg_confidence"],
            "avg_usefulness": stats["avg_usefulness"],
            "stale_count": stats["stale_count"],
        }
