"""Bring-your-own-key provider adapters.

Every adapter takes the API key as a call argument, uses it for exactly one
request and lets it fall out of scope. Nothing here writes a key to disk, to a
log line, or to a memory record — the only copy that outlives a request is the
one the user keeps in their own browser.

    anthropic   official SDK, claude-opus-5, adaptive thinking
    openai      any OpenAI-compatible /chat/completions endpoint (base_url override)
    ollama      the same wire format against a local server — no key at all
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field

DEFAULT_MAX_TOKENS = 4096
HTTP_TIMEOUT = 120


class ProviderError(RuntimeError):
    """Anything that stopped a provider call, phrased for the end user."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ProviderTurn:
    """One assistant turn, normalised across providers."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    # Provider-native assistant content, replayed verbatim on the next request.
    # Anthropic rejects a tool-use continuation whose thinking blocks were
    # dropped, so paraphrasing the turn back into plain text is not an option.
    raw: object | None = None
    usage: dict = field(default_factory=dict)


# ── Anthropic ────────────────────────────────────────────────────────────────


def _to_anthropic(messages: list[dict]) -> list[dict]:
    """Canonical transcript → Anthropic blocks, batching consecutive results.

    Anthropic carries tool results in a *user* message, and every result for one
    assistant turn has to arrive in the same message.
    """
    out: list[dict] = []
    pending: list[dict] = []

    def flush() -> None:
        if pending:
            out.append({"role": "user", "content": list(pending)})
            pending.clear()

    for msg in messages:
        role = msg["role"]
        if role == "tool":
            pending.append(
                {
                    "type": "tool_result",
                    "tool_use_id": msg["tool_call_id"],
                    "content": msg["content"],
                }
            )
            continue
        flush()
        if role == "assistant" and msg.get("raw") is not None:
            out.append({"role": "assistant", "content": msg["raw"]})
        else:
            out.append({"role": role, "content": msg.get("content") or ""})
    flush()
    return out


class AnthropicProvider:
    name = "anthropic"
    label = "Anthropic (Claude)"
    default_model = "claude-opus-5"
    key_env = "ANTHROPIC_API_KEY"
    requires_key = True
    supports_base_url = False

    def complete(
        self,
        *,
        key: str,
        model: str,
        system: str,
        messages: list[dict],
        tools: list[dict],
        base_url: str = "",
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> ProviderTurn:
        try:
            import anthropic
        except ImportError as err:
            raise ProviderError(
                "The anthropic SDK is not installed — run: pip install -e '.[ai]'"
            ) from err

        client = anthropic.Anthropic(api_key=key)
        try:
            resp = client.messages.create(
                model=model or self.default_model,
                max_tokens=max_tokens,
                system=system,
                messages=_to_anthropic(messages),
                tools=[
                    {
                        "name": t["name"],
                        "description": t["description"],
                        "input_schema": t["parameters"],
                    }
                    for t in tools
                ],
                thinking={"type": "adaptive"},
            )
        except anthropic.AuthenticationError as err:
            raise ProviderError("Anthropic rejected the API key.") from err
        except anthropic.RateLimitError as err:
            raise ProviderError("Anthropic rate limit hit — retry shortly.") from err
        except anthropic.APIStatusError as err:
            raise ProviderError(f"Anthropic returned {err.status_code}: {err.message}") from err
        except anthropic.APIConnectionError as err:
            raise ProviderError("Could not reach the Anthropic API.") from err

        text = "".join(b.text for b in resp.content if b.type == "text")
        calls = [
            ToolCall(id=b.id, name=b.name, arguments=dict(b.input))
            for b in resp.content
            if b.type == "tool_use"
        ]
        return ProviderTurn(
            text=text,
            tool_calls=calls,
            raw=[b.model_dump(exclude_none=True) for b in resp.content],
            usage={
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
            },
        )


# ── OpenAI-compatible (OpenAI, Ollama, and anything speaking the same shape) ──


def _to_openai(system: str, messages: list[dict]) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system}]
    for msg in messages:
        if msg["role"] == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": msg["tool_call_id"],
                    "content": msg["content"],
                }
            )
        elif msg["role"] == "assistant" and msg.get("tool_calls"):
            out.append(
                {
                    "role": "assistant",
                    "content": msg.get("content") or None,
                    "tool_calls": [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                        }
                        for c in msg["tool_calls"]
                    ],
                }
            )
        else:
            out.append({"role": msg["role"], "content": msg.get("content") or ""})
    return out


@dataclass
class OpenAICompatibleProvider:
    name: str
    label: str
    base_url: str
    default_model: str
    key_env: str = ""
    requires_key: bool = True
    supports_base_url: bool = True

    def complete(
        self,
        *,
        key: str,
        model: str,
        system: str,
        messages: list[dict],
        tools: list[dict],
        base_url: str = "",
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> ProviderTurn:
        payload = {
            "model": model or self.default_model,
            "max_tokens": max_tokens,
            "messages": _to_openai(system, messages),
            "tools": [{"type": "function", "function": t} for t in tools],
            "tool_choice": "auto",
        }
        url = (base_url or self.base_url).rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                body = json.load(resp)
        except urllib.error.HTTPError as err:
            detail = err.read().decode(errors="replace")[:300]
            raise ProviderError(f"{self.label} returned {err.code}: {detail}") from err
        except (urllib.error.URLError, TimeoutError) as err:
            raise ProviderError(f"Could not reach {self.label} at {url}.") from err
        except json.JSONDecodeError as err:
            raise ProviderError(f"{self.label} sent a response that was not JSON.") from err

        choices = body.get("choices") or []
        if not choices:
            raise ProviderError(f"{self.label} returned no choices: {str(body)[:200]}")
        msg = choices[0].get("message") or {}
        calls = [
            ToolCall(
                id=c.get("id") or uuid.uuid4().hex[:12],
                name=c["function"]["name"],
                arguments=_loads_args(c["function"].get("arguments")),
            )
            for c in (msg.get("tool_calls") or [])
        ]
        return ProviderTurn(
            text=msg.get("content") or "",
            tool_calls=calls,
            usage=body.get("usage") or {},
        )


def _loads_args(raw: object) -> dict:
    """Arguments arrive as a JSON string from OpenAI, as a dict from Ollama."""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _ollama_base() -> str:
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/") + "/v1"


PROVIDERS: dict[str, object] = {
    "anthropic": AnthropicProvider(),
    "openai": OpenAICompatibleProvider(
        name="openai",
        label="OpenAI-compatible",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o",
        key_env="OPENAI_API_KEY",
    ),
    "ollama": OpenAICompatibleProvider(
        name="ollama",
        label="Ollama (local)",
        base_url=_ollama_base(),
        default_model="llama3.1",
        requires_key=False,
        supports_base_url=True,
    ),
}


def get_provider(name: str):
    if name not in PROVIDERS:
        raise ProviderError(f"unknown provider {name!r}; available: {sorted(PROVIDERS)}")
    return PROVIDERS[name]


def resolve_key(provider, supplied: str = "") -> str:
    """User-supplied key wins; otherwise fall back to the operator's env var.

    Returned to the caller only — never stored, never echoed back to the client.
    """
    if supplied:
        return supplied
    if provider.key_env:
        return os.environ.get(provider.key_env, "")
    return ""


def provider_catalog() -> list[dict]:
    """What the UI needs to render the picker — booleans only, never a key."""
    return [
        {
            "name": p.name,
            "label": p.label,
            "default_model": p.default_model,
            "requires_key": p.requires_key,
            "key_env": p.key_env,
            "server_key_available": bool(p.key_env and os.environ.get(p.key_env)),
            "supports_base_url": p.supports_base_url,
        }
        for p in PROVIDERS.values()
    ]
