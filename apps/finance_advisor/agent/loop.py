"""The agentic loop: ask the model, run the tools it asks for, repeat.

Emits events as it goes so the UI can show tool calls while they happen rather
than a spinner. Transcripts live in this process, keyed by session id — they
never go to the browser and never touch disk, because they contain the user's
financial context.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from collections.abc import Iterator

from finance_advisor.agent.providers import ProviderError, get_provider, resolve_key
from finance_advisor.agent.tools import MAX_RESULT_CHARS, Tool, execute

MAX_ROUNDS = 8
MAX_SESSIONS = 50
MAX_HISTORY_MESSAGES = 40

SYSTEM_PROMPT = """You are the Finance Advisor agent for a user in India who \
also tracks Irish property. You give educational financial guidance — never \
licensed advice, never a recommendation to buy or sell a named security.

How to work:
- Call recall_memory before answering anything personal. The user should not \
have to repeat their income, goals or holdings.
- When the user states a durable fact about themselves, call remember_fact. \
Mark exact salaries, balances and account details sensitive.
- Do the maths with run_skill instead of doing arithmetic in your head. Indian \
tax rules are encoded there and change often.
- Quote live numbers from market_snapshot or fund_navs rather than from memory \
of training data. Say when data is stale or missing.
- The dip-watch / extended signals are rule-based heuristics over price history. \
Present them as such — not as predictions.

How to answer:
- Lead with the answer, then the numbers that support it, then the caveat.
- Use ₹ and Indian digit grouping for Indian amounts.
- Be concrete about trade-offs, and say plainly when something is not knowable.
- Close anything actionable with a one-line reminder that this is educational, \
not licensed financial advice."""


_SESSIONS: OrderedDict[str, list[dict]] = OrderedDict()


def get_history(session: str) -> list[dict]:
    if not session:
        return []
    return _SESSIONS.get(session, [])


def _save_history(session: str, messages: list[dict]) -> None:
    if not session:
        return
    _SESSIONS[session] = messages[-MAX_HISTORY_MESSAGES:]
    _SESSIONS.move_to_end(session)
    while len(_SESSIONS) > MAX_SESSIONS:
        _SESSIONS.popitem(last=False)


def clear_session(session: str) -> bool:
    return _SESSIONS.pop(session, None) is not None


def _stringify(result: object) -> str:
    text = json.dumps(result, default=str)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + f"… [truncated at {MAX_RESULT_CHARS} chars]"
    return text


def run_agent(
    *,
    message: str,
    tools: dict[str, Tool],
    provider_name: str = "anthropic",
    model: str = "",
    api_key: str = "",
    base_url: str = "",
    session: str = "",
    max_rounds: int = MAX_ROUNDS,
    provider: object | None = None,
) -> Iterator[dict]:
    """Drive one user turn to completion, yielding events.

    Events: tool_call | tool_result | text | usage | error | done.
    `provider` is injectable so tests can run the loop without a network call.
    """
    try:
        prov = provider or get_provider(provider_name)
    except ProviderError as err:
        yield {"type": "error", "message": str(err)}
        return

    key = resolve_key(prov, api_key)
    if getattr(prov, "requires_key", False) and not key:
        yield {
            "type": "error",
            "message": (
                f"{prov.label} needs an API key. Paste yours in the key box — it "
                f"stays in this browser tab and is used only for this request "
                f"(or set {prov.key_env} on the server)."
            ),
        }
        return

    messages = list(get_history(session))
    messages.append({"role": "user", "content": message})
    schemas = [t.schema() for t in tools.values()]

    for round_no in range(max_rounds):
        try:
            turn = prov.complete(
                key=key,
                model=model,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=schemas,
                base_url=base_url,
            )
        except ProviderError as err:
            yield {"type": "error", "message": str(err)}
            return

        messages.append(
            {
                "role": "assistant",
                "content": turn.text,
                "tool_calls": turn.tool_calls,
                "raw": turn.raw,
            }
        )
        if turn.usage:
            yield {"type": "usage", "usage": turn.usage, "round": round_no + 1}
        if turn.text:
            yield {"type": "text", "text": turn.text}

        if not turn.tool_calls:
            _save_history(session, messages)
            yield {"type": "done", "rounds": round_no + 1}
            return

        for call in turn.tool_calls:
            yield {"type": "tool_call", "name": call.name, "arguments": call.arguments}
            result = execute(tools, call.name, call.arguments)
            yield {"type": "tool_result", "name": call.name, "result": result}
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.name,
                    "content": _stringify(result),
                }
            )

    _save_history(session, messages)
    yield {
        "type": "error",
        "message": f"Stopped after {max_rounds} tool rounds without a final answer.",
    }
