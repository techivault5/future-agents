"""Tests for VoiceRegistry — save, load, search, export, import."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from future_agents.voice.voice_profile import (
    AccentType, PersonalityType, SpeakerEmbedding, VoiceProfile,
)
from future_agents.voice.voice_registry import VoiceRegistry


def make_profile(name: str = "Test", **kwargs) -> VoiceProfile:
    return VoiceProfile(
        name=name,
        personality=kwargs.get("personality", PersonalityType.FRIENDLY_HELPER),
        accent=kwargs.get("accent", AccentType.AMERICAN_GENERAL),
        tags=kwargs.get("tags", ["test"]),
        description=kwargs.get("description", "A test voice"),
        embedding=SpeakerEmbedding(vector=[0.5, -0.3, 0.1, 0.8]),
        **{k: v for k, v in kwargs.items()
           if k not in ("personality", "accent", "tags", "description")},
    )


class TestVoiceRegistryCRUD:
    @pytest.fixture
    def registry(self, tmp_path) -> VoiceRegistry:
        return VoiceRegistry(registry_dir=tmp_path / "voices")

    def test_save_and_load(self, registry):
        p = make_profile("My Voice")
        registry.save(p)

        loaded = registry.load(p.id)
        assert loaded.id == p.id
        assert loaded.name == "My Voice"
        assert loaded.embedding.vector == p.embedding.vector

    def test_save_creates_json_and_yaml(self, registry, tmp_path):
        p = make_profile()
        registry.save(p)
        assert (registry.registry_dir / p.id / "profile.json").exists()
        assert (registry.registry_dir / p.id / "profile.yaml").exists()

    def test_save_updates_index(self, registry):
        p = make_profile()
        registry.save(p)
        assert p.id in registry._index
        entry = registry._index[p.id]
        assert entry["name"] == p.name

    def test_load_missing_raises(self, registry):
        with pytest.raises(KeyError):
            registry.load("nonexistent-id")

    def test_delete_removes_files(self, registry):
        p = make_profile()
        registry.save(p)
        assert p.id in registry._index

        registry.delete(p.id)
        assert p.id not in registry._index
        assert not (registry.registry_dir / p.id).exists()

    def test_list_all(self, registry):
        profiles = [make_profile(f"Voice {i}") for i in range(3)]
        for p in profiles:
            registry.save(p)
        all_entries = registry.list_all()
        assert len(all_entries) == 3

    def test_save_with_reference_wav(self, registry, tmp_audio_file):
        p = make_profile("WAV Test")
        registry.save(p, reference_wav=tmp_audio_file)
        wav_path = registry.registry_dir / p.id / "reference.wav"
        assert wav_path.exists()

    def test_get_reference_wav(self, registry, tmp_audio_file):
        p = make_profile()
        registry.save(p, reference_wav=tmp_audio_file)
        wav = registry.get_reference_wav(p.id)
        assert wav is not None
        assert wav.exists()

    def test_get_reference_wav_returns_none_if_missing(self, registry):
        p = make_profile()
        registry.save(p)
        assert registry.get_reference_wav(p.id) is None

    def test_index_persists_to_disk(self, tmp_path):
        reg1 = VoiceRegistry(registry_dir=tmp_path / "voices")
        p = make_profile("Persist Test")
        reg1.save(p)

        # Create a new registry instance pointing to the same dir
        reg2 = VoiceRegistry(registry_dir=tmp_path / "voices")
        loaded = reg2.load(p.id)
        assert loaded.name == "Persist Test"


class TestVoiceRegistrySearch:
    @pytest.fixture
    def registry_with_profiles(self, tmp_path) -> VoiceRegistry:
        registry = VoiceRegistry(registry_dir=tmp_path / "voices")
        profiles = [
            make_profile("Executive Voice", personality=PersonalityType.FORMAL_EXECUTIVE,
                         accent=AccentType.BRITISH_RP, tags=["formal", "executive"],
                         best_score=9.2),
            make_profile("Friendly Bot", personality=PersonalityType.FRIENDLY_HELPER,
                         accent=AccentType.AMERICAN_GENERAL, tags=["friendly", "support"],
                         best_score=8.5),
            make_profile("Calm Support", personality=PersonalityType.CALM_COUNSELOR,
                         accent=AccentType.CANADIAN, tags=["calm", "support"],
                         best_score=7.8),
        ]
        for p in profiles:
            registry.save(p)
        return registry

    def test_search_by_name(self, registry_with_profiles):
        results = registry_with_profiles.search("Executive")
        assert len(results) == 1
        assert results[0]["name"] == "Executive Voice"

    def test_search_by_tag(self, registry_with_profiles):
        results = registry_with_profiles.search("support")
        assert len(results) == 2

    def test_search_by_personality(self, registry_with_profiles):
        results = registry_with_profiles.search(
            personality=PersonalityType.CALM_COUNSELOR.value
        )
        assert len(results) == 1
        assert "Calm" in results[0]["name"]

    def test_search_by_accent(self, registry_with_profiles):
        results = registry_with_profiles.search(accent=AccentType.BRITISH_RP.value)
        assert len(results) == 1

    def test_search_min_score(self, registry_with_profiles):
        results = registry_with_profiles.search(min_score=9.0)
        assert len(results) == 1
        assert results[0]["best_score"] >= 9.0

    def test_search_results_sorted_by_score(self, registry_with_profiles):
        results = registry_with_profiles.search()
        scores = [r["best_score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_search_empty_query_returns_all(self, registry_with_profiles):
        results = registry_with_profiles.search("")
        assert len(results) == 3

    def test_search_by_multiple_tags(self, registry_with_profiles):
        # Only "Friendly Bot" has both "friendly" and "support"
        results = registry_with_profiles.search(tags=["friendly", "support"])
        assert len(results) == 1
        assert results[0]["name"] == "Friendly Bot"


class TestVoicePack:
    """Export and import of .voicepack files."""

    @pytest.fixture
    def registry(self, tmp_path) -> VoiceRegistry:
        return VoiceRegistry(registry_dir=tmp_path / "voices")

    def test_export_creates_voicepack_file(self, registry, tmp_path):
        p = make_profile("Export Test")
        registry.save(p)
        pack = registry.export_voicepack(p.id, output_dir=tmp_path)
        assert pack.exists()
        assert pack.suffix == ".voicepack"

    def test_voicepack_is_valid_zip(self, registry, tmp_path):
        p = make_profile("Zip Test")
        registry.save(p)
        pack = registry.export_voicepack(p.id, output_dir=tmp_path)
        assert zipfile.is_zipfile(pack)

    def test_voicepack_contains_required_files(self, registry, tmp_path):
        p = make_profile("Contents Test")
        registry.save(p)
        pack = registry.export_voicepack(p.id, output_dir=tmp_path)
        with zipfile.ZipFile(pack) as zf:
            names = zf.namelist()
        assert "profile.json" in names
        assert "manifest.json" in names

    def test_voicepack_includes_reference_wav(self, registry, tmp_path, tmp_audio_file):
        p = make_profile("WAV Pack Test")
        registry.save(p, reference_wav=tmp_audio_file)
        pack = registry.export_voicepack(p.id, output_dir=tmp_path, include_reference_wav=True)
        with zipfile.ZipFile(pack) as zf:
            assert "reference.wav" in zf.namelist()

    def test_export_import_roundtrip(self, tmp_path):
        """Export from registry A, import into registry B — data intact."""
        reg_a = VoiceRegistry(registry_dir=tmp_path / "reg_a")
        reg_b = VoiceRegistry(registry_dir=tmp_path / "reg_b")

        p = make_profile("Roundtrip")
        reg_a.save(p)
        pack = reg_a.export_voicepack(p.id, output_dir=tmp_path)

        imported = reg_b.import_voicepack(pack)
        assert imported.id == p.id
        assert imported.name == p.name
        assert imported.embedding.vector == p.embedding.vector

    def test_import_duplicate_raises_without_overwrite(self, tmp_path):
        reg = VoiceRegistry(registry_dir=tmp_path / "voices")
        p = make_profile("Duplicate")
        reg.save(p)
        pack = reg.export_voicepack(p.id, output_dir=tmp_path)

        with pytest.raises(ValueError, match="already exists"):
            reg.import_voicepack(pack, overwrite=False)

    def test_import_duplicate_succeeds_with_overwrite(self, tmp_path):
        reg = VoiceRegistry(registry_dir=tmp_path / "voices")
        p = make_profile("Overwrite Test")
        reg.save(p)
        pack = reg.export_voicepack(p.id, output_dir=tmp_path)

        # Should not raise
        imported = reg.import_voicepack(pack, overwrite=True)
        assert imported.id == p.id

    def test_import_detects_tampered_pack(self, tmp_path):
        reg = VoiceRegistry(registry_dir=tmp_path / "voices")
        p = make_profile("Tamper Test")
        reg.save(p)
        pack = reg.export_voicepack(p.id, output_dir=tmp_path)

        # Tamper: modify profile.json inside the ZIP
        import io
        buf = io.BytesIO(pack.read_bytes())
        with zipfile.ZipFile(buf, "a") as zf:
            zf.writestr("profile.json", '{"id": "tampered"}')
        pack.write_bytes(buf.getvalue())

        with pytest.raises(ValueError, match="integrity check failed"):
            reg.import_voicepack(pack)

    def test_manifest_includes_metadata(self, tmp_path):
        reg = VoiceRegistry(registry_dir=tmp_path / "voices")
        p = make_profile("Manifest Test")
        reg.save(p)
        pack = reg.export_voicepack(p.id, output_dir=tmp_path)
        with zipfile.ZipFile(pack) as zf:
            manifest = json.loads(zf.read("manifest.json"))
        assert manifest["profile_id"] == p.id
        assert "profile_checksum" in manifest
        assert manifest["voicepack_version"] == "1.0"
