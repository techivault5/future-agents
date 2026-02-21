"""SmartAgent — an agent that can speak, listen, and learn.

Combines BaseAgent with all three capability mixins. Agents that extend
SmartAgent automatically get:
  - **Speech** — broadcast, announce, teach, ask, report
  - **Listen** — subscribe to topics/speakers/types, inbox, event wiring
  - **Learn** — episodic/semantic/procedural memory, pattern detection, evolution

Usage:
    class MyAgent(SmartAgent):
        @property
        def agent_type(self) -> str:
            return "my_agent"

        @property
        def capabilities(self) -> list[str]:
            return ["my_agent.do_something"]

        async def _execute(self, context: TaskContext) -> TaskResult:
            ...

After each execution, the agent automatically records the outcome into
its learning engine. Teachings received via speech are auto-absorbed.
"""

from __future__ import annotations

import logging
from typing import Any

from future_agents.capabilities.learn import LearnMixin
from future_agents.capabilities.listen import ListenFilter, ListenMixin
from future_agents.capabilities.speech import ConversationLedger, SpeechMixin, SpeechType, Utterance
from future_agents.core.base_agent import BaseAgent, TaskContext, TaskResult
from future_agents.core.events import EventBus
from future_agents.models.feedback import ExecutionOutcome

logger = logging.getLogger(__name__)


class SmartAgent(BaseAgent, SpeechMixin, ListenMixin, LearnMixin):
    """An agent that can speak, listen, and learn.

    Extends BaseAgent with all three capability mixins wired together:
      - After every execution, the result is recorded into learning memory
      - Teachings received via listen are auto-absorbed into learning
      - Insights from learning can be announced via speech
    """

    def __init__(
        self,
        agent_id: str | None = None,
        event_bus: EventBus | None = None,
        ledger: ConversationLedger | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(agent_id=agent_id, event_bus=event_bus)
        # Initialize all mixins
        self.init_listen()
        self.init_learning()
        if ledger:
            self.attach_ledger(ledger)

    async def initialize(self) -> None:
        """Initialize the agent and wire up listening."""
        await super().initialize()
        await self.start_listening(self.event_bus)

        # Auto-subscribe to teachings directed at us
        self.subscribe_to(
            filter_type=ListenFilter.TYPE,
            filter_value=SpeechType.TEACH.value,
            handler=self._on_teaching,
        )

    async def execute(self, context: TaskContext) -> TaskResult:
        """Execute with automatic learning — records every outcome."""
        result = await super().execute(context)

        # Auto-record execution into learning memory
        self.remember_execution(
            intent=context.intent,
            success=result.outcome == ExecutionOutcome.SUCCESS,
            duration_ms=result.duration_ms,
            context=context.parameters,
            errors=result.errors if result.errors else None,
        )

        return result

    async def _on_teaching(self, utterance: Utterance) -> None:
        """Auto-absorb teachings from other agents."""
        agent_id = getattr(self, "agent_id", "")
        if utterance.recipient and utterance.recipient != agent_id:
            return  # Not for us
        self.absorb_teaching(utterance)
        logger.info(
            "Agent %s absorbed teaching from %s on '%s'",
            agent_id, utterance.speaker, utterance.topic,
        )

    async def announce_insights(self) -> int:
        """Run a learning cycle and announce any new insights via speech."""
        result = self.learn_cycle()
        announced = 0

        for insight in self.learning.insights:
            if not insight.applied and insight.actionable:
                await self.announce(
                    text=f"[{insight.insight_type.value}] {insight.title}: {insight.description}",
                    topic=f"learning.{insight.insight_type.value}",
                    content={
                        "insight_id": insight.id,
                        "confidence": insight.confidence,
                        "suggested_action": insight.suggested_action,
                    },
                    confidence=insight.confidence,
                    tags=["insight", insight.insight_type.value],
                )
                insight.applied = True
                announced += 1

        return announced

    async def assess_self(self) -> dict[str, Any]:
        """Self-assessment including learning stats."""
        memory_stats = self.learning.memory.stats()
        return {
            "success_rate": self.success_rate,
            "execution_count": self._execution_count,
            "memories": memory_stats["total_memories"],
            "memory_types": memory_stats.get("by_type", {}),
            "avg_confidence": memory_stats.get("avg_confidence", 0),
            "insights": len(self.learning.insights),
            "evolutions": len(self.learning.evolutions),
            "inbox_size": self.inbox.size,
            "subscriptions": len(self._subscriptions),
        }
