"""Voice module — create, clone, score, and share agent voices.

Quick start:
    from future_agents.voice import VoiceRegistry, VoiceCloner, VoiceScorer

    # Create a voice from a sample recording
    registry = VoiceRegistry()
    profile = await VoiceCloner().create_profile_from_sample(
        sample_path="my_recording.wav",
        name="My Voice",
        personality="friendly",
    )
    registry.save(profile)

    # Synthesise speech
    cloner = VoiceCloner()
    audio_path = await cloner.synthesize(profile, "Hello, I'm your IT assistant!")
    score = await VoiceScorer().score(profile, audio_path, "my_recording.wav")
    print(f"Accuracy: {score.composite}/10")

    # Share with anyone
    pack_path = registry.export_voicepack(profile.id)
    # → my_voice.voicepack   (portable ZIP — no raw audio, just embedding)
"""

from future_agents.voice.voice_profile import VoiceProfile, PersonalityType, AccentType
from future_agents.voice.voice_registry import VoiceRegistry
from future_agents.voice.voice_cloner import VoiceCloner, SynthesisResult
from future_agents.voice.voice_scorer import VoiceScorer, VoiceScore
from future_agents.voice.voice_agent import VoiceAgent
from future_agents.voice.sample_processor import SampleProcessor

__all__ = [
    "VoiceProfile",
    "PersonalityType",
    "AccentType",
    "VoiceRegistry",
    "VoiceCloner",
    "SynthesisResult",
    "VoiceScorer",
    "VoiceScore",
    "VoiceAgent",
    "SampleProcessor",
]
