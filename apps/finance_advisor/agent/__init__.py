"""Agentic layer for the Finance Advisor — bring your own LLM key.

    from finance_advisor.agent import build_toolset, run_agent

    tools = build_toolset(sdk)
    for event in run_agent(message="can I afford a 35L home loan?",
                           tools=tools, provider_name="anthropic", api_key=key):
        print(event)

The user's key arrives per request and is never stored. Transcripts stay in
this process. Sensitive memories are redacted before they can reach a provider.
"""

from finance_advisor.agent.loop import (
    MAX_ROUNDS,
    SYSTEM_PROMPT,
    clear_session,
    get_history,
    run_agent,
)
from finance_advisor.agent.providers import (
    PROVIDERS,
    ProviderError,
    ProviderTurn,
    ToolCall,
    get_provider,
    provider_catalog,
    resolve_key,
)
from finance_advisor.agent.tools import Tool, build_toolset, execute

__all__ = [
    "MAX_ROUNDS",
    "PROVIDERS",
    "SYSTEM_PROMPT",
    "ProviderError",
    "ProviderTurn",
    "Tool",
    "ToolCall",
    "build_toolset",
    "clear_session",
    "execute",
    "get_history",
    "get_provider",
    "provider_catalog",
    "resolve_key",
    "run_agent",
]
