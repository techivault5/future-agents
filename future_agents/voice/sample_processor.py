"""SampleProcessor — audio sample ingestion and speaker embedding extraction.

Pipeline:
  1. Validate the audio file (format, duration, quality checks)
  2. Convert to 22050 Hz mono WAV (required by XTTS / resemblyzer)
  3. Apply noise reduction (noisereduce)
  4. Trim silence from ends (librosa / pydub)
  5. Extract speaker embedding (resemblyzer or speechbrain ECAPA-TDNN)
  6. Return a SpeakerEmbedding + cleaned reference clip path

The 6-second reference clip is kept alongside the embedding so XTTS can
use it directly during synthesis (zero-shot voice cloning).

Dependencies (install via pip):
  librosa>=0.10, soundfile>=0.12, pydub>=0.25, resemblyzer>=0.1
  noisereduce>=3.0 (optional, improves accuracy)
  speechbrain>=1.0 (optional, higher-quality ECAPA-TDNN embeddings)
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import struct
import tempfile
from pathlib import Path
from typing import Optional

from future_agents.voice.voice_profile import SpeakerEmbedding

logger = logging.getLogger(__name__)

MIN_DURATION_S = 3.0  # minimum sample length for cloning
TARGET_DURATION_S = 6.0  # ideal XTTS reference length
MAX_DURATION_S = 30.0  # trim anything longer than this
TARGET_SR = 22050  # sample rate required by XTTS


class AudioValidationError(ValueError):
    """Raised when the uploaded audio sample cannot be used."""


class SampleProcessor:
    """Processes raw audio samples into speaker embeddings.

    Gracefully degrades:
      - With librosa + resemblyzer → full pipeline, highest quality
      - With soundfile only        → basic processing, numpy embedding
      - Without any audio libs     → stub embedding (for testing/CI)
    """

    def __init__(self, work_dir: Optional[Path] = None):
        self.work_dir = work_dir or Path(tempfile.mkdtemp(prefix="voice_samples_"))
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._check_available_backends()

    def _check_available_backends(self) -> None:
        self._has_librosa = self._try_import("librosa")
        self._has_sf = self._try_import("soundfile")
        self._has_resemblyzer = self._try_import("resemblyzer")
        self._has_speechbrain = self._try_import("speechbrain")
        self._has_noisereduce = self._try_import("noisereduce")
        self._has_pydub = self._try_import("pydub")

        if self._has_resemblyzer:
            logger.info("SampleProcessor: using resemblyzer for speaker embeddings (256-d)")
        elif self._has_speechbrain:
            logger.info("SampleProcessor: using speechbrain ECAPA-TDNN for embeddings (192-d)")
        else:
            logger.warning(
                "SampleProcessor: no embedding backend available — install resemblyzer "
                "or speechbrain for real embeddings. Using stub embeddings."
            )

    @staticmethod
    def _try_import(module: str) -> bool:
        try:
            __import__(module)
            return True
        except ImportError:
            return False

    def process(
        self,
        audio_path: str | Path,
        output_name: str | None = None,
    ) -> tuple[SpeakerEmbedding, Path]:
        """Full processing pipeline.

        Returns:
            (SpeakerEmbedding, reference_clip_path)
            The reference clip is a cleaned 6-second WAV at 22050 Hz mono.
        """
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        name = output_name or audio_path.stem
        out_dir = self.work_dir / name
        out_dir.mkdir(exist_ok=True)

        # Step 1: Validate
        duration = self._get_duration(audio_path)
        if duration < MIN_DURATION_S:
            raise AudioValidationError(
                f"Sample too short ({duration:.1f}s). Minimum is {MIN_DURATION_S}s. "
                f"For best results, record {TARGET_DURATION_S}+ seconds."
            )
        if duration > MAX_DURATION_S:
            logger.info("Sample is %.1fs — trimming to %.1fs for embedding", duration, MAX_DURATION_S)

        # Step 2: Convert + clean
        ref_clip = out_dir / "reference.wav"
        self._convert_and_clean(audio_path, ref_clip, duration)

        # Step 3: SHA-256 of original
        sample_hash = self._sha256(audio_path)

        # Step 4: Extract embedding
        embedding_vector, model_name = self._extract_embedding(ref_clip)

        # Step 5: Get final duration
        final_duration = self._get_duration(ref_clip)

        embedding = SpeakerEmbedding(
            vector=embedding_vector,
            model=model_name,
            sample_hash=sample_hash,
            sample_duration_s=final_duration,
        )

        logger.info(
            "Processed sample '%s': %dd embedding, %.1fs reference clip, hash=%s",
            name,
            embedding.dimension,
            final_duration,
            sample_hash[:8],
        )
        return embedding, ref_clip

    def _get_duration(self, path: Path) -> float:
        """Get audio duration in seconds — tries multiple backends."""
        if self._has_librosa:
            import librosa

            return float(librosa.get_duration(path=str(path)))
        if self._has_sf:
            import soundfile as sf

            info = sf.info(str(path))
            return info.duration
        # Fallback: read WAV header directly
        return self._wav_duration_from_header(path)

    @staticmethod
    def _wav_duration_from_header(path: Path) -> float:
        """Minimal WAV header parser — no external deps required."""
        try:
            data = path.read_bytes()
            if len(data) < 44:
                return 0.0
            # Standard PCM WAV: bytes 24-27 = sample rate, 34-35 = bit depth, 22-23 = channels
            sr = struct.unpack_from("<I", data, 24)[0]
            bits = struct.unpack_from("<H", data, 34)[0]
            ch = struct.unpack_from("<H", data, 22)[0]
            # Find data chunk
            data_size = len(data) - 44
            if sr > 0 and bits > 0 and ch > 0:
                return data_size / (sr * ch * (bits // 8))
        except Exception:
            pass
        return 6.0  # safe default

    def _convert_and_clean(self, src: Path, dst: Path, src_duration: float) -> None:
        """Convert to 22050 Hz mono, trim silence, apply noise reduction."""
        target_dur = min(TARGET_DURATION_S, src_duration)

        if self._has_librosa and self._has_sf:
            import librosa
            import soundfile as sf

            y, sr = librosa.load(str(src), sr=TARGET_SR, mono=True, duration=MAX_DURATION_S)

            # Trim silence
            y, _ = librosa.effects.trim(y, top_db=20)

            # Noise reduction (optional)
            if self._has_noisereduce:
                import noisereduce as nr

                y = nr.reduce_noise(y=y, sr=sr)

            # Take best TARGET_DURATION_S centred slice
            if len(y) > TARGET_SR * TARGET_DURATION_S:
                mid = len(y) // 2
                half = int(TARGET_SR * TARGET_DURATION_S // 2)
                y = y[mid - half : mid + half]

            sf.write(str(dst), y, TARGET_SR, subtype="PCM_16")

        elif self._has_pydub:
            from pydub import AudioSegment

            audio = AudioSegment.from_file(str(src))
            audio = audio.set_frame_rate(TARGET_SR).set_channels(1)
            # Trim to target duration
            ms = int(target_dur * 1000)
            audio = audio[:ms]
            audio.export(str(dst), format="wav")

        else:
            # No audio libs — just copy the file as-is
            shutil.copy2(src, dst)

    def _extract_embedding(self, ref_clip: Path) -> tuple[list[float], str]:
        """Extract speaker embedding from reference clip."""
        if self._has_resemblyzer:
            return self._embed_resemblyzer(ref_clip)
        if self._has_speechbrain:
            return self._embed_speechbrain(ref_clip)
        return self._embed_stub(ref_clip)

    def _embed_resemblyzer(self, ref_clip: Path) -> tuple[list[float], str]:
        """256-d GE2E embedding (Wan et al. 2018)."""
        from resemblyzer import VoiceEncoder, preprocess_wav

        encoder = VoiceEncoder()
        wav = preprocess_wav(ref_clip)
        embedding = encoder.embed_utterance(wav)
        return embedding.tolist(), "resemblyzer-ge2e"

    def _embed_speechbrain(self, ref_clip: Path) -> tuple[list[float], str]:
        """192-d ECAPA-TDNN embedding — highest quality speaker representation."""
        from speechbrain.pretrained import EncoderClassifier

        classifier = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            run_opts={"device": "cpu"},
        )
        signal, _ = classifier.load_audio(str(ref_clip))
        embedding = classifier.encode_batch(signal.unsqueeze(0))
        return embedding.squeeze().tolist(), "speechbrain-ecapa-tdnn"

    def _embed_stub(self, ref_clip: Path) -> tuple[list[float], str]:
        """Deterministic stub embedding derived from audio hash (no deps required).

        This produces a consistent 256-d vector for a given audio file —
        useful for testing and CI. Replace with a real encoder for production.
        """
        import hashlib

        raw = ref_clip.read_bytes()
        dim = 256
        vector = []
        for i in range(dim):
            h = hashlib.sha256(raw + i.to_bytes(4, "big")).digest()
            # Map first 4 bytes to float in [-1, 1]
            val = (int.from_bytes(h[:4], "big") / 2**32) * 2 - 1
            vector.append(round(val, 6))
        # L2-normalise
        magnitude = sum(v**2 for v in vector) ** 0.5
        if magnitude > 0:
            vector = [v / magnitude for v in vector]
        return vector, "stub-sha256"

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
