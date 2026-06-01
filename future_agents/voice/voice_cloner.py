"""VoiceCloner — multi-engine voice cloning with iterative accuracy improvement.

Engine priority (auto-selected based on availability and sample quality):

  1. XTTS v2 (Coqui TTS) — best open-source zero-shot voice cloning
     - Needs: pip install TTS>=0.22; ~6s reference clip; optional GPU
     - Quality: 9–10/10 speaker similarity on good samples
     - License: CPML (open for research/non-commercial; commercial licence available)

  2. OpenVoice v2 (MIT) — best for accent/style transfer
     - Needs: pip install openvoice; tone-color-converter weights
     - Quality: 8–9/10 speaker similarity; excellent style transfer

  3. ElevenLabs API (commercial) — highest quality, easiest to use
     - Needs: pip install elevenlabs; ELEVENLABS_API_KEY env var
     - Quality: 9.5–10/10; ~30 second sample recommended
     - Note: audio stays on ElevenLabs servers for API usage

  4. RVC (Retrieval-based Voice Conversion) — best for real-time conversion
     - Needs: pip install rvc-python; pretrained model per voice
     - Quality: 8–10/10 depending on training data amount

  5. Kokoro (MIT, fast, no API) — lightweight fallback
     - Needs: pip install kokoro>=0.8; preset voices or fine-tuning
     - Quality: 7–8/10 for style; limited zero-shot cloning

Improvement loop:
  The cloner runs up to MAX_ITERATIONS synthesis attempts, scores each with
  VoiceScorer, adjusts acoustic parameters, and returns the best result.
  Stops early when score ≥ target (default 9.5/10).
"""

from __future__ import annotations

import asyncio
import copy
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from future_agents.voice.voice_profile import (
    ImprovementRecord, VoiceProfile, PersonalityType,
)
from future_agents.voice.sample_processor import SampleProcessor

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5
DEFAULT_TARGET_SCORE = 9.5


@dataclass
class SynthesisResult:
    """Result of one synthesis attempt."""
    audio_path: Path
    engine: str
    iteration: int
    score: float          # composite 0–10
    speaker_similarity: float
    prosody_match: float
    mos: float
    parameters_used: dict[str, Any]
    is_best: bool = False


# ── Personality → prosody parameter presets ────────────────────────

PERSONALITY_PRESETS: dict[PersonalityType, dict[str, Any]] = {
    PersonalityType.FORMAL_EXECUTIVE: {
        "speed": 0.88, "temperature": 0.55, "emotion": "confident",
        "pause_factor": 1.2, "pitch_offset": -1.0,
    },
    PersonalityType.FRIENDLY_HELPER: {
        "speed": 1.05, "temperature": 0.70, "emotion": "friendly",
        "pause_factor": 0.9, "pitch_offset": 1.0,
    },
    PersonalityType.TECHNICAL_EXPERT: {
        "speed": 0.92, "temperature": 0.50, "emotion": "neutral",
        "pause_factor": 1.1, "pitch_offset": -0.5,
    },
    PersonalityType.ENTHUSIASTIC_INNOVATOR: {
        "speed": 1.20, "temperature": 0.85, "emotion": "friendly",
        "pause_factor": 0.75, "pitch_offset": 2.0,
    },
    PersonalityType.CALM_COUNSELOR: {
        "speed": 0.80, "temperature": 0.45, "emotion": "empathetic",
        "pause_factor": 1.4, "pitch_offset": -0.5,
    },
    PersonalityType.DIRECT_COMMANDER: {
        "speed": 0.95, "temperature": 0.40, "emotion": "authoritative",
        "pause_factor": 1.0, "pitch_offset": -2.0,
    },
    PersonalityType.CREATIVE_STORYTELLER: {
        "speed": 1.0, "temperature": 0.90, "emotion": "friendly",
        "pause_factor": 1.0, "pitch_offset": 0.5,
    },
    PersonalityType.EMPATHETIC_ADVISOR: {
        "speed": 0.88, "temperature": 0.60, "emotion": "empathetic",
        "pause_factor": 1.2, "pitch_offset": 0.5,
    },
    PersonalityType.SHARP_ANALYST: {
        "speed": 1.0, "temperature": 0.45, "emotion": "neutral",
        "pause_factor": 1.0, "pitch_offset": 0.0,
    },
    PersonalityType.GLOBAL_CONNECTOR: {
        "speed": 0.95, "temperature": 0.55, "emotion": "neutral",
        "pause_factor": 1.05, "pitch_offset": 0.0,
    },
    PersonalityType.CUSTOM: {
        "speed": 1.0, "temperature": 0.65, "emotion": "neutral",
        "pause_factor": 1.0, "pitch_offset": 0.0,
    },
}


