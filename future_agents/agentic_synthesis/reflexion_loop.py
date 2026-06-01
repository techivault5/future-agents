"""Reflexion Loop — verbal reinforcement learning: act → evaluate → reflect → improve.

Synthesises:
  Reflexion (Shinn et al. 2023) → verbal RL with self-critique traces
  Our ReflectionRunner          → generate → critique → refine pattern
  SyncEngine feedback           → structured outcome scoring
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ReflexionTrace:
    """One act-evaluate-reflect cycle."""
    attempt: int
    action: str
    observation: str        # environment / evaluator response
    evaluation: str         # human-readable quality assessment
    reflection: str         # verbal self-critique to guide next attempt
    score: float            # 0.0-1.0
    tokens_used: int = 0


@dataclass
class ReflexionResult:
    task: str
    final_answer: str
    traces: list[ReflexionTrace]
    success: bool
    total_tokens: int
    best_score: float

    @property
    def attempts(self) -> int:
        return len(self.traces)

    def summary(self) -> str:
        lines = [
            f"Task     : {self.task[:80]}",
            f"Attempts : {self.attempts}  Best score: {self.best_score:.2f}  Success: {self.success}",
        ]
        for t in self.traces:
            lines.append(f"  [{t.attempt}] score={t.score:.2f} — {t.reflection[:100]}")
        return "\n".join(lines)


class ReflexionLoop:
    """Verbal RL loop that iteratively improves answers via self-critique.

    Each attempt:
      1. Act    — generate answer incorporating prior reflections
      2. Evaluate — score the answer
      3. Reflect  — produce verbal critique for the next attempt

    Stops when score >= success_threshold or max_attempts reached.
    """

    def __init__(
        self,
        client=None,
        model: str = "claude-opus-4-7",
        max_attempts: int = 3,
        success_threshold: float = 0.85,
    ) -> None:
        self._client = client
        self._model = model
        self._max_attempts = max_attempts
        self._threshold = success_threshold

    async def run(
        self,
        task: str,
        evaluation_criteria: str = "",
        context: dict[str, Any] | None = None,
    ) -> ReflexionResult:
        traces: list[ReflexionTrace] = []
        total_tokens = 0
        prior_reflections: list[str] = []
        best_answer = ""
        best_score = 0.0
        context = context or {}

        for attempt in range(1, self._max_attempts + 1):
            action, act_tokens = await self._act(task, prior_reflections, context)
            total_tokens += act_tokens

            evaluation, score, eval_tokens = await self._evaluate(task, action, evaluation_criteria)
            total_tokens += eval_tokens

            reflection, ref_tokens = await self._reflect(task, action, evaluation, score)
            total_tokens += ref_tokens

            traces.append(ReflexionTrace(
                attempt=attempt,
                action=action,
                observation=evaluation,
                evaluation=evaluation,
                reflection=reflection,
                score=score,
                tokens_used=act_tokens + eval_tokens + ref_tokens,
            ))
            prior_reflections.append(reflection)

            if score > best_score:
                best_score = score
                best_answer = action

            if score >= self._threshold:
                break

        return ReflexionResult(
            task=task,
            final_answer=best_answer,
            traces=traces,
            success=best_score >= self._threshold,
            total_tokens=total_tokens,
            best_score=best_score,
        )

    # ── Steps ─────────────────────────────────────────────────────────────────

    async def _act(self, task: str, prior_reflections: list[str], context: dict) -> tuple[str, int]:
        if self._client is None:
            return f"[stub action: {task[:60]}]", 0

        reflection_block = ""
        if prior_reflections:
            reflection_block = "\n\nPrior attempt reflections (incorporate these):\n" + "\n".join(
                f"  Attempt {i + 1}: {r}" for i, r in enumerate(prior_reflections)
            )

        ctx_block = "\n".join(f"  {k}: {str(v)[:200]}" for k, v in context.items()) if context else ""

        prompt = f"Task: {task}\n{ctx_block}{reflection_block}\n\nProvide your best response."
        try:
            resp = self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                thinking={"type": "adaptive"},
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            return text, resp.usage.input_tokens + resp.usage.output_tokens
        except Exception as exc:
            return f"Act error: {exc}", 0

    async def _evaluate(self, task: str, action: str, criteria: str) -> tuple[str, float, int]:
        if self._client is None:
            return "Stub evaluation", 0.80, 0

        criteria_text = criteria or "accuracy, completeness, clarity, and practical usefulness"
        prompt = (
            f"Task: {task}\n\nResponse:\n{action[:800]}\n\n"
            f"Evaluate against: {criteria_text}\n\n"
            "Respond in exactly this format:\n"
            "EVALUATION: <one paragraph>\n"
            "SCORE: <0.0–1.0>"
        )
        try:
            resp = self._client.messages.create(
                model=self._model,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            evaluation = ""
            score = 0.7
            for line in text.splitlines():
                if line.startswith("EVALUATION:"):
                    evaluation = line[11:].strip()
                elif line.startswith("SCORE:"):
                    try:
                        score = max(0.0, min(1.0, float(line[6:].strip())))
                    except ValueError:
                        pass
            return evaluation or text[:200], score, resp.usage.input_tokens + resp.usage.output_tokens
        except Exception as exc:
            return f"Eval error: {exc}", 0.5, 0

    async def _reflect(self, task: str, action: str, evaluation: str, score: float) -> tuple[str, int]:
        if self._client is None:
            return f"[stub reflection, score={score:.2f}]", 0

        prompt = (
            f"Task: {task}\n\nMy response (excerpt): {action[:400]}\n\n"
            f"Evaluation: {evaluation}\nScore: {score:.2f}\n\n"
            "In 2–3 specific, actionable sentences: what went wrong and what will you do differently next time?"
        )
        try:
            resp = self._client.messages.create(
                model=self._model,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            return text, resp.usage.input_tokens + resp.usage.output_tokens
        except Exception as exc:
            return f"Reflect error: {exc}", 0
