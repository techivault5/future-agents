"""VoiceProfile — complete specification for an agent voice.

A VoiceProfile captures:
  - Speaker characteristics (pitch, rate, energy)
  - Personality and accent type
  - Speaker embedding (extracted from audio sample — no raw audio stored)
  - Engine preferences and fallback order
  - Iteration history for accuracy improvement tracking
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class PersonalityType(str, Enum):
    """Broad personality archetype that shapes prosody and delivery style."""

    FORMAL_EXECUTIVE = "formal-executive"  # Precise, measured, authoritative
    FRIENDLY_HELPER = "friendly-helper"  # Warm, approachable, upbeat
    TECHNICAL_EXPERT = "technical-expert"  # Analytical, deliberate, detail-oriented
    ENTHUSIASTIC_INNOVATOR = "enthusiastic-innovator"  # Fast, energetic, excited
    CALM_COUNSELOR = "calm-counselor"  # Slow, soothing, patient
    DIRECT_COMMANDER = "direct-commander"  # Terse, commanding, no-nonsense
    CREATIVE_STORYTELLER = "creative-storyteller"  # Expressive, varied, imaginative
    EMPATHETIC_ADVISOR = "empathetic-advisor"  # Gentle, understanding, reassuring
    SHARP_ANALYST = "sharp-analyst"  # Crisp, factual, precise
    GLOBAL_CONNECTOR = "global-connector"  # Neutral, clear, inclusive
    CUSTOM = "custom"  # User-defined profile


class AccentType(str, Enum):
    """Accent / dialect settings for the voice."""

    AMERICAN_GENERAL = "american-general"
    AMERICAN_SOUTHERN = "american-southern"
    BRITISH_RP = "british-rp"
    BRITISH_NORTHERN = "british-northern"
    AUSTRALIAN = "australian"
    CANADIAN = "canadian"
    IRISH = "irish"
    SCOTTISH = "scottish"
    SOUTH_AFRICAN = "south-african"
    INDIAN_ENGLISH = "indian-english"
    SINGAPORE_ENGLISH = "singapore-english"
    NEUTRAL_GLOBAL = "neutral-global"
    CUSTOM = "custom"  # Learned from sample — no preset


class EmotionWeight(BaseModel):
    """How much of each emotion is blended into the voice."""

    neutral: float = Field(0.7, ge=0.0, le=1.0)
    friendly: float = Field(0.1, ge=0.0, le=1.0)
    confident: float = Field(0.1, ge=0.0, le=1.0)
    empathetic: float = Field(0.05, ge=0.0, le=1.0)
    authoritative: float = Field(0.05, ge=0.0, le=1.0)


class SpeakerEmbedding(BaseModel):
    """Speaker embedding extracted from an audio sample.

    Embeddings are 256-d or 512-d float vectors derived by a speaker-encoder
    (e.g. resemblyzer, speechbrain ECAPA-TDNN). Raw audio is NEVER stored —
    only this compact representation is needed for synthesis and sharing.
    """

    vector: list[float] = Field(default_factory=list, description="Speaker embedding vector")
    model: str = Field("resemblyzer", description="Model used to extract this embedding")
    sample_hash: str = Field("", description="SHA-256 of the source audio (for integrity)")
    sample_duration_s: float = Field(0.0, description="Duration of the reference clip used")
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def dimension(self) -> int:
        return len(self.vector)

    def cosine_similarity(self, other: "SpeakerEmbedding") -> float:
        """Cosine similarity between two speaker embeddings (0–1)."""
        import math

        if not self.vector or not other.vector:
            return 0.0
        a, b = self.vector, other.vector
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x**2 for x in a))
        mag_b = math.sqrt(sum(y**2 for y in b))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)


class ImprovementRecord(BaseModel):
    """One iteration of the voice accuracy improvement loop."""

    iteration: int
    engine: str
    parameters: dict[str, Any]
    speaker_similarity: float
    prosody_score: float
    mos_score: float
    composite_score: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class VoiceProfile(BaseModel):
    """Complete, portable specification for one agent voice.

    Designed to be:
      - Serialisable to YAML/JSON for storage and sharing
      - Engine-agnostic (works with XTTS, ElevenLabs, OpenVoice, RVC)
      - Self-contained — includes embedding so raw audio is not required
    """

    # ── Identity ──────────────────────────────────────────────────
    id: str = Field(default_factory=lambda: f"vp-{uuid4().hex[:12]}")
    name: str
    description: str = ""
    created_by: str = "user"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    version: str = "1.0.0"
    tags: list[str] = Field(default_factory=list)

    # ── Personality & Accent ───────────────────────────────────────
    personality: PersonalityType = PersonalityType.CUSTOM
    accent: AccentType = AccentType.CUSTOM

    # ── Acoustic Parameters ────────────────────────────────────────
    speaking_rate: float = Field(1.0, ge=0.5, le=2.5, description="Speech rate multiplier (1.0 = normal)")
    pitch_offset: float = Field(0.0, ge=-12.0, le=12.0, description="Semitone pitch offset from neutral")
    energy: float = Field(0.8, ge=0.0, le=1.0, description="Energy/loudness normalised level")
    pause_factor: float = Field(1.0, ge=0.5, le=2.0, description="Inter-phrase pause duration multiplier")

    # ── Emotion Blend ──────────────────────────────────────────────
    emotion_weights: EmotionWeight = Field(default_factory=EmotionWeight)

    # ── Speaker Embedding (from sample) ───────────────────────────
    embedding: SpeakerEmbedding | None = None

    # ── Engine Preferences ────────────────────────────────────────
    engine_preference: list[str] = Field(
        default_factory=lambda: ["xtts", "openvoice", "elevenlabs"], description="Ordered list of TTS engines to try"
    )
    engine_config: dict[str, dict[str, Any]] = Field(
        default_factory=dict, description="Per-engine configuration overrides"
    )

    # ── Accuracy Tracking ─────────────────────────────────────────
    best_score: float = Field(0.0, description="Best composite score achieved (0–10)")
    improvement_history: list[ImprovementRecord] = Field(default_factory=list)
    target_score: float = Field(9.5, description="Target composite score for improvement loop")

    # ── Gender / Demographics (for TTS engine hints) ──────────────
    gender: str = Field("neutral", description="neutral | male | female")

    # ── SSML Overrides ────────────────────────────────────────────
    ssml_prefix: str = Field("", description="SSML to prepend to all utterances")
    ssml_suffix: str = Field("", description="SSML to append to all utterances")

    def record_improvement(self, record: ImprovementRecord) -> None:
        self.improvement_history.append(record)
        if record.composite_score > self.best_score:
            self.best_score = record.composite_score
        self.updated_at = datetime.now(timezone.utc)

    def to_yaml(self) -> str:
        """Serialise to YAML string (embedding vector omitted for readability)."""
        import yaml

        data = self.model_dump(mode="json")
        # Replace long embedding vector with a summary
        if data.get("embedding") and data["embedding"].get("vector"):
            dim = len(data["embedding"]["vector"])
            data["embedding"]["vector"] = f"<{dim}-d embedding omitted>"
        return yaml.dump(data, default_flow_style=False, allow_unicode=True)

    @classmethod
    def from_yaml_file(cls, path: str | Path) -> "VoiceProfile":
        import yaml

        data = yaml.safe_load(Path(path).read_text())
        return cls.model_validate(data)

    def fingerprint(self) -> str:
        """Short hash that uniquely identifies this profile's acoustic parameters."""
        key = json.dumps(
            {
                "id": self.id,
                "speaking_rate": self.speaking_rate,
                "pitch_offset": self.pitch_offset,
                "energy": self.energy,
                "personality": self.personality,
                "accent": self.accent,
            },
            sort_keys=True,
        )
        return hashlib.sha256(key.encode()).hexdigest()[:16]
