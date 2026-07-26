"""Message types for inter-agent communication.

This defines the standardized wire format that all agents use to talk
to each other, to the master agent, and to external callers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    """Type of inter-agent message."""

    REQUEST = "request"  # Ask an agent to do something
    RESPONSE = "response"  # Agent's reply
    DELEGATION = "delegation"  # Master delegating to a sub-agent
    HANDOFF = "handoff"  # One agent handing off to another
    NOTIFICATION = "notification"  # Fire-and-forget event
    ERROR = "error"  # Error response


class MessageRole(str, Enum):
    """Who is sending the message."""

    USER = "user"  # External caller / human
    MASTER = "master"  # Master agent
    AGENT = "agent"  # Domain agent
    SYSTEM = "system"  # Infrastructure


class AgentMessage(BaseModel):
    """Universal message format for all agent communication.

    Every interaction in the system uses this format, making it easy
    to log, replay, analyze, and debug agent conversations.
    """

    id: str = Field(default_factory=lambda: uuid4().hex[:16])
    type: MessageType
    role: MessageRole

    # Routing
    sender: str  # Agent ID or "user" or "system"
    recipient: str  # Agent ID or "master" or "broadcast"

    # Content
    intent: str = ""  # What the sender wants (e.g. "capability.register")
    content: dict[str, Any] = Field(default_factory=dict)
    text: str = ""  # Optional human-readable text

    # Context
    conversation_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    parent_message_id: str | None = None  # For threading
    metadata: dict[str, str] = Field(default_factory=dict)

    # Timing
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def reply(
        self,
        content: dict[str, Any] | None = None,
        text: str = "",
        msg_type: MessageType = MessageType.RESPONSE,
    ) -> AgentMessage:
        """Create a reply to this message."""
        return AgentMessage(
            type=msg_type,
            role=MessageRole.AGENT,
            sender=self.recipient,
            recipient=self.sender,
            intent=self.intent,
            content=content or {},
            text=text,
            conversation_id=self.conversation_id,
            parent_message_id=self.id,
        )

    def error_reply(self, error: str) -> AgentMessage:
        """Create an error reply to this message."""
        return AgentMessage(
            type=MessageType.ERROR,
            role=MessageRole.AGENT,
            sender=self.recipient,
            recipient=self.sender,
            intent=self.intent,
            content={"error": error},
            text=error,
            conversation_id=self.conversation_id,
            parent_message_id=self.id,
        )


class DelegationRequest(BaseModel):
    """Master agent delegating a task to a sub-agent.

    Includes full context so the sub-agent can execute independently.
    """

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    from_agent: str  # Master agent ID
    to_agent: str  # Target agent ID
    intent: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)  # Extra context from master
    priority: float = 0.5
    deadline_seconds: int | None = None
    conversation_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DelegationResponse(BaseModel):
    """Sub-agent's response to a delegation request."""

    delegation_id: str
    agent_id: str
    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    duration_ms: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HandoffRequest(BaseModel):
    """One agent handing off to another mid-conversation.

    Used when an agent realizes another agent is better suited for
    the task, or when a multi-agent workflow transitions between stages.
    """

    from_agent: str
    to_agent_type: str  # Agent type to hand off to
    intent: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""  # Why the handoff is happening
    conversation_history: list[AgentMessage] = Field(default_factory=list)
    conversation_id: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
