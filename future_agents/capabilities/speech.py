"""Speech capability — agents can speak, broadcast, announce, and share.

Speech is how agents push information outward. An agent with speech can:
  - **Broadcast** to all agents (announcements, status updates)
  - **Speak** to a specific agent (directed messages)
  - **Announce** learnings (share discoveries with the system)
  - **Report** findings (structured output to the conversation log)

Every speech act is logged in the conversation ledger so other agents
(and the learning engine) can replay and learn from it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from future_agents.core.events import Event, EventBus

logger = logging.getLogger(__name__)


class SpeechType(str, Enum):
    """What kind of speech act this is."""
    BROADCAST = "broadcast"  # To all agents
    DIRECT = "direct"  # To a specific agent
    ANNOUNCE = "announce"  # Share a learning/discovery
    REPORT = "report"  # Structured output/finding
    QUESTION = "question"  # Ask another agent something
    TEACH = "teach"  # Share knowledge to help another agent improve


@dataclass
class Utterance:
    """A single speech act — one thing an agent said."""

    id: str = field(default_factory=lambda: uuid4().hex[:12])
    speaker: str = ""  # Agent ID
    speech_type: SpeechType = SpeechType.BROADCAST
    recipient: str = ""  # Empty for broadcasts, agent ID for directed
    topic: str = ""  # What this is about (e.g. "capability.gap_found")
    content: dict[str, Any] = field(default_factory=dict)
    text: str = ""  # Human-readable summary
    tags: list[str] = field(default_factory=list)
    confidence: float = 1.0  # How confident the speaker is
    in_reply_to: str = ""  # ID of utterance this responds to
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ConversationLedger:
    """Append-only log of all speech acts in the system.

    The ledger is the shared memory of all agent communication. The
    learning engine reads it to find patterns, and agents can query
    it to understand what's been discussed.
    """

    def __init__(self, max_entries: int = 5000) -> None:
        self._entries: list[Utterance] = []
        self._max_entries = max_entries

    def record(self, utterance: Utterance) -> None:
        self._entries.append(utterance)
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries:]

    def by_speaker(self, speaker: str, limit: int = 50) -> list[Utterance]:
        return [u for u in self._entries if u.speaker == speaker][-limit:]

    def by_topic(self, topic: str, limit: int = 50) -> list[Utterance]:
        return [u for u in self._entries if topic in u.topic][-limit:]

    def by_type(self, speech_type: SpeechType, limit: int = 50) -> list[Utterance]:
        return [u for u in self._entries if u.speech_type == speech_type][-limit:]

    def by_tag(self, tag: str, limit: int = 50) -> list[Utterance]:
        return [u for u in self._entries if tag in u.tags][-limit:]

    def between(self, speaker: str, recipient: str, limit: int = 50) -> list[Utterance]:
        """Get the conversation between two specific agents."""
        return [
            u for u in self._entries
            if (u.speaker == speaker and u.recipient == recipient)
            or (u.speaker == recipient and u.recipient == speaker)
        ][-limit:]

    def recent(self, limit: int = 50) -> list[Utterance]:
        return self._entries[-limit:]

    def announcements(self, limit: int = 50) -> list[Utterance]:
        return self.by_type(SpeechType.ANNOUNCE, limit)

    def teachings(self, limit: int = 50) -> list[Utterance]:
        return self.by_type(SpeechType.TEACH, limit)

    @property
    def size(self) -> int:
        return len(self._entries)

    def stats(self) -> dict[str, Any]:
        by_speaker: dict[str, int] = {}
        by_type: dict[str, int] = {}
        for u in self._entries:
            by_speaker[u.speaker] = by_speaker.get(u.speaker, 0) + 1
            by_type[u.speech_type.value] = by_type.get(u.speech_type.value, 0) + 1
        return {
            "total": len(self._entries),
            "by_speaker": by_speaker,
            "by_type": by_type,
        }


class SpeechMixin:
    """Mixin that gives any agent the ability to speak.

    Add to an agent class:
        class MyAgent(BaseAgent, SpeechMixin):
            ...

    Then call self.say(), self.broadcast(), self.announce(), etc.
    Requires self.agent_id and self.event_bus to be set (provided by BaseAgent).
    """

    _ledger: ConversationLedger | None = None

    def attach_ledger(self, ledger: ConversationLedger) -> None:
        self._ledger = ledger

    async def say(
        self,
        text: str,
        recipient: str = "",
        topic: str = "",
        content: dict[str, Any] | None = None,
        speech_type: SpeechType = SpeechType.DIRECT,
        tags: list[str] | None = None,
        confidence: float = 1.0,
        in_reply_to: str = "",
    ) -> Utterance:
        """Speak — the core speech primitive."""
        utterance = Utterance(
            speaker=self.agent_id,  # type: ignore[attr-defined]
            speech_type=speech_type,
            recipient=recipient,
            topic=topic,
            content=content or {},
            text=text,
            tags=tags or [],
            confidence=confidence,
            in_reply_to=in_reply_to,
        )

        # Record in the ledger
        if self._ledger:
            self._ledger.record(utterance)

        # Emit event so listeners can react
        event_bus: EventBus = self.event_bus  # type: ignore[attr-defined]
        await event_bus.emit(Event(
            type=f"speech.{speech_type.value}",
            source=self.agent_id,  # type: ignore[attr-defined]
            data={
                "utterance_id": utterance.id,
                "topic": topic,
                "text": text,
                "recipient": recipient,
                "tags": tags or [],
            },
        ))

        return utterance

    async def broadcast(
        self,
        text: str,
        topic: str = "",
        content: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> Utterance:
        """Broadcast a message to all agents."""
        return await self.say(
            text=text,
            topic=topic,
            content=content,
            speech_type=SpeechType.BROADCAST,
            tags=tags,
        )

    async def announce(
        self,
        text: str,
        topic: str = "",
        content: dict[str, Any] | None = None,
        confidence: float = 1.0,
        tags: list[str] | None = None,
    ) -> Utterance:
        """Announce a discovery or learning to the system."""
        return await self.say(
            text=text,
            topic=topic,
            content=content,
            speech_type=SpeechType.ANNOUNCE,
            confidence=confidence,
            tags=["learning", *(tags or [])],
        )

    async def teach(
        self,
        recipient: str,
        text: str,
        topic: str = "",
        content: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> Utterance:
        """Teach another agent something — share knowledge to help it improve."""
        return await self.say(
            text=text,
            recipient=recipient,
            topic=topic,
            content=content,
            speech_type=SpeechType.TEACH,
            tags=["teaching", *(tags or [])],
        )

    async def ask(
        self,
        recipient: str,
        text: str,
        topic: str = "",
        content: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> Utterance:
        """Ask another agent a question."""
        return await self.say(
            text=text,
            recipient=recipient,
            topic=topic,
            content=content,
            speech_type=SpeechType.QUESTION,
            tags=["question", *(tags or [])],
        )

    async def report(
        self,
        text: str,
        topic: str = "",
        content: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> Utterance:
        """Report a structured finding."""
        return await self.say(
            text=text,
            topic=topic,
            content=content,
            speech_type=SpeechType.REPORT,
            tags=["report", *(tags or [])],
        )
