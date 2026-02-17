"""Event bus — async event propagation between agents."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine
from uuid import uuid4

logger = logging.getLogger(__name__)

EventHandler = Callable[["Event"], Coroutine[Any, Any, None]]


@dataclass
class Event:
    """An event that flows through the system."""

    type: str  # e.g. "capability.updated", "policy.violated", "task.completed"
    source: str  # Agent ID that emitted the event
    data: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EventBus:
    """Pub/sub event bus for inter-agent communication.

    Agents subscribe to event types (supports wildcards like "capability.*")
    and receive events asynchronously.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._history: list[Event] = []
        self._max_history = 1000

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Subscribe to events matching a type pattern.

        Supports exact match ("task.completed") or prefix wildcard ("task.*").
        """
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """Remove a handler from an event type."""
        if event_type in self._handlers:
            self._handlers[event_type] = [
                h for h in self._handlers[event_type] if h is not handler
            ]

    async def emit(self, event: Event) -> None:
        """Emit an event to all matching subscribers."""
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        handlers = self._matching_handlers(event.type)
        if not handlers:
            return

        results = await asyncio.gather(
            *(h(event) for h in handlers),
            return_exceptions=True,
        )
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "Event handler error for %s: %s",
                    event.type,
                    result,
                    exc_info=result,
                )

    def _matching_handlers(self, event_type: str) -> list[EventHandler]:
        """Find all handlers matching an event type, including wildcards."""
        handlers: list[EventHandler] = []
        for pattern, pattern_handlers in self._handlers.items():
            if pattern == event_type:
                handlers.extend(pattern_handlers)
            elif pattern.endswith(".*"):
                prefix = pattern[:-2]
                if event_type.startswith(prefix + "."):
                    handlers.extend(pattern_handlers)
            elif pattern == "*":
                handlers.extend(pattern_handlers)
        return handlers

    def recent_events(self, event_type: str | None = None, limit: int = 50) -> list[Event]:
        """Get recent events, optionally filtered by type."""
        events = self._history
        if event_type:
            events = [e for e in events if e.type == event_type]
        return events[-limit:]
