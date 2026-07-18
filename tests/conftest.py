"""Shared pytest fixtures for the full test suite."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── Paths ─────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).parent.parent
AGENTS_DIR = REPO_ROOT / "agents"
AGENTS_INDEX = AGENTS_DIR / "agents_index.json"
GUARDRAILS_DIR = REPO_ROOT / "guardrails"


# ── Agents Index ──────────────────────────────────────────────────

@pytest.fixture(scope="session")
def agents_index() -> list[dict]:
    """All 10,000 agent metadata entries from the index."""
    return json.loads(AGENTS_INDEX.read_text())


@pytest.fixture(scope="session")
def agents_by_role(agents_index) -> dict[str, list[dict]]:
    """Agents grouped by role string."""
    groups: dict[str, list[dict]] = {}
    for a in agents_index:
        role = a.get("role", "unknown")
        groups.setdefault(role, []).append(a)
    return groups


@pytest.fixture(scope="session")
def agents_by_seniority(agents_index) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for a in agents_index:
        s = a.get("seniority", "unknown")
        groups.setdefault(s, []).append(a)
    return groups


@pytest.fixture(scope="session")
def sample_agents(agents_index) -> list[dict]:
    """Representative 100-agent sample — one per seniority per role (capped)."""
    seen: set[str] = set()
    sample = []
    for a in agents_index:
        key = f"{a.get('role')}:{a.get('seniority')}"
        if key not in seen:
            seen.add(key)
            sample.append(a)
        if len(sample) >= 100:
            break
    return sample


# ── Agent System ──────────────────────────────────────────────────

@pytest.fixture
def mock_event_bus():
    bus = MagicMock()
    bus.emit = AsyncMock()
    bus.subscribe = MagicMock()
    return bus


@pytest.fixture
async def agent_system():
    """A real (in-memory) AgentSystem for integration tests."""
    from future_agents.system import AgentSystem
    system = AgentSystem()
    await system.start()
    yield system
    await system.stop()


# ── Voice fixtures ─────────────────────────────────────────────────

@pytest.fixture
def sample_voice_profile() -> dict:
    return {
        "id": "vp-test-001",
        "name": "Test Voice",
        "personality": "friendly-helper",
        "gender": "neutral",
        "accent": "american-general",
        "speaking_rate": 1.0,
        "pitch_offset": 0.0,
        "energy": 0.8,
        "emotion_weights": {"neutral": 0.7, "friendly": 0.3},
        "engine_preference": ["stub"],
        "description": "A test voice profile",
        "tags": ["test", "neutral"],
    }


@pytest.fixture
def tmp_voice_dir(tmp_path) -> Path:
    voice_dir = tmp_path / "voices"
    voice_dir.mkdir()
    return voice_dir


@pytest.fixture
def tmp_audio_file(tmp_path) -> Path:
    """Valid WAV file — 4 seconds of sine wave at 22050 Hz mono (sufficient for voice processing)."""
    import math
    import struct
    wav_path = tmp_path / "sample.wav"
    sample_rate = 22050
    duration_s = 4.0
    freq = 220.0
    num_samples = int(sample_rate * duration_s)
    samples = [
        int(math.sin(2 * math.pi * freq * i / sample_rate) * 16000)
        for i in range(num_samples)
    ]
    data = struct.pack(f"<{num_samples}h", *samples)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(data), b"WAVE",
        b"fmt ", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16,
        b"data", len(data),
    )
    wav_path.write_bytes(header + data)
    return wav_path


# ── Guardrails fixtures ────────────────────────────────────────────

@pytest.fixture
def guardrails_engine(tmp_path):
    import sys
    sys.path.insert(0, str(GUARDRAILS_DIR.parent))
    from guardrails.guardrails_engine import GuardrailsEngine
    return GuardrailsEngine()


# ── Helpers ────────────────────────────────────────────────────────

def load_agent_yaml(agent_id: str, agents_dir: Path = AGENTS_DIR) -> dict | None:
    """Load a specific agent YAML by ID."""
    import yaml
    for yaml_file in agents_dir.rglob(f"{agent_id}.yaml"):
        return yaml.safe_load(yaml_file.read_text())
    return None
