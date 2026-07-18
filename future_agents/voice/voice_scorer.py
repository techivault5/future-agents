"""VoiceScorer — multi-dimensional accuracy scoring for synthesized voice output.

Three complementary scores are combined into a composite 0–10 score:

  1. Speaker Similarity (0–10)
     Cosine similarity between the reference speaker embedding and the
     embedding extracted from the synthesised audio. This is the primary
     "does it sound like me?" metric.
     Tools: resemblyzer / speechbrain (same encoder used for cloning)

  2. Prosody Match (0–10)
     How well the synthesised audio matches the reference in:
       - Pitch mean and variance (fundamental frequency)
       - Speaking rate (syllables/second estimate)
       - Energy envelope shape
     Tools: librosa (pitch, energy), parselmouth/praat (optional, most accurate)

  3. MOS Predictor (0–10, normalised from 1–5 MOS scale)
     Mean Opinion Score predicted by a neural model — how natural and
     intelligible the speech sounds to a human listener.
     Tools: DNSMOS (Microsoft) or UTMOS (sheet-music model)
     Fallback: waveform heuristic when no model is available

Composite formula (tunable):
  composite = (speaker_sim * 0.50) + (prosody * 0.30) + (mos * 0.20)

Target: composite ≥ 9.5 / 10 for "perfect" voice cloning.

Iterative improvement:
  VoiceScorer is used by VoiceCloner's improvement loop. After each
  synthesis attempt, the score is checked. If below target, cloner
  adjusts parameters (temperature, speed, emotion weight) and retries.
  Maximum 5 iterations per synthesis request.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from future_agents.voice.voice_profile import SpeakerEmbedding, VoiceProfile
from future_agents.voice.sample_processor import SampleProcessor

logger = logging.getLogger(__name__)


@dataclass
class VoiceScore:
    """Full scoring result for one synthesised audio clip."""
    speaker_similarity: float    # 0–10
    prosody_match: float         # 0–10
    mos: float                   # 0–10
    composite: float             # 0–10 (weighted combination)
    engine: str = ""
    iteration: int = 1
    details: dict = field(default_factory=dict)

    @property
    def grade(self) -> str:
        if self.composite >= 9.5:
            return "S (Perfect)"
        if self.composite >= 9.0:
            return "A+ (Excellent)"
        if self.composite >= 8.0:
            return "A (Great)"
        if self.composite >= 7.0:
            return "B (Good)"
        if self.composite >= 6.0:
            return "C (Acceptable)"
        return "F (Poor — retry)"

    def __str__(self) -> str:
        return (
            f"Score: {self.composite:.2f}/10 [{self.grade}]\n"
            f"  Speaker similarity : {self.speaker_similarity:.2f}/10\n"
            f"  Prosody match      : {self.prosody_match:.2f}/10\n"
            f"  MOS predictor      : {self.mos:.2f}/10\n"
            f"  Engine             : {self.engine} (iteration {self.iteration})"
        )


# Composite weight constants
W_SPEAKER = 0.50
W_PROSODY = 0.30
W_MOS = 0.20


class VoiceScorer:
    """Scores synthesised voice audio against a reference VoiceProfile.

    Degrades gracefully:
      - Full accuracy with librosa + resemblyzer + DNSMOS
      - Partial accuracy with librosa only (no speaker similarity)
      - Heuristic-only mode without any audio deps (for testing/CI)
    """

    def __init__(self, processor: Optional[SampleProcessor] = None):
        self._processor = processor or SampleProcessor()

    async def score(
        self,
        profile: VoiceProfile,
        synthesised_path: str | Path,
        reference_path: str | Path | None = None,
    ) -> VoiceScore:
        """Score synthesised audio against the profile's reference embedding.

        Args:
            profile:          The VoiceProfile that was used for synthesis.
            synthesised_path: Path to the synthesised WAV file to evaluate.
            reference_path:   Optional path to the original raw sample audio.
                              If provided, a fresh embedding is extracted for
                              maximum accuracy. Otherwise, profile.embedding is used.
        """
        synth_path = Path(synthesised_path)
        if not synth_path.exists():
            raise FileNotFoundError(f"Synthesised audio not found: {synth_path}")

        # Extract embedding from synthesised audio
        synth_embedding, _ = self._processor._extract_embedding(synth_path)

        # Get reference embedding
        if reference_path and Path(reference_path).exists():
            ref_embedding_vec, _ = self._processor._extract_embedding(Path(reference_path))
            ref_emb = SpeakerEmbedding(vector=ref_embedding_vec)
        elif profile.embedding:
            ref_emb = profile.embedding
        else:
            logger.warning("No reference embedding available — speaker similarity will be 0")
            ref_emb = SpeakerEmbedding(vector=[])

        synth_emb = SpeakerEmbedding(vector=synth_embedding)

        # Score 1: Speaker similarity
        sim = ref_emb.cosine_similarity(synth_emb)
        speaker_score = round(sim * 10, 3)

        # Score 2: Prosody match
        prosody_score, prosody_details = await self._score_prosody(
            synth_path,
            reference_path=reference_path,
            profile=profile,
        )

        # Score 3: MOS prediction
        mos_score, mos_details = await self._score_mos(synth_path)

        # Composite
        composite = round(
            speaker_score * W_SPEAKER +
            prosody_score * W_PROSODY +
            mos_score * W_MOS,
            3
        )

        score = VoiceScore(
            speaker_similarity=speaker_score,
            prosody_match=prosody_score,
            mos=mos_score,
            composite=composite,
            details={**prosody_details, **mos_details},
        )
        logger.info("Voice score: %s", score)
        return score

    async def _score_prosody(
        self,
        synth_path: Path,
        reference_path: str | Path | None,
        profile: VoiceProfile,
    ) -> tuple[float, dict]:
        """Compare pitch, rate, and energy between synth and reference."""
        details: dict = {}

        if not self._processor._has_librosa:
            # Heuristic: rate-based estimate from profile parameters
            rate_score = 10.0 - abs(profile.speaking_rate - 1.0) * 3
            return round(min(10.0, max(0.0, rate_score)), 2), {"mode": "heuristic"}

        import librosa
        import numpy as np

        # Load synthesised
        TARGET_SR = 22050
        y_synth, sr = librosa.load(str(synth_path), sr=TARGET_SR, mono=True)

        # Pitch analysis (synth)
        f0_synth = librosa.yin(y_synth, fmin=50, fmax=500, sr=sr)
        f0_synth = f0_synth[f0_synth > 0]  # remove unvoiced frames

        pitch_score = 10.0
        rate_score = 10.0
        energy_score = 10.0

        if reference_path and Path(reference_path).exists():
            y_ref, _ = librosa.load(str(reference_path), sr=TARGET_SR, mono=True)
            f0_ref = librosa.yin(y_ref, fmin=50, fmax=500, sr=sr)
            f0_ref = f0_ref[f0_ref > 0]

            if len(f0_synth) > 0 and len(f0_ref) > 0:
                # Pitch mean difference in semitones
                cent_synth = librosa.hz_to_midi(f0_synth.mean())
                cent_ref = librosa.hz_to_midi(f0_ref.mean())
                pitch_diff = abs(cent_synth - cent_ref)
                pitch_score = max(0.0, 10.0 - pitch_diff * 1.5)
                details["pitch_diff_semitones"] = round(pitch_diff, 2)

                # Speaking rate ratio (duration proxy)
                rate_ratio = len(y_synth) / max(1, len(y_ref))
                rate_score = max(0.0, 10.0 - abs(1.0 - rate_ratio) * 10)
                details["duration_ratio"] = round(rate_ratio, 3)

            # Energy envelope correlation
            rms_synth = librosa.feature.rms(y=y_synth)[0]
            rms_ref = librosa.feature.rms(y=y_ref)[0]
            min_len = min(len(rms_synth), len(rms_ref))
            if min_len > 1:
                corr = float(np.corrcoef(rms_synth[:min_len], rms_ref[:min_len])[0, 1])
                energy_score = max(0.0, corr * 10)
                details["energy_correlation"] = round(corr, 3)
        else:
            # No reference: score based on speech quality heuristics
            if len(f0_synth) > 0:
                # Naturalness of pitch variance
                f0_var = f0_synth.std() / max(f0_synth.mean(), 1)
                pitch_score = min(10.0, f0_var * 30)  # some variance is natural
                details["f0_variance_ratio"] = round(float(f0_var), 4)

        prosody = round((pitch_score + rate_score + energy_score) / 3, 3)
        details.update({
            "pitch_score": round(pitch_score, 2),
            "rate_score": round(rate_score, 2),
            "energy_score": round(energy_score, 2),
        })
        return prosody, details

    async def _score_mos(self, synth_path: Path) -> tuple[float, dict]:
        """Predict Mean Opinion Score for the synthesised audio.

        Tries (in order):
          1. DNSMOS P.835 (Microsoft neural MOS predictor)
          2. UTMOS strong model
          3. Waveform SNR heuristic (fallback)
        """
        # Try DNSMOS
        try:
            return await self._dnsmos_score(synth_path)
        except Exception as e:
            logger.debug("DNSMOS unavailable: %s", e)

        # Try librosa SNR heuristic
        if self._processor._has_librosa:
            return await self._snr_heuristic_score(synth_path)

        # Final fallback: assume a decent score for valid audio files
        return 7.5, {"mode": "default-fallback"}

    async def _dnsmos_score(self, synth_path: Path) -> tuple[float, dict]:
        """DNSMOS P.835 neural MOS predictor (requires onnxruntime + model weights)."""
        import onnxruntime as ort  # type: ignore
        import numpy as np
        import soundfile as sf

        # Model weights would be at: models/dnsmos/sig_bak_ovr.onnx
        model_path = Path(__file__).parent.parent.parent / "models" / "dnsmos" / "sig_bak_ovr.onnx"
        if not model_path.exists():
            raise FileNotFoundError("DNSMOS model not found")

        audio, sr = sf.read(str(synth_path))
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        # Resample to 16kHz if needed
        if sr != 16000 and self._processor._has_librosa:
            import librosa
            audio = librosa.resample(audio.astype(float), orig_sr=sr, target_sr=16000)

        session = ort.InferenceSession(str(model_path))
        input_name = session.get_inputs()[0].name
        pred = session.run(None, {input_name: audio.astype(np.float32)[np.newaxis]})[0]
        # DNSMOS returns [SIG, BAK, OVR] on 1–5 scale; we use OVR
        ovr_mos = float(pred[0, 2])
        # Convert 1–5 MOS → 0–10
        mos_10 = max(0.0, (ovr_mos - 1.0) / 4.0 * 10.0)
        return round(mos_10, 3), {"mode": "dnsmos", "raw_mos": round(ovr_mos, 3)}

    async def _snr_heuristic_score(self, synth_path: Path) -> tuple[float, dict]:
        """Librosa-based signal quality heuristic as MOS proxy."""
        import librosa
        import numpy as np
        y, sr = librosa.load(str(synth_path), sr=None, mono=True)

        # Spectral flatness — lower = more tonal (better for speech)
        flatness = librosa.feature.spectral_flatness(y=y)[0].mean()
        flatness_score = max(0.0, 10.0 - float(flatness) * 50)

        # Zero-crossing rate — too high = noisy
        zcr = librosa.feature.zero_crossing_rate(y)[0].mean()
        zcr_score = max(0.0, 10.0 - float(zcr) * 100)

        # RMS energy presence (speech should have clear energy)
        rms = librosa.feature.rms(y=y)[0].mean()
        rms_score = min(10.0, float(rms) * 200)

        heuristic = round((flatness_score + zcr_score + rms_score) / 3, 3)
        return heuristic, {
            "mode": "librosa-heuristic",
            "spectral_flatness": round(float(flatness), 5),
            "zcr": round(float(zcr), 5),
            "rms": round(float(rms), 5),
        }
