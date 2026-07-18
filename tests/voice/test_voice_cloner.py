"""Tests for VoiceCloner — synthesis, engine selection, improvement loop."""

from __future__ import annotations

import asyncio
import struct
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from future_agents.voice.voice_cloner import (
    MAX_ITERATIONS,
    PERSONALITY_PRESETS,
    SynthesisResult,
    VoiceCloner,
)
from future_agents.voice.voice_profile import PersonalityType, VoiceProfile


def make_profile(**kwargs) -> VoiceProfile:
    return VoiceProfile(
        name=kwargs.get("name", "Test Voice"),
        personality=kwargs.get("personality", PersonalityType.CUSTOM),
        engine_preference=kwargs.get("engine_preference", ["stub"]),
        **{k: v for k, v in kwargs.items() if k not in ("name", "personality", "engine_preference")},
    )


def make_wav(path: Path, duration_s: float = 0.5, freq: float = 220.0) -> None:
    """Write a minimal sine-wave WAV for testing."""
    import math
    sr = 22050
    num = int(sr * duration_s)
    samples = [int(math.sin(2 * math.pi * freq * i / sr) * 16000) for i in range(num)]
    data = struct.pack(f"<{num}h", *samples)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(data), b"WAVE",
        b"fmt ", 16, 1, 1, sr, sr * 2, 2, 16,
        b"data", len(data),
    )
    path.write_bytes(header + data)


class TestVoiceClonerInit:
    def test_detects_stub_when_no_engines(self, tmp_path):
        cloner = VoiceCloner(output_dir=tmp_path)
        assert "stub" in cloner._available_engines

    def test_output_dir_created(self, tmp_path):
        out = tmp_path / "synth_output"
        cloner = VoiceCloner(output_dir=out)
        assert out.exists()


class TestStubSynthesis:
    """End-to-end tests using the stub engine (no external deps required)."""

    @pytest.fixture
    def cloner(self, tmp_path) -> VoiceCloner:
        c = VoiceCloner(output_dir=tmp_path, target_score=0.0, max_iterations=1)
        c._available_engines = ["stub"]
        return c

    @pytest.mark.asyncio
    async def test_synthesize_returns_result(self, cloner, tmp_path):
        profile = make_profile(engine_preference=["stub"])
        result = await cloner.synthesize(profile, "Hello world", "test_out.wav")
        assert isinstance(result, SynthesisResult)
        assert result.audio_path.exists()
        assert result.engine == "stub"

    @pytest.mark.asyncio
    async def test_synthesize_creates_valid_wav(self, cloner):
        profile = make_profile(engine_preference=["stub"])
        result = await cloner.synthesize(profile, "Test audio output")
        data = result.audio_path.read_bytes()
        assert data[:4] == b"RIFF"
        assert b"WAVE" in data[:12]

    @pytest.mark.asyncio
    async def test_synthesize_records_improvement_history(self, cloner):
        profile = make_profile(engine_preference=["stub"])
        await cloner.synthesize(profile, "History check")
        assert len(profile.improvement_history) >= 1

    @pytest.mark.asyncio
    async def test_synthesize_marks_best_result(self, cloner):
        profile = make_profile(engine_preference=["stub"])
        result = await cloner.synthesize(profile, "Best check")
        assert result.is_best is True

    @pytest.mark.asyncio
    async def test_result_has_score_between_0_and_10(self, cloner):
        profile = make_profile(engine_preference=["stub"])
        result = await cloner.synthesize(profile, "Score range check")
        assert 0.0 <= result.score <= 10.0

    @pytest.mark.asyncio
    async def test_different_profiles_produce_different_audio(self, cloner, tmp_path):
        p1 = make_profile(name="A", pitch_offset=0.0, energy=0.5, engine_preference=["stub"])
        p2 = make_profile(name="B", pitch_offset=5.0, energy=0.9, engine_preference=["stub"])

        r1 = await cloner.synthesize(p1, "Same text", "out_a.wav")
        r2 = await cloner.synthesize(p2, "Same text", "out_b.wav")

        # Different pitch should produce different byte content
        assert r1.audio_path.read_bytes() != r2.audio_path.read_bytes()


