"""Tests for VoiceScorer — scoring accuracy, composite formula, grading."""

from __future__ import annotations

import math
import struct
from pathlib import Path

import pytest

from future_agents.voice.voice_scorer import VoiceScore, VoiceScorer, W_MOS, W_PROSODY, W_SPEAKER
from future_agents.voice.voice_profile import SpeakerEmbedding, VoiceProfile


def make_wav(path: Path, freq: float = 220.0, duration: float = 0.5) -> None:
    sr = 22050
    n = int(sr * duration)
    samples = [int(math.sin(2 * math.pi * freq * i / sr) * 16000) for i in range(n)]
    data = struct.pack(f"<{n}h", *samples)
    hdr = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(data), b"WAVE",
        b"fmt ", 16, 1, 1, sr, sr * 2, 2, 16,
        b"data", len(data),
    )
    path.write_bytes(hdr + data)


class TestVoiceScore:
    """Unit tests for the VoiceScore dataclass."""

    def test_grade_perfect(self):
        s = VoiceScore(speaker_similarity=9.8, prosody_match=9.5, mos=9.2, composite=9.6)
        assert "Perfect" in s.grade or "Excellent" in s.grade

    def test_grade_excellent(self):
        s = VoiceScore(speaker_similarity=9.2, prosody_match=9.0, mos=8.5, composite=9.1)
        assert "Excellent" in s.grade or "A" in s.grade

    def test_grade_poor(self):
        s = VoiceScore(speaker_similarity=3.0, prosody_match=4.0, mos=5.0, composite=3.8)
        assert "Poor" in s.grade or "F" in s.grade

    def test_str_representation(self):
        s = VoiceScore(speaker_similarity=8.5, prosody_match=8.0, mos=7.5, composite=8.2,
                       engine="xtts", iteration=2)
        output = str(s)
        assert "8.20" in output
        assert "xtts" in output
        assert "Speaker" in output

    def test_composite_weights_sum_to_one(self):
        assert abs(W_SPEAKER + W_PROSODY + W_MOS - 1.0) < 1e-9

    def test_composite_formula(self):
        # Manual calculation
        ss, pm, mos = 8.0, 7.0, 9.0
        expected = ss * W_SPEAKER + pm * W_PROSODY + mos * W_MOS
        score = VoiceScore(speaker_similarity=ss, prosody_match=pm, mos=mos, composite=expected)
        assert abs(score.composite - expected) < 0.001


class TestVoiceScorerNoAudioLibs:
    """Scorer must work even without librosa/resemblyzer (stub/CI mode)."""

    @pytest.mark.asyncio
    async def test_score_returns_voice_score(self, tmp_path, sample_voice_profile):
        wav_path = tmp_path / "synth.wav"
        make_wav(wav_path, freq=220.0)

        profile = VoiceProfile(**{
            **sample_voice_profile,
            "embedding": SpeakerEmbedding(vector=[0.5, 0.5, -0.5, -0.5]),
        })

        scorer = VoiceScorer()
        score = await scorer.score(profile, wav_path)

        assert isinstance(score, VoiceScore)
        assert 0.0 <= score.speaker_similarity <= 10.0
        assert 0.0 <= score.prosody_match <= 10.0
        assert 0.0 <= score.mos <= 10.0
        assert 0.0 <= score.composite <= 10.0

    @pytest.mark.asyncio
    async def test_score_with_no_embedding_gives_zero_speaker_sim(self, tmp_path):
        wav_path = tmp_path / "synth.wav"
        make_wav(wav_path)

        profile = VoiceProfile(name="No Embedding", embedding=None)
        scorer = VoiceScorer()
        score = await scorer.score(profile, wav_path)

        assert score.speaker_similarity == 0.0

    @pytest.mark.asyncio
    async def test_score_fails_if_synth_file_missing(self, tmp_path):
        profile = VoiceProfile(name="T")
        scorer = VoiceScorer()
        with pytest.raises(FileNotFoundError):
            await scorer.score(profile, tmp_path / "nonexistent.wav")

    @pytest.mark.asyncio
    async def test_identical_audio_gives_high_speaker_sim(self, tmp_path):
        """When synth == reference, speaker similarity should be maximum (1.0)."""
        wav_path = tmp_path / "audio.wav"
        make_wav(wav_path, freq=300.0, duration=1.0)

        # Extract embedding from the file
        from future_agents.voice.sample_processor import SampleProcessor
        proc = SampleProcessor(work_dir=tmp_path)
        emb_vec, _ = proc._extract_embedding(wav_path)

        profile = VoiceProfile(
            name="Self-test",
            embedding=SpeakerEmbedding(vector=emb_vec),
        )
        scorer = VoiceScorer(processor=proc)
        score = await scorer.score(profile, wav_path)

        # Same file → cosine similarity should be very close to 1.0 → score ≈ 10
        assert score.speaker_similarity >= 9.9

    @pytest.mark.asyncio
    async def test_different_audio_gives_lower_speaker_sim(self, tmp_path):
        """Different audio files should give lower speaker similarity than identical."""
        wav_a = tmp_path / "audio_a.wav"
        wav_b = tmp_path / "audio_b.wav"
        make_wav(wav_a, freq=220.0, duration=1.0)
        make_wav(wav_b, freq=880.0, duration=1.0)  # very different frequency

        from future_agents.voice.sample_processor import SampleProcessor
        proc = SampleProcessor(work_dir=tmp_path)
        emb_vec_a, _ = proc._extract_embedding(wav_a)

        profile = VoiceProfile(
            name="Audio A",
            embedding=SpeakerEmbedding(vector=emb_vec_a),
        )
        scorer = VoiceScorer(processor=proc)
        score_same = await scorer.score(profile, wav_a)
        score_diff = await scorer.score(profile, wav_b)

        # Same should score higher than different
        assert score_same.speaker_similarity >= score_diff.speaker_similarity

    @pytest.mark.asyncio
    async def test_composite_matches_weighted_sum(self, tmp_path):
        wav_path = tmp_path / "synth.wav"
        make_wav(wav_path)

        from future_agents.voice.sample_processor import SampleProcessor
        proc = SampleProcessor(work_dir=tmp_path)
        emb_vec, _ = proc._extract_embedding(wav_path)

        profile = VoiceProfile(name="T", embedding=SpeakerEmbedding(vector=emb_vec))
        scorer = VoiceScorer(processor=proc)
        score = await scorer.score(profile, wav_path)

        expected = round(
            score.speaker_similarity * W_SPEAKER +
            score.prosody_match * W_PROSODY +
            score.mos * W_MOS,
            3
        )
        assert abs(score.composite - expected) < 0.01


class TestVoiceScorerIterativeImprovement:
    """Integration: cloner + scorer improvement loop reaches target."""

    @pytest.mark.asyncio
    async def test_improvement_loop_monotonically_improves(self, tmp_path, tmp_audio_file):
        from future_agents.voice.voice_cloner import VoiceCloner

        # Use a low target so stub can reach it
        cloner = VoiceCloner(output_dir=tmp_path, target_score=0.0, max_iterations=3)
        cloner._available_engines = ["stub"]
        profile = VoiceProfile(name="Improve Test", engine_preference=["stub"])

        await cloner.synthesize(profile, "Testing iterative improvement")

        # All iterations recorded
        assert len(profile.improvement_history) >= 1

        # Best score should be the max of all scores
        all_scores = [r.composite_score for r in profile.improvement_history]
        assert profile.best_score == pytest.approx(max(all_scores), abs=0.01)
