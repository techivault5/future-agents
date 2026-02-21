"""Listen capability — agents can subscribe, receive, and process input.

Listen is how agents receive information. An agent with listen can:
  - **Subscribe** to speech topics, types, or specific agents
  - **Receive** utterances and events matching its subscriptions
  - **Process** incoming information through handlers
  - **Absorb** teachings from other agents
  - **React** to broadcasts and announcements

The listen system feeds directly into the learning engine — everything
an agent hears becomes potential material for learning.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine
from uuid import uuid4

from future_agents.capabilities.speech import (
    ConversationLedger,
    SpeechType,
    Utterance,
)
from future_agents.core.events import Event, EventBus

logger = logging.getLogger(__name__)

# A handler that processes an incoming utterance
UtteranceHandler = Callable[[Utterance], Coroutine[Any, Any, None]]


class ListenFilter(str, Enum):
    """What dimension to filter incoming speech on."""
    TOPIC = "topic"  # Filter by topic substring
    SPEAKER = "speaker"  # Filter by speaker agent ID
    TYPE = "type"  # Filter by SpeechType
    TAG = "tag"  # Filter by tag


@dataclass
class Subscription:
    """A subscription to incoming speech."""

    id: str = field(default_factory=lambda: uuid4().hex[:8])
    filter_type: ListenFilter = ListenFilter.TOPIC
    filter_value: str = ""
    handler: UtteranceHandler | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Inbox:
    """Unprocessed incoming utterances for an agent."""

    items: list[Utterance] = field(default_factory=list)
    max_size: int = 500

    def add(self, utterance: Utterance) -> None:
        self.items.append(utterance)
        if len(self.items) > self.max_size:
            self.items = self.items[-self.max_size:]

    def unread(self, limit: int = 50) -> list[Utterance]:
        return self.items[-limit:]

    def clear(self) -> int:
        count = len(self.items)
        self.items = []
        return count

    @property
    def size(self) -> int:
        return len(self.items)


class ListenMixin:
    """Mixin that gives any agent the ability to listen.

    Add to an agent class:
        class MyAgent(BaseAgent, SpeechMixin, ListenMixin):
            ...

    Then call self.subscribe_to(), and incoming speech matching the
    subscriptions will be delivered to the agent's inbox and handlers.
    """

    _subscriptions: list[Subscription]
    _inbox: Inbox
    _ledger: ConversationLedger | None
    _listen_initialized: bool

    def init_listen(self) -> None:
        """Initialize listen state. Call from agent's __init__ or initialize()."""
        self._subscriptions = []
        self._inbox = Inbox()
        self._listen_initialized = True

    def _ensure_listen(self) -> None:
        if not getattr(self, "_listen_initialized", False):
            self.init_listen()

    @property
    def inbox(self) -> Inbox:
        self._ensure_listen()
        return self._inbox

    def subscribe_to(
        self,
        filter_type: ListenFilter,
        filter_value: str,
        handler: UtteranceHandler | None = None,
    ) -> Subscription:
        """Subscribe to incoming speech matching a filter.

        Args:
            filter_type: What to filter on (topic, speaker, type, tag)
            filter_value: The value to match
            handler: Optional async handler called when a match arrives.
                     If None, utterances just go to the inbox.
        """
        self._ensure_listen()
        sub = Subscription(
            filter_type=filter_type,
            filter_value=filter_value,
            handler=handler,
        )
        self._subscriptions.append(sub)
        return sub

    def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a subscription."""
        self._ensure_listen()
        before = len(self._subscriptions)
        self._subscriptions = [s for s in self._subscriptions if s.id != subscription_id]
        return len(self._subscriptions) < before

    async def on_speech(self, utterance: Utterance) -> None:
        """Called when an utterance arrives via the event bus.

        Routes to matching subscription handlers and adds to inbox.
        Override for custom processing logic.
        """
        self._ensure_listen()
        agent_id = getattr(self, "agent_id", "")

        # Don't listen to yourself
        if utterance.speaker == agent_id:
            return

        # Check if this utterance matches any subscriptions
        matched = False
        for sub in self._subscriptions:
            if self._matches(sub, utterance):
                matched = True
                if sub.handler:
                    try:
                        await sub.handler(utterance)
                    except Exception:
                        logger.exception(
                            "Listen handler error in %s for sub %s",
                            agent_id, sub.id,
                        )

        # Always add to inbox if it was directed at us, a broadcast, or matched a sub
        if (
            matched
            or utterance.recipient == agent_id
            or utterance.speech_type == SpeechType.BROADCAST
            or utterance.speech_type == SpeechType.ANNOUNCE
        ):
            self._inbox.add(utterance)

    async def start_listening(self, event_bus: EventBus) -> None:
        """Wire up the event bus to deliver speech events to this agent.

        Call this during agent initialization after the event bus is set.
        """
        self._ensure_listen()

        async def _speech_handler(event: Event) -> None:
            # Reconstruct the utterance from the event
            data = event.data
            utterance = Utterance(
                id=data.get("utterance_id", ""),
                speaker=event.source,
                speech_type=SpeechType(event.type.split(".")[-1]) if "." in event.type else SpeechType.BROADCAST,
                recipient=data.get("recipient", ""),
                topic=data.get("topic", ""),
                text=data.get("text", ""),
                tags=data.get("tags", []),
                content=data.get("content", {}),
            )
            await self.on_speech(utterance)

        # Subscribe to all speech events
        event_bus.subscribe("speech.*", _speech_handler)

    def get_teachings(self) -> list[Utterance]:
        """Get all teachings directed at this agent."""
        self._ensure_listen()
        agent_id = getattr(self, "agent_id", "")
        return [
            u for u in self._inbox.items
            if u.speech_type == SpeechType.TEACH
            and (u.recipient == agent_id or u.recipient == "")
        ]

    def get_questions(self) -> list[Utterance]:
        """Get all unanswered questions directed at this agent."""
        self._ensure_listen()
        agent_id = getattr(self, "agent_id", "")
        return [
            u for u in self._inbox.items
            if u.speech_type == SpeechType.QUESTION and u.recipient == agent_id
        ]

    @staticmethod
    def _matches(sub: Subscription, utterance: Utterance) -> bool:
        """Check if an utterance matches a subscription filter."""
        if sub.filter_type == ListenFilter.TOPIC:
            return sub.filter_value in utterance.topic
        elif sub.filter_type == ListenFilter.SPEAKER:
            return utterance.speaker == sub.filter_value
        elif sub.filter_type == ListenFilter.TYPE:
            return utterance.speech_type.value == sub.filter_value
        elif sub.filter_type == ListenFilter.TAG:
            return sub.filter_value in utterance.tags
        return False