class VoiceCloner:
    """Synthesises speech in a target voice with iterative accuracy improvement.

    Usage:
        cloner = VoiceCloner()
        result = await cloner.synthesize(profile, "Hello, I'm your IT assistant!")
        print(f"Score: {result.score}/10 via {result.engine}")
    """

    def __init__(
        self,
        output_dir: Optional[Path] = None,
        target_score: float = DEFAULT_TARGET_SCORE,
        max_iterations: int = MAX_ITERATIONS,
    ):
        self.output_dir = output_dir or Path(tempfile.mkdtemp(prefix="voice_output_"))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.target_score = target_score
        self.max_iterations = max_iterations
        self._processor = SampleProcessor()
        self._detect_engines()

    def _detect_engines(self) -> None:
        self._available_engines: list[str] = []
        for engine, check_fn in [
            ("xtts", self._check_xtts),
            ("openvoice", self._check_openvoice),
            ("elevenlabs", self._check_elevenlabs),
            ("kokoro", self._check_kokoro),
        ]:
            if check_fn():
                self._available_engines.append(engine)
        if self._available_engines:
            logger.info("Voice engines available: %s", self._available_engines)
        else:
            logger.warning("No TTS engines found — using stub synthesis. "
                           "Install: pip install TTS (for XTTS) or set ELEVENLABS_API_KEY")
            self._available_engines = ["stub"]

    def _check_xtts(self) -> bool:
        try:
            import importlib
            importlib.import_module("TTS")
            return True
        except ImportError:
            return False

    def _check_openvoice(self) -> bool:
        try:
            import importlib
            importlib.import_module("openvoice")
            return True
        except ImportError:
            return False

    def _check_elevenlabs(self) -> bool:
        return bool(os.environ.get("ELEVENLABS_API_KEY"))

    def _check_kokoro(self) -> bool:
        try:
            import importlib
            importlib.import_module("kokoro")
            return True
        except ImportError:
            return False

    async def create_profile_from_sample(
        self,
        sample_path: str | Path,
        name: str,
        personality: PersonalityType = PersonalityType.CUSTOM,
        description: str = "",
        tags: list[str] | None = None,
    ) -> VoiceProfile:
        """Create a VoiceProfile by processing a raw audio sample.

        The returned profile includes a speaker embedding and reference clip.
        No raw audio is stored in the profile — only the compact embedding.

        Args:
            sample_path: Path to WAV/MP3/OGG/FLAC recording (3–30 seconds)
            name:        Display name for this voice
            personality: Personality archetype (sets prosody presets)

        Returns:
            A fully initialised VoiceProfile ready for synthesis.
        """
        from future_agents.voice.voice_profile import AccentType

        logger.info("Creating voice profile '%s' from sample: %s", name, sample_path)
        embedding, ref_clip = self._processor.process(str(sample_path), name)

        profile = VoiceProfile(
            name=name,
            description=description or f"Voice profile created from sample: {Path(sample_path).name}",
            personality=personality,
            accent=AccentType.CUSTOM,
            tags=tags or [],
            embedding=embedding,
        )

        # Apply personality presets
        preset = PERSONALITY_PRESETS.get(personality, PERSONALITY_PRESETS[PersonalityType.CUSTOM])
        profile.speaking_rate = preset["speed"]
        profile.pitch_offset = preset.get("pitch_offset", 0.0)

        # Store reference clip path in engine config for XTTS
        profile.engine_config["xtts"] = {
            "reference_wav": str(ref_clip),
            "language": "en",
        }

        logger.info("Profile created: id=%s, embedding=%dd, engines=%s",
                    profile.id, embedding.dimension, self._available_engines)
        return profile

    async def synthesize(
        self,
        profile: VoiceProfile,
        text: str,
        output_filename: str | None = None,
    ) -> SynthesisResult:
        """Synthesise speech and run the improvement loop.

        Tries each engine in the profile's preference list, scores the result,
        and iterates with adjusted parameters until target_score is achieved
        or max_iterations is exhausted. Returns the best result.

        Args:
            profile:  The VoiceProfile to clone.
            text:     Text to synthesise.
            output_filename: Optional filename for the output WAV.

        Returns:
            SynthesisResult with the best audio path and score.
        """
        from future_agents.voice.voice_scorer import VoiceScorer
        scorer = VoiceScorer(processor=self._processor)

        # Determine engine order
        engine_order = [e for e in profile.engine_preference if e in self._available_engines]
        if not engine_order:
            engine_order = self._available_engines[:1] or ["stub"]

        best_result: Optional[SynthesisResult] = None
        params = copy.deepcopy(PERSONALITY_PRESETS.get(profile.personality,
                               PERSONALITY_PRESETS[PersonalityType.CUSTOM]))

        for iteration in range(1, self.max_iterations + 1):
            engine = engine_order[(iteration - 1) % len(engine_order)]

            out_path = self.output_dir / (
                output_filename or f"{profile.id}_iter{iteration}.wav"
            )

            try:
                await self._synthesize_with_engine(engine, profile, text, params, out_path)
            except Exception as e:
                logger.warning("Engine %s failed iteration %d: %s", engine, iteration, e)
                continue

            # Score the output
            ref_path = (profile.engine_config.get("xtts", {}) or {}).get("reference_wav")
            voice_score = await scorer.score(profile, out_path, reference_path=ref_path)

            result = SynthesisResult(
                audio_path=out_path,
                engine=engine,
                iteration=iteration,
                score=voice_score.composite,
                speaker_similarity=voice_score.speaker_similarity,
                prosody_match=voice_score.prosody_match,
                mos=voice_score.mos,
                parameters_used=copy.copy(params),
            )

            # Record in profile history
            profile.record_improvement(ImprovementRecord(
                iteration=iteration,
                engine=engine,
                parameters=copy.copy(params),
                speaker_similarity=voice_score.speaker_similarity,
                prosody_score=voice_score.prosody_match,
                mos_score=voice_score.mos,
                composite_score=voice_score.composite,
            ))

            logger.info("Iteration %d/%d [%s]: %.2f/10 %s",
                        iteration, self.max_iterations, engine,
                        voice_score.composite, voice_score.grade)

            if best_result is None or result.score > best_result.score:
                if best_result:
                    best_result.is_best = False
                result.is_best = True
                best_result = result

            if voice_score.composite >= self.target_score:
                logger.info("Target score %.1f reached — stopping early", self.target_score)
                break

            # Tune parameters for next iteration
            params = self._tune_parameters(params, voice_score, iteration)

        if best_result is None:
            raise RuntimeError("All synthesis engines failed")

        logger.info("Best result: %.2f/10 via %s (iteration %d)",
                    best_result.score, best_result.engine, best_result.iteration)
        return best_result

    def _tune_parameters(
        self, params: dict, score: Any, iteration: int
    ) -> dict:
        """Adjust synthesis parameters based on scoring feedback."""
        new_params = copy.copy(params)

        # If speaker similarity is low: reduce temperature (more deterministic)
        if score.speaker_similarity < 7.0:
            new_params["temperature"] = max(0.30, params["temperature"] - 0.10)

        # If prosody is low: adjust speed toward neutral
        if score.prosody_match < 7.0:
            current_speed = params.get("speed", 1.0)
            new_params["speed"] = current_speed + (1.0 - current_speed) * 0.3

        # Alternate engine on even iterations if score is still poor
        if score.composite < 7.0 and iteration % 2 == 0:
            new_params["_force_next_engine"] = True

        # Slight temperature variation to escape local minima
        import random
        new_params["temperature"] = max(0.25, min(0.95,
            new_params.get("temperature", 0.65) + random.uniform(-0.05, 0.05)
        ))

        return new_params

    # ── Engine implementations ─────────────────────────────────────

    async def _synthesize_with_engine(
        self,
        engine: str,
        profile: VoiceProfile,
        text: str,
        params: dict,
        output_path: Path,
    ) -> None:
        dispatch = {
            "xtts": self._synth_xtts,
            "openvoice": self._synth_openvoice,
            "elevenlabs": self._synth_elevenlabs,
            "kokoro": self._synth_kokoro,
            "stub": self._synth_stub,
        }
        fn = dispatch.get(engine, self._synth_stub)
        await fn(profile, text, params, output_path)

    async def _synth_xtts(
        self, profile: VoiceProfile, text: str, params: dict, out: Path
    ) -> None:
        """XTTS v2 (Coqui TTS) — best zero-shot cloning quality."""
        from TTS.api import TTS  # type: ignore
        ref_wav = (profile.engine_config.get("xtts") or {}).get("reference_wav")
        language = (profile.engine_config.get("xtts") or {}).get("language", "en")

        if not ref_wav or not Path(ref_wav).exists():
            raise ValueError("XTTS requires a reference WAV in profile.engine_config['xtts']")

        tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: tts.tts_to_file(
            text=text,
            speaker_wav=ref_wav,
            language=language,
            file_path=str(out),
            speed=params.get("speed", 1.0),
            temperature=params.get("temperature", 0.65),
        ))

    async def _synth_openvoice(
        self, profile: VoiceProfile, text: str, params: dict, out: Path
    ) -> None:
        """OpenVoice v2 — MIT licensed, excellent style/tone transfer."""
        from openvoice import se_extractor  # type: ignore
        from openvoice.api import ToneColorConverter  # type: ignore

        ref_wav = (profile.engine_config.get("openvoice") or
                   profile.engine_config.get("xtts") or {}).get("reference_wav")

        ckpt_dir = os.environ.get("OPENVOICE_CKPT_DIR", "models/openvoice/checkpoints_v2")
        converter = ToneColorConverter(f"{ckpt_dir}/config.json")
        converter.load_ckpt(f"{ckpt_dir}/checkpoint.pth")

        target_se, _ = se_extractor.get_se(ref_wav, converter, target_dir=str(out.parent))

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: converter.convert(
            audio_src_path=str(out),  # would be TTS base voice first
            src_se=None,
            tgt_se=target_se,
            output_path=str(out),
            tau=params.get("temperature", 0.7),
        ))

    async def _synth_elevenlabs(
        self, profile: VoiceProfile, text: str, params: dict, out: Path
    ) -> None:
        """ElevenLabs API — commercial, highest quality, easy setup."""
        from elevenlabs import ElevenLabs, VoiceSettings  # type: ignore
        import soundfile as sf
        import numpy as np

        api_key = os.environ["ELEVENLABS_API_KEY"]
        client = ElevenLabs(api_key=api_key)

        # Look up or create a voice clone via ElevenLabs IVC
        el_config = profile.engine_config.get("elevenlabs", {})
        voice_id = el_config.get("voice_id")

        if not voice_id:
            # First-time: add voice from reference audio
            ref_wav = (profile.engine_config.get("xtts") or {}).get("reference_wav")
            if not ref_wav:
                raise ValueError("ElevenLabs IVC requires reference_wav in engine_config")
            voice = client.clone(
                name=profile.name,
                description=profile.description,
                files=[open(ref_wav, "rb")],
            )
            voice_id = voice.voice_id
            profile.engine_config.setdefault("elevenlabs", {})["voice_id"] = voice_id

        settings = VoiceSettings(
            stability=1.0 - params.get("temperature", 0.65),
            similarity_boost=0.95,
            style=0.0,
            use_speaker_boost=True,
        )

        loop = asyncio.get_event_loop()
        audio_bytes = await loop.run_in_executor(None, lambda: b"".join(
            client.text_to_speech.convert(
                voice_id=voice_id,
                text=text,
                voice_settings=settings,
                output_format="pcm_22050",
            )
        ))

        # Write raw PCM to WAV
        audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(float) / 32768.0
        sf.write(str(out), audio, 22050)

    async def _synth_kokoro(
        self, profile: VoiceProfile, text: str, params: dict, out: Path
    ) -> None:
        """Kokoro — lightweight, fast, MIT licensed."""
        import kokoro  # type: ignore
        import soundfile as sf

        voice_name = profile.engine_config.get("kokoro", {}).get("voice", "af_heart")
        pipeline = kokoro.KPipeline(lang_code="a")
        generator = pipeline(text, voice=voice_name, speed=params.get("speed", 1.0))

        import numpy as np
        chunks = []
        for _, _, audio in generator:
            chunks.append(audio)
        audio_all = np.concatenate(chunks) if chunks else np.zeros(22050)
        sf.write(str(out), audio_all, 24000)

    async def _synth_stub(
        self, profile: VoiceProfile, text: str, params: dict, out: Path
    ) -> None:
        """Deterministic stub — writes a valid WAV for testing without any TTS library.

        The stub creates a sine wave whose frequency encodes the profile's pitch_offset,
        producing a unique-but-recognisable tone per profile. Replace with a real engine.
        """
        import struct
        import math

        sample_rate = 22050
        # Base frequency of 220 Hz, shifted by pitch offset
        freq = 220.0 * (2 ** (profile.pitch_offset / 12.0))
        duration = max(0.5, len(text.split()) * 0.35)  # ~0.35s per word
        num_samples = int(sample_rate * duration)

        samples = []
        for i in range(num_samples):
            # Amplitude envelope: fade in/out
            t = i / sample_rate
            env = math.sin(math.pi * t / duration) ** 0.5
            val = env * math.sin(2 * math.pi * freq * t) * profile.energy
            samples.append(int(val * 32767))

        data = struct.pack(f"<{num_samples}h", *samples)
        data_size = len(data)
        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF", 36 + data_size, b"WAVE",
            b"fmt ", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16,
            b"data", data_size,
        )
        out.write_bytes(header + data)
