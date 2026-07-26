"""Pluggable embedders — including one that is portable to the browser.

`HashingEmbedder` is the default: pure-stdlib character-ngram hashing into a
fixed-width L2-normalised vector. It needs no model download, no GPU and no
network, and the identical algorithm is implemented in the JavaScript SDK
(`sdk/js/finance-memory.mjs`), so a memory embedded in the browser is
searchable by the Python side and vice versa.

For semantic quality beyond lexical overlap, swap in a local model:

    SentenceTransformerEmbedder  — local CPU/GPU/Metal via sentence-transformers
    OllamaEmbedder               — local Ollama server (nomic-embed-text etc.)
    OnnxEmbedder                 — ONNX Runtime, CPU/DirectML/NPU providers

All of them satisfy the same `Embedder` protocol, so the manager, backends
and skills never know which one is in use.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import urllib.error
import urllib.request
from typing import Protocol, runtime_checkable

DEFAULT_DIM = 256
_TOKEN_RE = re.compile(r"[a-z0-9₹%]+")


@runtime_checkable
class Embedder(Protocol):
    """Anything that turns text into a fixed-width vector."""

    dim: int

    def embed(self, text: str) -> list[float]:
        """Return the embedding for `text`."""
        ...


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens, shared by the embedder and keyword scoring."""
    return _TOKEN_RE.findall(text.lower())


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity; 0.0 when either vector is empty or zero-length."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class HashingEmbedder:
    """Deterministic, dependency-free embedder (word + char trigram hashing).

    Portable by construction: the JS SDK reproduces this exact algorithm, so
    vectors are comparable across runtimes. Quality is lexical, not semantic —
    good enough for recall over short finance facts, and it never fails.
    """

    def __init__(self, dim: int = DEFAULT_DIM) -> None:
        self.dim = dim

    def _bucket(self, feature: str) -> int:
        digest = hashlib.sha1(feature.encode("utf-8")).digest()
        return int.from_bytes(digest[:4], "big") % self.dim

    def embed(self, text: str) -> list[float]:
        """Hash words and character trigrams into an L2-normalised vector."""
        vec = [0.0] * self.dim
        tokens = tokenize(text)
        for token in tokens:
            vec[self._bucket(f"w:{token}")] += 1.0
            padded = f" {token} "
            for i in range(len(padded) - 2):
                vec[self._bucket(f"c:{padded[i : i + 3]}")] += 0.5
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            return vec
        return [v / norm for v in vec]


class SentenceTransformerEmbedder:
    """Local transformer embeddings via sentence-transformers (optional dep).

    Runs on CPU, CUDA or Apple Metal depending on what torch reports; pass
    `device` explicitly to pin it. Raises ImportError if the extra is missing.
    """

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        device: str | None = None,
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as err:  # pragma: no cover - optional dependency
            raise ImportError(
                "sentence-transformers not installed. Install the extra: "
                'pip install -e ".[localnlp]"'
            ) from err
        self._model = SentenceTransformer(model_name, device=device)
        self.dim = int(self._model.get_sentence_embedding_dimension())

    def embed(self, text: str) -> list[float]:
        """Encode text with the local transformer model."""
        return [float(x) for x in self._model.encode(text, normalize_embeddings=True)]


class OllamaEmbedder:
    """Embeddings from a local Ollama server (no API key, stays on device)."""

    def __init__(
        self,
        model: str = "nomic-embed-text",
        host: str | None = None,
        dim: int = 768,
    ) -> None:
        self.model = model
        self.host = (host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        """POST to /api/embeddings; raises on transport failure."""
        payload = json.dumps({"model": self.model, "prompt": text}).encode()
        req = urllib.request.Request(
            f"{self.host}/api/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.load(resp)
        except (urllib.error.URLError, TimeoutError) as err:
            raise RuntimeError(f"Ollama embedding failed: {err}") from err
        vector = [float(x) for x in data.get("embedding", [])]
        if vector:
            self.dim = len(vector)
        return vector


class OnnxEmbedder:
    """ONNX Runtime embeddings — CPU, DirectML or NPU execution providers.

    The same ONNX graph powers Transformers.js in the browser, so an ONNX
    model chosen here can be reused client-side with matching vectors.
    """

    def __init__(self, model_path: str, providers: list[str] | None = None, dim: int = 384) -> None:
        try:
            import onnxruntime
        except ImportError as err:  # pragma: no cover - optional dependency
            raise ImportError(
                'onnxruntime not installed. Install the extra: pip install -e ".[localnlp]"'
            ) from err
        self._session = onnxruntime.InferenceSession(
            model_path, providers=providers or onnxruntime.get_available_providers()
        )
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        """Mean-pool the model's last hidden state into one vector."""
        tokens = [float(abs(hash(t)) % 30000) for t in tokenize(text)] or [0.0]
        inputs = {self._session.get_inputs()[0].name: [tokens]}
        outputs = self._session.run(None, inputs)
        flat = outputs[0]
        while hasattr(flat, "__len__") and len(flat) and hasattr(flat[0], "__len__"):
            flat = [sum(col) / len(col) for col in zip(*flat)]
        return [float(x) for x in flat][: self.dim]
