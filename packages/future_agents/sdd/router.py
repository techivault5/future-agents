"""MCP-style engine routing — pick the model per role and per intent.

The pipeline never names a model inline. It asks the router, which resolves
role → engine from the rulebook, lets an intent keyword override it, and falls
back when an engine is unavailable. Swapping vendors is a config edit.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Optional, Protocol, runtime_checkable

from future_agents.sdd.config import SpecKitConfig


@dataclass
class EngineCall:
    role: str
    system: str
    prompt: str
    max_tokens: int = 4096
    temperature: float = 0.2


@runtime_checkable
class Engine(Protocol):
    """Anything that can turn a prompt into text."""

    name: str

    def complete(self, call: EngineCall) -> str: ...  # pragma: no cover - protocol


class NullEngine:
    """Default engine: returns nothing, so every stage stays deterministic.

    Stages are written to work without a model; an engine only enriches them.
    That keeps the pipeline runnable in CI, offline, and inside tests.
    """

    name = "null"

    def complete(self, call: EngineCall) -> str:
        return ""


class CallableEngine:
    """Adapter around a plain function — the seam tests and custom backends use."""

    def __init__(self, name: str, fn: Callable[[EngineCall], str]) -> None:
        self.name = name
        self._fn = fn

    def complete(self, call: EngineCall) -> str:
        return self._fn(call)


class AnthropicEngine:
    """Claude-backed engine. Optional dependency — install the `ai` extra."""

    def __init__(self, model: str = "claude-opus-5", api_key_env: str = "ANTHROPIC_API_KEY"):
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError("anthropic SDK not installed — pip install -e '.[ai]'") from exc
        key = os.environ.get(api_key_env)
        if not key:
            raise RuntimeError(f"{api_key_env} is not set")
        self.name = model
        self._client = anthropic.Anthropic(api_key=key)

    def complete(self, call: EngineCall) -> str:  # pragma: no cover - network
        response = self._client.messages.create(
            model=self.name,
            max_tokens=call.max_tokens,
            system=call.system,
            messages=[{"role": "user", "content": call.prompt}],
        )
        return "".join(block.text for block in response.content if block.type == "text")


@dataclass
class RouteDecision:
    role: str
    engine: str
    rationale: str
    fallback: str = ""


@dataclass
class RouteRecord:
    role: str
    engine: str
    ok: bool
    detail: str = ""


class EngineRouter:
    """Resolves role/intent → engine and holds the live engine instances."""

    def __init__(
        self,
        config: Optional[SpecKitConfig] = None,
        engines: Optional[dict[str, Engine]] = None,
        default: Optional[Engine] = None,
    ) -> None:
        self.config = config or SpecKitConfig()
        self.default = default or NullEngine()
        self._engines: dict[str, Engine] = dict(engines or {})
        self.history: list[RouteRecord] = []

    def register(self, name: str, engine: Engine) -> None:
        self._engines[name] = engine

    def decide(self, role: str, intent: str = "") -> RouteDecision:
        agents = self.config.agents
        role_cfg = agents.roles.get(role)
        engine = role_cfg.engine if role_cfg else agents.default_engine
        rationale = f"role default for {role}"

        low = intent.lower()
        for keyword, target in agents.intent_routes.items():
            if keyword.lower() in low:
                engine, rationale = target, f"intent route on '{keyword}'"
                break

        fallback = (role_cfg.fallback if role_cfg else "") or agents.default_engine
        return RouteDecision(role=role, engine=engine, rationale=rationale, fallback=fallback)

    def engine_for(self, role: str, intent: str = "") -> tuple[Engine, RouteDecision]:
        decision = self.decide(role, intent)
        engine = self._engines.get(decision.engine)
        if engine is None and decision.fallback:
            engine = self._engines.get(decision.fallback)
        return engine or self.default, decision

    def run(self, call: EngineCall, intent: str = "") -> str:
        """Best-effort completion. An engine failure degrades, never crashes."""
        engine, decision = self.engine_for(call.role, intent)
        try:
            out = engine.complete(call)
            self.history.append(RouteRecord(call.role, engine.name, ok=True))
            return out
        except Exception as exc:  # engines are remote; the pipeline must survive
            self.history.append(
                RouteRecord(call.role, decision.engine, ok=False, detail=str(exc)[:200])
            )
            return ""
