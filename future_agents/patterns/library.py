"""Pattern library cataloging known agentic design patterns."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PatternCategory(str, Enum):
    REASONING = "reasoning"
    ACTING = "acting"
    LEARNING = "learning"
    ORCHESTRATION = "orchestration"
    RELIABILITY = "reliability"


@dataclass
class AgentPattern:
    name: str
    category: PatternCategory
    description: str
    use_cases: list[str] = field(default_factory=list)
    benefits: list[str] = field(default_factory=list)
    tradeoffs: list[str] = field(default_factory=list)
    implementation_class: str | None = None


_BUILTIN_PATTERNS: list[AgentPattern] = [
    AgentPattern(
        name="ReAct",
        category=PatternCategory.REASONING,
        description=(
            "Interleaves Reasoning and Acting: the model thinks step-by-step, "
            "calls tools, observes results, and iterates to a final answer."
        ),
        use_cases=["web search + synthesis", "multi-step computation", "database queries"],
        benefits=["transparent reasoning", "accurate tool use", "self-correcting"],
        tradeoffs=["higher latency", "more tokens"],
        implementation_class="future_agents.patterns.react.ReActRunner",
    ),
    AgentPattern(
        name="Reflection",
        category=PatternCategory.RELIABILITY,
        description=(
            "Generates an initial response, critiques it for accuracy and completeness, "
            "then produces a refined response based on the critique."
        ),
        use_cases=["code generation", "report writing", "complex analysis"],
        benefits=["higher quality output", "catches own errors"],
        tradeoffs=["2-3x more tokens", "higher cost"],
        implementation_class="future_agents.patterns.reflection.ReflectionRunner",
    ),
    AgentPattern(
        name="Plan-and-Execute",
        category=PatternCategory.ORCHESTRATION,
        description=(
            "Creates a structured plan (sequence of steps) before executing any step, "
            "allowing upfront validation and parallel execution."
        ),
        use_cases=["multi-stage workflows", "research pipelines", "long-horizon tasks"],
        benefits=["predictable", "parallelisable", "auditable"],
        tradeoffs=["rigid — hard to adapt mid-run if plan is wrong"],
    ),
    AgentPattern(
        name="Tool-Use",
        category=PatternCategory.ACTING,
        description=(
            "Equips the model with a typed tool registry; the model selects and invokes "
            "tools by name, receiving structured results."
        ),
        use_cases=["API integration", "database access", "file operations"],
        benefits=["extends model capabilities", "structured I/O", "auditable calls"],
        tradeoffs=["requires well-described tools", "hallucination risk on tool names"],
        implementation_class="future_agents.patterns.tool_registry.ToolRegistry",
    ),
    AgentPattern(
        name="Chain-of-Thought",
        category=PatternCategory.REASONING,
        description=(
            "Prompts the model to reason step-by-step before producing a final answer, "
            "improving accuracy on complex problems."
        ),
        use_cases=["math", "logic puzzles", "multi-step reasoning"],
        benefits=["improved accuracy", "transparent reasoning"],
        tradeoffs=["more output tokens"],
    ),
    AgentPattern(
        name="Self-Consistency",
        category=PatternCategory.RELIABILITY,
        description=(
            "Generates multiple independent responses and aggregates them (majority vote "
            "or best-of-N) for improved reliability."
        ),
        use_cases=["high-stakes decisions", "factual queries"],
        benefits=["reduced variance", "more reliable answers"],
        tradeoffs=["N× cost and latency"],
    ),
    AgentPattern(
        name="Subagent-Delegation",
        category=PatternCategory.ORCHESTRATION,
        description=(
            "Orchestrator decomposes a task, delegates subtasks to specialised subagents, "
            "then synthesises results into a final output."
        ),
        use_cases=["research + writing", "code review + fix", "data + analysis"],
        benefits=["specialisation", "parallelism", "separation of concerns"],
        tradeoffs=["coordination overhead", "complex failure handling"],
    ),
    AgentPattern(
        name="Memory-Augmented",
        category=PatternCategory.LEARNING,
        description=(
            "Stores episodic and semantic memories in an external store (vector DB, "
            "knowledge graph) and retrieves relevant context before each response."
        ),
        use_cases=["long-running assistants", "knowledge-intensive tasks"],
        benefits=["persistent context", "personalised responses"],
        tradeoffs=["retrieval latency", "memory staleness"],
    ),
]


class PatternLibrary:
    """Catalog of known agentic patterns with lookup and discovery."""

    def __init__(self) -> None:
        self._patterns: dict[str, AgentPattern] = {p.name: p for p in _BUILTIN_PATTERNS}

    def register(self, pattern: AgentPattern) -> None:
        self._patterns[pattern.name] = pattern

    def get(self, name: str) -> AgentPattern | None:
        return self._patterns.get(name)

    def by_category(self, category: PatternCategory) -> list[AgentPattern]:
        return [p for p in self._patterns.values() if p.category == category]

    def search(self, keyword: str) -> list[AgentPattern]:
        kw = keyword.lower()
        return [
            p
            for p in self._patterns.values()
            if kw in p.name.lower() or kw in p.description.lower() or any(kw in uc.lower() for uc in p.use_cases)
        ]

    def all(self) -> list[AgentPattern]:
        return list(self._patterns.values())

    def summary(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for p in self._patterns.values():
            result.setdefault(p.category.value, []).append(p.name)
        return result
