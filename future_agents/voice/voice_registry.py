"""VoiceRegistry — store, search, and share voice profiles.

Storage layout:
    ~/.future-agents/voices/
        <profile-id>/
            profile.yaml      ← human-readable profile (no raw embedding vector)
            profile.json      ← machine-readable, includes full embedding
            reference.wav     ← 6-second cleaned reference clip (optional)
        voice_index.json      ← searchable index of all registered profiles

Sharing: export to a portable .voicepack file (ZIP):
    .voicepack/
        profile.json          ← full profile including embedding vector
        reference.wav         ← cleaned reference clip (optional)
        manifest.json         ← version, checksum, metadata
    → Import on any machine with: registry.import_voicepack("my_voice.voicepack")
"""

from __future__ import annotations

import json
import logging
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from future_agents.voice.voice_profile import VoiceProfile

logger = logging.getLogger(__name__)

DEFAULT_REGISTRY_DIR = Path.home() / ".future-agents" / "voices"


class VoiceRegistry:
    """Manages the lifecycle of VoiceProfiles: save, load, search, share.

    Usage:
        registry = VoiceRegistry()
        registry.save(profile)

        # Search
        profiles = registry.search("friendly")

        # Share
        pack_path = registry.export_voicepack(profile.id)
        # → /path/to/my-voice.voicepack

        # Import on another machine
        registry2 = VoiceRegistry()
        profile2 = registry2.import_voicepack("my-voice.voicepack")
    """

    def __init__(self, registry_dir: Optional[Path] = None):
        self.registry_dir = registry_dir or DEFAULT_REGISTRY_DIR
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.registry_dir / "voice_index.json"
        self._index: dict[str, dict] = self._load_index()

    # ── CRUD ───────────────────────────────────────────────────────

    def save(self, profile: VoiceProfile, reference_wav: Optional[Path] = None) -> None:
        """Persist a VoiceProfile to the registry.

        Args:
            profile:       The profile to save.
            reference_wav: Optional path to the cleaned reference WAV.
                           If provided, it is copied into the profile directory.
        """
        profile_dir = self.registry_dir / profile.id
        profile_dir.mkdir(exist_ok=True)

        # Save machine-readable JSON (includes full embedding vector)
        json_path = profile_dir / "profile.json"
        json_path.write_text(profile.model_dump_json(indent=2))

        # Save human-readable YAML (embedding vector replaced with summary)
        yaml_path = profile_dir / "profile.yaml"
        yaml_path.write_text(profile.to_yaml())

        # Copy reference WAV if provided
        if reference_wav and Path(reference_wav).exists():
            dest = profile_dir / "reference.wav"
            shutil.copy2(reference_wav, dest)
            logger.debug("Reference WAV saved to %s", dest)

        # Update index
        self._index[profile.id] = self._profile_to_index_entry(profile)
        self._save_index()

        logger.info("VoiceProfile '%s' (%s) saved to registry", profile.name, profile.id)

    def load(self, profile_id: str) -> VoiceProfile:
        """Load a VoiceProfile by ID."""
        json_path = self.registry_dir / profile_id / "profile.json"
        if not json_path.exists():
            raise KeyError(f"No voice profile found with id: {profile_id}")
        return VoiceProfile.model_validate_json(json_path.read_text())

    def delete(self, profile_id: str) -> None:
        """Remove a profile from the registry (irreversible)."""
        profile_dir = self.registry_dir / profile_id
        if profile_dir.exists():
            shutil.rmtree(profile_dir)
        self._index.pop(profile_id, None)
        self._save_index()
        logger.info("Voice profile %s deleted", profile_id)

    def list_all(self) -> list[dict]:
        """Return index entries for all registered profiles."""
        return list(self._index.values())

    # ── Search ─────────────────────────────────────────────────────

    def search(
        self,
        query: str = "",
        personality: str | None = None,
        accent: str | None = None,
        min_score: float = 0.0,
        tags: list[str] | None = None,
    ) -> list[dict]:
        """Search the registry index.

        Args:
            query:       Free-text search against name, description, tags.
            personality: Filter by personality type string.
            accent:      Filter by accent type string.
            min_score:   Minimum best_score threshold.
            tags:        All provided tags must be present.

        Returns:
            List of index entries (dicts) sorted by best_score descending.
        """
        results = list(self._index.values())

        if query:
            q = query.lower()
            results = [
                r for r in results
                if q in r.get("name", "").lower()
                or q in r.get("description", "").lower()
                or any(q in t.lower() for t in r.get("tags", []))
            ]

        if personality:
            results = [r for r in results if r.get("personality") == personality]

        if accent:
            results = [r for r in results if r.get("accent") == accent]

        if min_score > 0.0:
            results = [r for r in results if r.get("best_score", 0.0) >= min_score]

        if tags:
            results = [
                r for r in results
                if all(t in r.get("tags", []) for t in tags)
            ]

        return sorted(results, key=lambda r: r.get("best_score", 0.0), reverse=True)

    def get_reference_wav(self, profile_id: str) -> Optional[Path]:
        """Return the path to the reference WAV clip if it exists."""
        wav = self.registry_dir / profile_id / "reference.wav"
        return wav if wav.exists() else None

    # ── Sharing / Export / Import ─────────────────────────────────

    def export_voicepack(
        self,
        profile_id: str,
        output_dir: Optional[Path] = None,
        include_reference_wav: bool = True,
    ) -> Path:
        """Export a profile to a portable .voicepack file.

        The .voicepack contains:
          - profile.json     (full profile including embedding)
          - reference.wav    (optional, 6-second reference clip)
          - manifest.json    (metadata, version, checksum)

        Raw audio is NOT included — only the embedding vector extracted
        from it. This protects user privacy while enabling voice cloning
        on the receiving end.

        Returns:
            Path to the generated .voicepack file.
        """
        import hashlib

        profile = self.load(profile_id)
        out_dir = output_dir or Path.cwd()
        safe_name = profile.name.replace(" ", "_").replace("/", "-").lower()
        pack_path = out_dir / f"{safe_name}-{profile.id[:8]}.voicepack"

        profile_json = profile.model_dump_json(indent=2)
        checksum = hashlib.sha256(profile_json.encode()).hexdigest()

        manifest = {
            "voicepack_version": "1.0",
            "profile_id": profile.id,
            "profile_name": profile.name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "best_score": profile.best_score,
            "engine_preference": profile.engine_preference,
            "has_reference_wav": False,
            "profile_checksum": checksum,
        }

        with zipfile.ZipFile(pack_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("profile.json", profile_json)
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))

            ref_wav = self.get_reference_wav(profile_id)
            if include_reference_wav and ref_wav and ref_wav.exists():
                zf.write(ref_wav, "reference.wav")
                manifest["has_reference_wav"] = True
                # Update manifest with reference info
                zf.writestr("manifest.json", json.dumps(manifest, indent=2))

        logger.info("VoicePack exported: %s (%.1f KB)", pack_path,
                    pack_path.stat().st_size / 1024)
        return pack_path

    def import_voicepack(
        self,
        pack_path: str | Path,
        overwrite: bool = False,
    ) -> VoiceProfile:
        """Import a .voicepack file into the registry.

        Args:
            pack_path: Path to the .voicepack file.
            overwrite: If True, overwrite an existing profile with the same ID.

        Returns:
            The imported VoiceProfile.
        """
        import hashlib

        pack_path = Path(pack_path)
        if not pack_path.exists():
            raise FileNotFoundError(f"VoicePack not found: {pack_path}")

        with zipfile.ZipFile(pack_path, "r") as zf:
            names = zf.namelist()
            if "profile.json" not in names:
                raise ValueError("Invalid .voicepack — missing profile.json")

            profile_json = zf.read("profile.json").decode()
            manifest = json.loads(zf.read("manifest.json")) if "manifest.json" in names else {}

            # Integrity check
            expected = manifest.get("profile_checksum")
            if expected:
                actual = hashlib.sha256(profile_json.encode()).hexdigest()
                if actual != expected:
                    raise ValueError(
                        f"VoicePack integrity check failed! "
                        f"Expected {expected[:16]}…, got {actual[:16]}…"
                    )

            profile = VoiceProfile.model_validate_json(profile_json)

            if profile.id in self._index and not overwrite:
                raise ValueError(
                    f"Profile '{profile.id}' already exists. Use overwrite=True to replace."
                )

            # Extract reference WAV if present
            ref_wav_path = None
            if "reference.wav" in names:
                dest_dir = self.registry_dir / profile.id
                dest_dir.mkdir(exist_ok=True)
                ref_wav_path = dest_dir / "reference.wav"
                ref_wav_path.write_bytes(zf.read("reference.wav"))

                # Update engine config to point to the extracted reference
                profile.engine_config.setdefault("xtts", {})["reference_wav"] = str(ref_wav_path)

        self.save(profile, reference_wav=ref_wav_path)
        logger.info("VoicePack imported: '%s' (%s)", profile.name, profile.id)
        return profile

    # ── Index management ───────────────────────────────────────────

    @staticmethod
    def _profile_to_index_entry(profile: VoiceProfile) -> dict:
        return {
            "id": profile.id,
            "name": profile.name,
            "description": profile.description,
            "personality": profile.personality.value,
            "accent": profile.accent.value,
            "best_score": profile.best_score,
            "target_score": profile.target_score,
            "gender": profile.gender,
            "tags": profile.tags,
            "engine_preference": profile.engine_preference,
            "created_at": profile.created_at.isoformat(),
            "updated_at": profile.updated_at.isoformat(),
            "improvement_iterations": len(profile.improvement_history),
        }

    def _load_index(self) -> dict[str, dict]:
        if self._index_path.exists():
            try:
                return json.loads(self._index_path.read_text())
            except Exception:
                return {}
        return {}

    def _save_index(self) -> None:
        self._index_path.write_text(json.dumps(self._index, indent=2))
