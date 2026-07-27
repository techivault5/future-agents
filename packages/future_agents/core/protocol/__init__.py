"""Interaction protocol — standardized message format for agent-to-agent communication."""

from future_agents.core.protocol.messages import (
    AgentMessage,
    DelegationRequest,
    DelegationResponse,
    HandoffRequest,
    MessageRole,
    MessageType,
)

__all__ = [
    "AgentMessage",
    "DelegationRequest",
    "DelegationResponse",
    "HandoffRequest",
    "MessageRole",
    "MessageType",
]
