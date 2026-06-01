"""ReAct pattern — Reasoning + Acting loop using Claude API."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from future_agents.patterns.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

try:
    import anthropic

    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False


@dataclass
class ReActStep:
    thought: str
    action: str | None = None
    action_input: dict[str, Any] = field(default_factory=dict)
    observation: str | None = None


@dataclass
class ReActResult:
    answer: str
    steps: list[ReActStep]
    success: bool
    total_tokens: int = 0


class ReActRunner:
    """Runs the ReAct loop: Claude reasons, calls tools, observes, repeats.

    Uses claude-opus-4-7 with adaptive thinking. Loops until Claude
    returns a plain-text answer or max_iterations is reached.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        model: str = "claude-opus-4-7",
        max_iterations: int = 10,
        system_prompt: str = "",
    ) -> None:
        if not _ANTHROPIC_AVAILABLE:
            raise ImportError("anthropic package required: pip install anthropic")
        from future_agents.patterns.tool_registry import ToolRegistry as TR

        self.tool_registry = tool_registry or TR()
        self.model = model
        self.max_iterations = max_iterations
        self.system_prompt = system_prompt or (
            "You are an intelligent agent. Think carefully before acting. "
            "Use available tools when you need information or to perform actions. "
            "When you have enough information, provide a clear final answer."
        )
        self._client = anthropic.Anthropic()

    async def run(self, query: str) -> ReActResult:
        messages: list[dict] = [{"role": "user", "content": query}]
        tools = self.tool_registry.to_claude_schemas()
        steps: list[ReActStep] = []
        total_tokens = 0

        for _ in range(self.max_iterations):
            kwargs: dict[str, Any] = {
                "model": self.model,
                "max_tokens": 4096,
                "system": self.system_prompt,
                "messages": messages,
                "thinking": {"type": "adaptive"},
            }
            if tools:
                kwargs["tools"] = tools

            response = self._client.messages.create(**kwargs)
            total_tokens += response.usage.input_tokens + response.usage.output_tokens

            tool_calls = [b for b in response.content if b.type == "tool_use"]
            text_blocks = [b for b in response.content if b.type == "text"]

            if not tool_calls:
                answer = "\n".join(b.text for b in text_blocks if hasattr(b, "text"))
                return ReActResult(
                    answer=answer, steps=steps, success=True, total_tokens=total_tokens
                )

            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for tool_call in tool_calls:
                thought = "\n".join(b.text for b in text_blocks if hasattr(b, "text"))
                step = ReActStep(
                    thought=thought,
                    action=tool_call.name,
                    action_input=tool_call.input,
                )
                tool = self.tool_registry.get(tool_call.name)
                if tool is None:
                    observation = f"Error: tool '{tool_call.name}' not found"
                else:
                    try:
                        result = await tool.call(**tool_call.input)
                        observation = json.dumps(result) if not isinstance(result, str) else result
                    except Exception as exc:
                        observation = f"Error: {exc}"
                step.observation = observation
                steps.append(step)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_call.id,
                        "content": observation,
                    }
                )

            messages.append({"role": "user", "content": tool_results})

        return ReActResult(
            answer="Max iterations reached without a final answer.",
            steps=steps,
            success=False,
            total_tokens=total_tokens,
        )