class TestPersonalityPresets:
    def test_all_personalities_have_presets(self):
        for personality in PersonalityType:
            if personality == PersonalityType.CUSTOM:
                continue
            assert personality in PERSONALITY_PRESETS, \
                f"No preset for {personality}"

    def test_presets_have_required_keys(self):
        required = {"speed", "temperature", "emotion"}
        for personality, preset in PERSONALITY_PRESETS.items():
            missing = required - set(preset.keys())
            assert not missing, \
                f"{personality}: preset missing keys {missing}"

    def test_speed_values_in_bounds(self):
        for personality, preset in PERSONALITY_PRESETS.items():
            speed = preset["speed"]
            assert 0.5 <= speed <= 2.5, \
                f"{personality}: speed={speed} out of [0.5, 2.5]"

    def test_temperature_values_in_bounds(self):
        for personality, preset in PERSONALITY_PRESETS.items():
            temp = preset["temperature"]
            assert 0.0 <= temp <= 1.0, \
                f"{personality}: temperature={temp} out of [0, 1]"


class TestImprovementLoop:
    """Test the iterative improvement mechanism."""

    @pytest.mark.asyncio
    async def test_early_stop_when_target_reached(self, tmp_path):
        """When target is 0, should stop after 1 iteration."""
        cloner = VoiceCloner(output_dir=tmp_path, target_score=0.0, max_iterations=5)
        cloner._available_engines = ["stub"]
        profile = make_profile(engine_preference=["stub"])
        result = await cloner.synthesize(profile, "Early stop test")
        assert result.iteration == 1

    @pytest.mark.asyncio
    async def test_respects_max_iterations(self, tmp_path):
        """With an impossible target, should stop at max_iterations."""
        cloner = VoiceCloner(output_dir=tmp_path, target_score=10.0, max_iterations=3)
        cloner._available_engines = ["stub"]
        profile = make_profile(engine_preference=["stub"])
        await cloner.synthesize(profile, "Max iter test")
        assert len(profile.improvement_history) <= 3

    def test_tune_parameters_reduces_temperature_on_low_similarity(self, tmp_path):
        cloner = VoiceCloner(output_dir=tmp_path)
        score = MagicMock()
        score.speaker_similarity = 5.0
        score.prosody_match = 9.0
        score.composite = 6.0

        params = {"temperature": 0.70, "speed": 1.0}
        new_params = cloner._tune_parameters(params, score, iteration=1)
        assert new_params["temperature"] < params["temperature"]

    def test_tune_parameters_adjusts_speed_on_low_prosody(self, tmp_path):
        cloner = VoiceCloner(output_dir=tmp_path)
        score = MagicMock()
        score.speaker_similarity = 9.0
        score.prosody_match = 5.0
        score.composite = 7.0

        params = {"temperature": 0.65, "speed": 1.4}
        new_params = cloner._tune_parameters(params, score, iteration=1)
        # Speed should move toward 1.0
        assert new_params["speed"] < 1.4


class TestCreateProfileFromSample:
    """Tests for create_profile_from_sample (uses stub processor)."""

    @pytest.mark.asyncio
    async def test_creates_profile_with_embedding(self, tmp_path, tmp_audio_file):
        cloner = VoiceCloner(output_dir=tmp_path)
        profile = await cloner.create_profile_from_sample(
            sample_path=tmp_audio_file,
            name="My Test Voice",
            personality=PersonalityType.FRIENDLY_HELPER,
        )
        assert profile.name == "My Test Voice"
        assert profile.personality == PersonalityType.FRIENDLY_HELPER
        assert profile.embedding is not None
        assert len(profile.embedding.vector) > 0

    @pytest.mark.asyncio
    async def test_applies_personality_preset(self, tmp_path, tmp_audio_file):
        cloner = VoiceCloner(output_dir=tmp_path)
        profile = await cloner.create_profile_from_sample(
            tmp_audio_file,
            name="Executive Test",
            personality=PersonalityType.FORMAL_EXECUTIVE,
        )
        # FORMAL_EXECUTIVE preset has speed=0.88
        assert profile.speaking_rate == pytest.approx(0.88, abs=0.01)
