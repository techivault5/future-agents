"""VoiceAgent — a BaseAgent with a voice identity.

A VoiceAgent wraps an existing agent (any subclass of BaseAgent) and gives
it a persistent voice. Every time the agent produces a response, the text
can be synthesised using the agent's VoiceProfile.

Usage:
    from future_agents.voice import VoiceAgent, VoiceRegistry, VoiceCloner
    from future_agents.agents.capability_agent import CapabilityAgent

    # Give the capability agent a voice
    base = CapabilityAgent()
    registry = VoiceRegistry()
    profile = registry.load("vp-formal-executive")

    agent = VoiceAgent(base_agent=base, voice_profile=profile)
    await agent.initialize()

    # Execute a task — returns text result + audio path
    context = TaskContext(intent="capability.register", parameters={...})
    result = await agent.execute(context)

    if result.data.get("audio_path"):
        print(f"Audio synthesised: {result.data['audio_path']}")
        print(f"Voice score: {result.data['voice_score']}/10")
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from future_agents.core.base_agent import BaseAgent, TaskContext, TaskResult
from future_agents.models.feedback import ExecutionOutcome
from future_agents.voice.voice_cloner import VoiceCloner
from future_agents.voice.voice_profile import VoiceProfile
from future_agents.voice.voice_registry import VoiceRegistry

logger = logging.getLogger(__name__)


class VoiceAgent(BaseAgent):
    """Decorates any BaseAgent with a synthesised voice.

    The agent executes normally; after a successful response, the text
    content is synthesised into audio using the configured VoiceProfile.

    Voice synthesis is non-blocking by default — the task result is
    returned immediately with a pending audio path, and synthesis
    completes asynchronously.
    """

    def __init__(
        self,
        base_agent: BaseAgent,
        voice_profile: VoiceProfile,
        cloner: Optional[VoiceCloner] = None,
        synthesise_responses: bool = True,
        target_score: float = 9.5,
    ) -> None:
        super().__init__(
            agent_id=f"voice_{base_agent.agent_id}",
            event_bus=base_agent.event_bus,
        )
        self._base = base_agent
        self.voice_profile = voice_profile
        self._cloner = cloner or VoiceCloner(target_score=target_score)
        self.synthesise_responses = synthesise_responses

    @property
    def agent_type(self) -> str:
        return f"voice_{self._base.agent_type}"

    @property
    def capabilities(self) -> list[str]:
        return self._base.capabilities + ["voice_synthesis"]

    async def initialize(self) -> None:
        await self._base.initialize()
        await super().initialize()
        logger.info(
            "VoiceAgent '%s' ready — voice: '%s' (best score: %.1f/10)",
            self.agent_id,
            self.voice_profile.name,
            self.voice_profile.best_score,
        )

    async def shutdown(self) -> None:
        await self._base.shutdown()
        await super().shutdown()

    async def _execute(self, context: TaskContext) -> TaskResult:
        """Delegate to the base agent, then synthesise the response text."""
        result = await self._base.execute(context)

        if not self.synthesise_responses or result.outcome != ExecutionOutcome.SUCCESS:
            return result

        # Extract text content from the result
        text = self._extract_speech_text(result)
        if not text:
            return result

        # Synthesise
        try:
            synth_result = await self._cloner.synthesize(
                profile=self.voice_profile,
                text=text,
                output_filename=f"{context.task_id}_response.wav",
            )
            result.data["audio_path"] = str(synth_result.audio_path)
            result.data["voice_score"] = synth_result.score
            result.data["voice_engine"] = synth_result.engine
            result.data["voice_iterations"] = synth_result.iteration

            await self.emit(
                "agent.voice.synthesised",
                {
                    "task_id": context.task_id,
                    "profile_id": self.voice_profile.id,
                    "score": synth_result.score,
                    "engine": synth_result.engine,
                    "audio_path": str(synth_result.audio_path),
                },
            )

        except Exception as e:
            logger.warning("Voice synthesis failed (non-fatal): %s", e)
            result.data["voice_error"] = str(e)

        return result

    async def assess_self(self) -> dict[str, Any]:
        base_assessment = await self._base.assess_self()
        return {
            **base_assessment,
            "voice_profile_id": self.voice_profile.id,
            "voice_profile_name": self.voice_profile.name,
            "voice_best_score": self.voice_profile.best_score,
            "voice_target_score": self.voice_profile.target_score,
            "voice_engine_preference": self.voice_profile.engine_preference,
            "voice_improvement_iterations": len(self.voice_profile.improvement_history),
        }

    @staticmethod
    def _extract_speech_text(result: TaskResult) -> str:
        """Extract speakable text from a task result."""
        data = result.data

        # Check common response keys
        for key in ("response", "message", "summary", "content", "text", "answer"):
            if key in data and isinstance(data[key], str) and data[key].strip():
                return data[key].strip()

        # Synthesise a short status message if no text found
        if result.outcome == ExecutionOutcome.SUCCESS:
            return "Task completed successfully."
        return ""

    @classmethod
    def from_registry(
        cls,
        base_agent: BaseAgent,
        profile_id: str,
        registry: Optional[VoiceRegistry] = None,
        **kwargs: Any,
    ) -> "VoiceAgent":
        """Convenience factory: load a profile from the registry by ID."""
        reg = registry or VoiceRegistry()
        profile = reg.load(profile_id)
        return cls(base_agent=base_agent, voice_profile=profile, **kwargs)
