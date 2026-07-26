"""Tool registry for agentic tool-use patterns."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolParameter:
    """Schema for a single tool parameter."""

    name: str
    type: str
    description: str
    required: bool = True


@dataclass
class Tool:
    """A callable tool with a Claude API-compatible JSON schema."""

    name: str
    description: str
    fn: Callable[..., Any]
    parameters: list[ToolParameter] = field(default_factory=list)

    def to_claude_schema(self) -> dict:
        properties: dict[str, dict] = {}
        required: list[str] = []
        for param in self.parameters:
            properties[param.name] = {"type": param.type, "description": param.description}
            if param.required:
                required.append(param.name)
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }

    async def call(self, **kwargs: Any) -> Any:
        result = self.fn(**kwargs)
        if inspect.isawaitable(result):
            return await result
        return result


class ToolRegistry:
    """Registry of named tools available to agentic patterns."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def to_claude_schemas(self) -> list[dict]:
        return [t.to_claude_schema() for t in self._tools.values()]
