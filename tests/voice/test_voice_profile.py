"""Tests for VoiceProfile — creation, serialisation, embedding, sharing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from future_agents.voice.voice_profile import (
    AccentType,
    EmotionWeight,
    ImprovementRecord,
    PersonalityType,
    SpeakerEmbedding,
    VoiceProfile,
)

VOICE_AGENTS_DIR = Path(__file__).parent.parent.parent / "agents" / "voice"


# ── SpeakerEmbedding ──────────────────────────────────────────────

class TestSpeakerEmbedding:
    def test_cosine_similarity_identical(self):
        v = [0.5, 0.5, 0.5, 0.5]
        e = SpeakerEmbedding(vector=v)
        assert e.cosine_similarity(e) == pytest.approx(1.0, abs=1e-5)

    def test_cosine_similarity_orthogonal(self):
        e1 = SpeakerEmbedding(vector=[1.0, 0.0])
        e2 = SpeakerEmbedding(vector=[0.0, 1.0])
        assert e1.cosine_similarity(e2) == pytest.approx(0.0, abs=1e-5)

    def test_cosine_similarity_opposite(self):
        e1 = SpeakerEmbedding(vector=[1.0, 0.0])
        e2 = SpeakerEmbedding(vector=[-1.0, 0.0])
        assert e1.cosine_similarity(e2) == pytest.approx(-1.0, abs=1e-5)

    def test_cosine_similarity_empty_returns_zero(self):
        e1 = SpeakerEmbedding(vector=[1.0, 0.0])
        e2 = SpeakerEmbedding(vector=[])
        assert e1.cosine_similarity(e2) == 0.0

    def test_dimension_property(self):
        e = SpeakerEmbedding(vector=[0.1] * 256)
        assert e.dimension == 256

    def test_similarity_range(self):
        import random
        v1 = [random.gauss(0, 1) for _ in range(64)]
        v2 = [random.gauss(0, 1) for _ in range(64)]
        e1 = SpeakerEmbedding(vector=v1)
        e2 = SpeakerEmbedding(vector=v2)
        sim = e1.cosine_similarity(e2)
        assert -1.0 <= sim <= 1.0


# ── VoiceProfile ──────────────────────────────────────────────────

class TestVoiceProfile:
    def test_default_id_generated(self):
        p = VoiceProfile(name="Test")
        assert p.id.startswith("vp-")
        assert len(p.id) > 5

    def test_unique_ids(self):
        ids = {VoiceProfile(name="Test").id for _ in range(100)}
        assert len(ids) == 100

    def test_personality_enum(self):
        p = VoiceProfile(name="T", personality=PersonalityType.FORMAL_EXECUTIVE)
        assert p.personality == PersonalityType.FORMAL_EXECUTIVE

    def test_accent_enum(self):
        p = VoiceProfile(name="T", accent=AccentType.BRITISH_RP)
        assert p.accent == AccentType.BRITISH_RP

    def test_speaking_rate_bounds(self):
        with pytest.raises(Exception):
            VoiceProfile(name="T", speaking_rate=0.1)  # below 0.5
        with pytest.raises(Exception):
            VoiceProfile(name="T", speaking_rate=5.0)  # above 2.5

    def test_pitch_offset_bounds(self):
        with pytest.raises(Exception):
            VoiceProfile(name="T", pitch_offset=20.0)  # above 12

    def test_energy_bounds(self):
        with pytest.raises(Exception):
            VoiceProfile(name="T", energy=1.5)  # above 1.0

    def test_record_improvement_updates_best(self):
        p = VoiceProfile(name="T")
        assert p.best_score == 0.0

        from datetime import datetime, timezone
        rec = ImprovementRecord(
            iteration=1, engine="xtts", parameters={},
            speaker_similarity=8.5, prosody_score=8.0,
            mos_score=7.5, composite_score=8.2,
        )
        p.record_improvement(rec)
        assert p.best_score == 8.2

        rec2 = ImprovementRecord(
            iteration=2, engine="xtts", parameters={},
            speaker_similarity=9.2, prosody_score=9.0,
            mos_score=8.5, composite_score=9.1,
        )
        p.record_improvement(rec2)
        assert p.best_score == 9.1
        assert len(p.improvement_history) == 2

    def test_record_improvement_never_decreases_best(self):
        p = VoiceProfile(name="T")
        for score in [9.0, 7.0, 8.0]:
            p.record_improvement(ImprovementRecord(
                iteration=1, engine="stub", parameters={},
                speaker_similarity=score, prosody_score=score,
                mos_score=score, composite_score=score,
            ))
        assert p.best_score == 9.0

    def test_to_yaml_no_raw_vector(self):
        p = VoiceProfile(name="T", embedding=SpeakerEmbedding(vector=[0.1] * 256))
        yml = p.to_yaml()
        # Vector should be summarised, not raw
        assert "256-d embedding omitted" in yml
        assert len(yml.split("\n")) < 200  # shouldn't be huge

    def test_to_yaml_parseable(self):
        p = VoiceProfile(name="My Voice", personality=PersonalityType.CALM_COUNSELOR)
        yml = p.to_yaml()
        parsed = yaml.safe_load(yml)
        assert parsed["name"] == "My Voice"

    def test_json_roundtrip(self):
        p = VoiceProfile(
            name="Roundtrip Test",
            personality=PersonalityType.SHARP_ANALYST,
            accent=AccentType.AUSTRALIAN,
            speaking_rate=0.95,
            pitch_offset=1.0,
            energy=0.8,
            embedding=SpeakerEmbedding(vector=[0.5, -0.3, 0.1]),
        )
        json_str = p.model_dump_json()
        p2 = VoiceProfile.model_validate_json(json_str)
        assert p2.name == p.name
        assert p2.personality == p.personality
        assert p2.embedding.vector == p.embedding.vector

    def test_fingerprint_deterministic(self):
        p = VoiceProfile(name="T", speaking_rate=0.9, pitch_offset=-1.0)
        assert p.fingerprint() == p.fingerprint()

    def test_fingerprint_differs_on_param_change(self):
        p1 = VoiceProfile(name="T", speaking_rate=0.9)
        p2 = VoiceProfile(name="T", speaking_rate=1.1)
        # Different IDs → always different fingerprints; even if we force same id:
        p2_copy = p2.model_copy(update={"id": p1.id})
        assert p1.fingerprint() != p2_copy.fingerprint()


# ── Pre-built voice agent YAMLs ───────────────────────────────────

class TestPrebuiltVoiceAgentYamls:
    """All 10 voice agent YAML definitions must be valid and complete."""

    @pytest.fixture(scope="class")
    def voice_yamls(self) -> list[dict]:
        files = sorted(VOICE_AGENTS_DIR.glob("voice-*.yaml"))
        assert len(files) >= 10, f"Expected ≥10 voice agent YAMLs, found {len(files)}"
        return [yaml.safe_load(f.read_text()) for f in files]

    def test_all_have_required_fields(self, voice_yamls):
        required = {
            "id", "name", "role", "type", "personality", "accent",
            "description", "speaking_rate", "pitch_offset", "energy",
            "engine_preference", "use_cases", "tags", "guardrails_profile",
        }
        for data in voice_yamls:
            missing = required - set(data.keys())
            assert not missing, f"Voice agent {data.get('id')} missing: {missing}"

    def test_all_ids_unique(self, voice_yamls):
        ids = [d["id"] for d in voice_yamls]
        assert len(ids) == len(set(ids))

    def test_all_personalities_valid(self, voice_yamls):
        valid = {p.value for p in PersonalityType}
        for data in voice_yamls:
            assert data["personality"] in valid, \
                f"{data['id']}: invalid personality '{data['personality']}'"

    def test_all_accents_valid(self, voice_yamls):
        valid = {a.value for a in AccentType}
        for data in voice_yamls:
            assert data["accent"] in valid, \
                f"{data['id']}: invalid accent '{data['accent']}'"

    def test_speaking_rate_in_bounds(self, voice_yamls):
        for data in voice_yamls:
            rate = data["speaking_rate"]
            assert 0.5 <= rate <= 2.5, f"{data['id']}: speaking_rate={rate} out of bounds"

    def test_pitch_offset_in_bounds(self, voice_yamls):
        for data in voice_yamls:
            offset = data["pitch_offset"]
            assert -12 <= offset <= 12, f"{data['id']}: pitch_offset={offset} out of bounds"

    def test_all_have_use_cases(self, voice_yamls):
        for data in voice_yamls:
            assert len(data.get("use_cases", [])) >= 3, \
                f"{data['id']} has fewer than 3 use cases"

    def test_all_have_sample_phrases(self, voice_yamls):
        for data in voice_yamls:
            assert len(data.get("sample_phrases", [])) >= 2, \
                f"{data['id']} has fewer than 2 sample phrases"

    def test_all_ten_personalities_represented(self, voice_yamls):
        personalities = {d["personality"] for d in voice_yamls}
        expected = {
            "formal-executive", "friendly-helper", "technical-expert",
            "enthusiastic-innovator", "calm-counselor", "direct-commander",
            "creative-storyteller", "empathetic-advisor", "sharp-analyst",
            "global-connector",
        }
        missing = expected - personalities
        assert not missing, f"Missing personalities: {missing}"

    def test_cover_all_guardrails_profiles(self, voice_yamls):
        profiles = {d.get("guardrails_profile") for d in voice_yamls}
        # Should use at least 2 different profiles
        assert len(profiles) >= 2
