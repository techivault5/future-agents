"""Digital Worker Agent — Claude-powered agent using agentic patterns."""

from __future__ import annotations

import logging
from typing import Any

from future_agents.core.base_agent import BaseAgent, TaskContext, TaskResult
from future_agents.core.events import EventBus
from future_agents.models.feedback import ExecutionOutcome
from future_agents.patterns.library import PatternLibrary
from future_agents.patterns.tool_registry import Tool, ToolParameter, ToolRegistry

logger = logging.getLogger(__name__)

try:
    from future_agents.patterns.react import ReActRunner
    from future_agents.patterns.reflection import ReflectionRunner

    _PATTERNS_AVAILABLE = True
except ImportError:
    _PATTERNS_AVAILABLE = False


class DigitalWorkerAgent(BaseAgent):
    """AI-powered agent that executes tasks using ReAct or Reflection patterns.

    Uses ReAct (tool-enabled reasoning loop) for queries that benefit from
    tool use, and Reflection (generate→critique→refine) for open-ended tasks.
    Falls back gracefully when the anthropic package is not installed.
    """

    def __init__(
        self,
        agent_id: str | None = None,
        event_bus: EventBus | None = None,
        tool_registry: ToolRegistry | None = None,
        use_reflection: bool = False,
        model: str = "claude-opus-4-7",
    ) -> None:
        super().__init__(agent_id=agent_id, event_bus=event_bus)
        self.tool_registry = tool_registry or ToolRegistry()
        self.use_reflection = use_reflection
        self.model = model
        self.pattern_library = PatternLibrary()
        self._register_builtin_tools()

    @property
    def agent_type(self) -> str:
        return "digital_worker"

    @property
    def capabilities(self) -> list[str]:
        return [
            "digital_worker.react",
            "digital_worker.reflection",
            "digital_worker.pattern_discovery",
            "digital_worker.tool_use",
        ]

    def _register_builtin_tools(self) -> None:
        self.tool_registry.register(
            Tool(
                name="list_patterns",
                description="List all known agentic design patterns in the library.",
                fn=self._list_patterns,
                parameters=[],
            )
        )
        self.tool_registry.register(
            Tool(
                name="get_pattern",
                description="Get details about a specific agentic design pattern by name.",
                fn=self._get_pattern,
                parameters=[
                    ToolParameter(
                        name="name",
                        type="string",
                        description="Pattern name (e.g. 'ReAct', 'Reflection')",
                    )
                ],
            )
        )
        self.tool_registry.register(
            Tool(
                name="search_patterns",
                description="Search the pattern library by keyword.",
                fn=self._search_patterns,
                parameters=[
                    ToolParameter(
                        name="keyword",
                        type="string",
                        description="Search keyword",
                    )
                ],
            )
        )

    def _list_patterns(self) -> list[dict]:
        return [
            {"name": p.name, "category": p.category.value, "description": p.description[:100]}
            for p in self.pattern_library.all()
        ]

    def _get_pattern(self, name: str) -> dict | str:
        p = self.pattern_library.get(name)
        if p is None:
            return f"Pattern '{name}' not found"
        return {
            "name": p.name,
            "category": p.category.value,
            "description": p.description,
            "use_cases": p.use_cases,
            "benefits": p.benefits,
            "tradeoffs": p.tradeoffs,
        }

    def _search_patterns(self, keyword: str) -> list[dict]:
        return [{"name": p.name, "category": p.category.value} for p in self.pattern_library.search(keyword)]

    async def _execute(self, context: TaskContext) -> TaskResult:
        if not _PATTERNS_AVAILABLE:
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.FAILURE,
                errors=["anthropic package not installed; run: pip install anthropic"],
            )

        query = context.parameters.get("query", context.intent)
        if not query:
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.FAILURE,
                errors=["No query in context.parameters['query'] or context.intent"],
            )

        try:
            if self.use_reflection or context.parameters.get("use_reflection"):
                runner = ReflectionRunner(model=self.model)
                result = await runner.run(query)
                return TaskResult(
                    task_id=context.task_id,
                    agent_id=self.agent_id,
                    outcome=ExecutionOutcome.SUCCESS,
                    data={
                        "answer": result.refined,
                        "pattern": "Reflection",
                        "initial": result.initial,
                        "critique": result.critique,
                        "total_tokens": result.total_tokens,
                    },
                )
            else:
                runner = ReActRunner(tool_registry=self.tool_registry, model=self.model)
                result = await runner.run(query)
                return TaskResult(
                    task_id=context.task_id,
                    agent_id=self.agent_id,
                    outcome=(ExecutionOutcome.SUCCESS if result.success else ExecutionOutcome.PARTIAL),
                    data={
                        "answer": result.answer,
                        "pattern": "ReAct",
                        "steps": len(result.steps),
                        "total_tokens": result.total_tokens,
                    },
                    errors=[] if result.success else ["Max iterations reached"],
                )
        except Exception as exc:
            logger.exception("DigitalWorkerAgent task %s failed", context.task_id)
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.FAILURE,
                errors=[str(exc)],
            )

    async def assess_self(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "execution_count": self._execution_count,
            "success_rate": self.success_rate,
            "patterns_available": _PATTERNS_AVAILABLE,
            "tools_registered": len(self.tool_registry.all()),
            "patterns_in_library": len(self.pattern_library.all()),
        }
