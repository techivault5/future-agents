"""Model providers — one call, one shape, no key in module state.

Three implementations behind one Protocol:

    LunaProvider     the real target. Structured output if the endpoint
                     supports it, a JSON-mode fallback if it does not.
    AnthropicProvider  the same contract against the Anthropic SDK.
    EchoProvider     deterministic, offline, free. The entire pipeline —
                     routing, planning, identifier resolution, the guard, the
                     executor — is testable in CI with no key and no spend,
                     which is the only way the rest of this gets tested at all.

The API key is a call argument or read from the environment at call time. It is
never module state, never an attribute that ends up in a repr, and never
logged. A provider that stores a key is a provider that leaks one in a stack
trace.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from beta_queries.agent.contract import QueryPlan

DEFAULT_TIMEOUT = 8.0
# The budget allows one call at ~900 ms. Anything slower has already lost, so
# fail fast and let the orchestrator degrade rather than blocking the turn.
DEFAULT_MAX_TOKENS = 1500


@dataclass
class Completion:
    text: str
    model: str = ""
    ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def truncated(self) -> bool:
        """A truncated plan is not a plan — it is half a SQL statement."""
        return self.stop_reason in ("max_tokens", "length")


class Provider(Protocol):
    name: str

    def complete(
        self,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Completion: ...


def _strip_fences(text: str) -> str:
    """Models wrap JSON in ``` even when told not to. Costly to retry over."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
        stripped = re.sub(r"\n?```$", "", stripped)
    return stripped.strip()


def parse_plan(text: str) -> QueryPlan:
    """Parse a completion into the one shape the planner may return.

    Raises `ValueError` with the offending text attached, because the repair
    path needs to show the model what it actually produced.
    """
    cleaned = _strip_fences(text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        # Last resort: the first balanced object in the response. Models
        # sometimes narrate before the JSON despite instructions.
        match = re.search(r"\{.*\}", cleaned, re.S)
        if not match:
            raise ValueError(f"no JSON object in model output: {cleaned[:200]!r}") from exc
        data = json.loads(match.group(0))
    return QueryPlan.model_validate(data)


class EchoProvider:
    """Deterministic, offline, free — the CI and demo provider.

    Returns a plan built from what the orchestrator already worked out: the
    routed datasource, the tables the graph chose, the join path it resolved.
    That is not cheating. Everything it fills in is deterministic anyway; the
    model's real job is the projection and the predicates, and a fixed answer
    for those is exactly what a test wants.
    """

    name = "echo"

    def __init__(self, plans: dict[str, dict[str, Any]] | None = None) -> None:
        # question fragment -> canned plan, for tests that need a specific shape
        self.plans = plans or {}
        self.calls: list[tuple[str, str]] = []

    def complete(
        self,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Completion:
        self.calls.append((system, user))
        # Match on the question line only. The prompt also carries the
        # conversation history, so matching the whole thing means a previous
        # turn's question silently selects this turn's plan.
        asked = _field_line(user, "question")
        for fragment, plan in self.plans.items():
            if fragment.lower() in asked.lower():
                return Completion(text=json.dumps(plan), model="echo", ms=1)

        payload = _plan_from_prompt(user)
        return Completion(text=json.dumps(payload), model="echo", ms=1)


def _plan_from_prompt(user: str) -> dict[str, Any]:
    """Build a plausible plan from the context block the prompt already carries.

    The prompt states the datasource, the dialect, the tables and the join
    path; this reads them back out. When it cannot, it returns a clarification
    — which is the honest default and exercises that path in tests.
    """
    datasource = _field(user, "datasource")
    dialect = _field(user, "dialect") or "duckdb"
    tables = re.findall(r"^\s*-\s+table:\s*(\S+)", user, re.M)

    if not datasource or not tables:
        return {
            "datasource_id": datasource or "unknown",
            "dialect": dialect,
            "intent": "lookup",
            "confidence": 0.3,
            "clarification": {
                "question": "Which data source should I use?",
                "options": [
                    {"id": "a", "label": "the first one"},
                    {"id": "b", "label": "the second one"},
                ],
            },
        }

    relname = tables[0].split(".", 1)[1] if "." in tables[0] else tables[0]
    return {
        "datasource_id": datasource,
        "dialect": dialect,
        "intent": "aggregate_count",
        "confidence": 0.9,
        "sql": f"SELECT COUNT(*) AS n FROM {relname}",
        "params": [],
        "referenced_tables": [relname],
        "assumptions": [],
        "answer_template": "There are {{n}} rows.",
    }


def _field(text: str, name: str) -> str:
    match = re.search(rf"^{name}:\s*(\S+)", text, re.M | re.I)
    return match.group(1).strip() if match else ""


def _field_line(text: str, name: str) -> str:
    """The whole rest of the line, not just the first token."""
    match = re.search(rf"^{name}:\s*(.+)$", text, re.M | re.I)
    return match.group(1).strip() if match else ""


class LunaProvider:
    """GPT Luna. The endpoint contract is still open, so this is deliberately thin.

    Two things are pinned because changing them later is expensive: the key is
    read at call time, and a truncated response is an error rather than a plan.
    Everything else — structured output vs JSON mode, streaming, prefix
    caching — is a question for whoever owns the endpoint, and lives behind
    this one method.
    """

    name = "luna"

    def __init__(
        self, base_url: str = "", model: str = "gpt-luna", key_env: str = "LUNA_API_KEY"
    ) -> None:
        self.base_url = base_url or os.environ.get("LUNA_BASE_URL", "")
        self.model = model
        self.key_env = key_env

    def complete(
        self,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Completion:
        import urllib.error
        import urllib.request

        key = os.environ.get(self.key_env)
        if not key:
            raise RuntimeError(
                f"{self.key_env} is not set — the planner cannot run without a model"
            )
        if not self.base_url:
            raise RuntimeError("LUNA_BASE_URL is not set")

        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": DEFAULT_MAX_TOKENS,
            "temperature": 0,
        }
        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": schema}

        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        )
        started = time.perf_counter()
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read())
        ms = int((time.perf_counter() - started) * 1000)

        choice = (data.get("choices") or [{}])[0]
        usage = data.get("usage") or {}
        return Completion(
            text=(choice.get("message") or {}).get("content", ""),
            model=data.get("model", self.model),
            ms=ms,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            stop_reason=choice.get("finish_reason", ""),
            raw=data,
        )


class AnthropicProvider:
    """The same contract over the Anthropic SDK, imported lazily."""

    name = "anthropic"

    def __init__(self, model: str = "claude-opus-5", key_env: str = "ANTHROPIC_API_KEY") -> None:
        self.model = model
        self.key_env = key_env

    def complete(
        self,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Completion:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("anthropic is not installed: pip install -e '.[ai]'") from exc

        key = os.environ.get(self.key_env)
        if not key:
            raise RuntimeError(f"{self.key_env} is not set")

        client = anthropic.Anthropic(api_key=key, timeout=timeout)
        started = time.perf_counter()
        message = client.messages.create(
            model=self.model,
            max_tokens=DEFAULT_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        ms = int((time.perf_counter() - started) * 1000)
        text = "".join(block.text for block in message.content if block.type == "text")
        return Completion(
            text=text,
            model=message.model,
            ms=ms,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            stop_reason=message.stop_reason or "",
        )
