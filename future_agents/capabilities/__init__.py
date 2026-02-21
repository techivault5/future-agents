"""Agent capabilities — speech, listen, and learn.

These are composable mixins that can be added to any agent:
  - SpeechMixin — broadcast, announce, teach, ask, report
  - ListenMixin — subscribe, inbox, event wiring
  - LearnMixin — memory, pattern detection, skill evolution

Or use SmartAgent (in core.smart_agent) which combines all three.
"""

from future_agents.capabilities.learn import (
    AgentMemory,
    Insight,
    InsightType,
    LearnMixin,
    LearningEngine,
    Memory,
    MemoryType,
    SkillEvolution,
)
from future_agents.capabilities.listen import (
    Inbox,
    ListenFilter,
    ListenMixin,
    Subscription,
)
from future_agents.capabilities.speech import (
    ConversationLedger,
    SpeechMixin,
    SpeechType,
    Utterance,
)

__all__ = [
    # Speech
    "SpeechMixin",
    "SpeechType",
    "Utterance",
    "ConversationLedger",
    # Listen
    "ListenMixin",
    "ListenFilter",
    "Subscription",
    "Inbox",
    # Learn
    "LearnMixin",
    "LearningEngine",
    "AgentMemory",
    "Memory",
    "MemoryType",
    "Insight",
    "InsightType",
    "SkillEvolution",
]
