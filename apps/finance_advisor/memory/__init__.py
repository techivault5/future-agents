"""Finance Advisor memory framework: five memory types, pluggable everywhere.

Public surface:

    FinanceMemorySDK   — the facade most callers want
    MemoryManager      — write/recall/consolidate/forget across memory types
    MemoryType         — working | episodic | semantic | procedural | graph
    backends           — InMemoryBackend | SqliteBackend | GraphBackend
    embedders          — HashingEmbedder (default) + local model adapters
    RUNTIME_MATRIX     — CPU/GPU/NPU/Metal/browser local-inference comparison
"""

from finance_advisor.memory.backends import (
    GraphBackend,
    InMemoryBackend,
    MemoryBackend,
    SqliteBackend,
)
from finance_advisor.memory.embeddings import (
    Embedder,
    HashingEmbedder,
    OllamaEmbedder,
    OnnxEmbedder,
    SentenceTransformerEmbedder,
)
from finance_advisor.memory.manager import MemoryManager
from finance_advisor.memory.runtimes import (
    RUNTIME_MATRIX,
    Capabilities,
    ComputeTarget,
    detect_available,
    matrix_as_dicts,
)
from finance_advisor.memory.sdk import FinanceMemorySDK, build_backend
from finance_advisor.memory.skills import SKILLS, skill_catalog
from finance_advisor.memory.types import (
    MemoryRecord,
    MemoryRelation,
    MemoryType,
    RecallHit,
)

__all__ = [
    "RUNTIME_MATRIX",
    "SKILLS",
    "Capabilities",
    "ComputeTarget",
    "Embedder",
    "FinanceMemorySDK",
    "GraphBackend",
    "HashingEmbedder",
    "InMemoryBackend",
    "MemoryBackend",
    "MemoryManager",
    "MemoryRecord",
    "MemoryRelation",
    "MemoryType",
    "OllamaEmbedder",
    "OnnxEmbedder",
    "RecallHit",
    "SentenceTransformerEmbedder",
    "SqliteBackend",
    "build_backend",
    "detect_available",
    "matrix_as_dicts",
    "skill_catalog",
]
