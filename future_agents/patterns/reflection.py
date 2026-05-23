"""Reflection pattern — generate, critique, refine using Claude API."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

try:
    import anthropic

    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False


@dataclass
class ReflectionResult:
    initial: str
    critique: str
    refined: str
    success: bool
    total_tokens: int = 0


class ReflectionRunner:
    """Implements the Reflection pattern via three Claude calls.

    1. Generate — produce an initial response.
    2. Critique — identify weaknesses, errors, and gaps.
    3. Refine   — produce an improved response addressing the critique.

    Uses claude-opus-4-7 with adaptive thinking.
    """

    def __init__(
        self,
        model: str = "claude-opus-4-7",
        system_prompt: str = "",
    ) -> None:
        if not _ANTHROPIC_AVAILABLE:
            raise ImportError("anthropic package required: pip install anthropic")
        self.model = model
        self.system_prompt = system_prompt or "You are a highly capable AI assistant."
        self._client = anthropic.Anthropic()

    def _call(self, messages: list[dict], system: str | None = None) -> tuple[str, int]:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system or self.system_prompt,
            messages=messages,
            thinking={"type": "adaptive"},
        )
        tokens = response.usage.input_tokens + response.usage.output_tokens
        text = "\n".join(b.text for b in response.content if hasattr(b, "text"))
        return text, tokens

    async def run(self, task: str) -> ReflectionResult:
        total_tokens = 0

        initial, t = self._call([{"role": "user", "content": task}])
        total_tokens += t

        critique_prompt = (
            f"Review the following response to this task:\n\n"
            f"**Task:** {task}\n\n"
            f"**Response:**\n{initial}\n\n"
            f"Identify specific weaknesses, inaccuracies, gaps in reasoning, "
            f"or missing considerations. Be specific and constructive."
        )
        critique, t = self._call(
            [{"role": "user", "content": critique_prompt}],
            system="You are a rigorous critic. Find flaws and suggest concrete improvements.",
        )
        total_tokens += t

        refine_prompt = (
            f"Improve your response to this task based on the critique below.\n\n"
            f"**Task:** {task}\n\n"
            f"**Original response:**\n{initial}\n\n"
            f"**Critique:**\n{critique}\n\n"
            f"Produce a significantly improved response that addresses all issues raised."
        )
        refined, t = self._call([{"role": "user", "content": refine_prompt}])
        total_tokens += t

        return ReflectionResult(
            initial=initial,
            critique=critique,
            refined=refined,
            success=True,
            total_tokens=total_tokens,
        )
