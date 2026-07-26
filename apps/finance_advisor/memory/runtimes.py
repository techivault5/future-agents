"""Local model runtimes: where the model lives, what silicon runs it.

Five compute targets are covered — CPU, discrete/integrated GPU, NPU, Apple
Metal (unified memory), and the browser (WASM/WebGPU) — with the runtimes that
target each. Everything listed here keeps weights on the user's own device,
which is the point: financial context should not need to leave the machine.

The matrix is data, not prose, so the dashboard and the docs render the same
facts, and `detect_available()` reports what this machine can actually do.

Figures are order-of-magnitude guidance gathered mid-2026, not benchmarks;
re-measure on your own hardware before capacity planning.
"""

from __future__ import annotations

import platform
import shutil
from dataclasses import asdict, dataclass, field
from enum import Enum


class ComputeTarget(str, Enum):
    """The silicon a runtime executes on."""

    CPU = "cpu"
    GPU = "gpu"
    NPU = "npu"
    METAL = "metal"
    BROWSER = "browser"


@dataclass(frozen=True)
class RuntimeProfile:
    """One local inference runtime and its practical trade-offs."""

    name: str
    target: ComputeTarget
    runs_where: str
    good_for: str
    model_formats: list[str]
    throughput: str  # relative, single-user unless stated
    memory_note: str
    setup_effort: str  # low | medium | high
    offline: bool
    embeddable_in: list[str]  # python | node | browser | vscode
    caveats: str

    def to_dict(self) -> dict:
        """Serialise for JSON APIs and the dashboard."""
        data = asdict(self)
        data["target"] = self.target.value
        return data


RUNTIME_MATRIX: list[RuntimeProfile] = [
    RuntimeProfile(
        name="llama.cpp",
        target=ComputeTarget.CPU,
        runs_where="Any x86 (AVX2/AVX-512) or ARM (NEON) machine; no GPU needed",
        good_for="Maximum control, quantised models on commodity hardware, embedded targets",
        model_formats=["GGUF"],
        throughput="Baseline for CPU; 4-bit 7B models are interactive on a modern laptop",
        memory_note="~0.6 GB per B params at Q4; 7B ≈ 4-5 GB RAM",
        setup_effort="medium",
        offline=True,
        embeddable_in=["python", "node"],
        caveats="The only mainstream engine treating CPU as a first-class target; "
        "you tune quantisation and threads yourself",
    ),
    RuntimeProfile(
        name="Ollama",
        target=ComputeTarget.GPU,
        runs_where="NVIDIA/AMD GPU, and CPU or Apple Metal fallback",
        good_for="Default single-developer choice: one-command install, model registry, "
        "OpenAI-compatible API",
        model_formats=["GGUF", "safetensors (converted)"],
        throughput="Good for one user; well below vLLM under concurrency",
        memory_note="Model must fit VRAM for full speed, else it spills to system RAM",
        setup_effort="low",
        offline=True,
        embeddable_in=["python", "node", "vscode"],
        caveats="Management layer wraps llama.cpp/MLX; less knob-level control",
    ),
    RuntimeProfile(
        name="vLLM",
        target=ComputeTarget.GPU,
        runs_where="Server-class NVIDIA/AMD GPUs",
        good_for="Multi-user serving; PagedAttention + continuous batching",
        model_formats=["safetensors", "AWQ", "GPTQ"],
        throughput="~16-20x Ollama on concurrent requests",
        memory_note="Expects the whole model in VRAM; 7B fp16 ≈ 15 GB",
        setup_effort="high",
        offline=True,
        embeddable_in=["python"],
        caveats="Overkill for one household's finance assistant; run it only if "
        "you are serving many users",
    ),
    RuntimeProfile(
        name="MLX",
        target=ComputeTarget.METAL,
        runs_where="Apple Silicon (M-series) via Metal + unified memory",
        good_for="Fastest path on Macs; Ollama 0.19+ uses it under the hood on M-series",
        model_formats=["MLX", "safetensors (converted)"],
        throughput="Best-in-class per watt on Apple Silicon",
        memory_note="Unified memory means RAM is VRAM: a 32 GB Mac runs 30B-class 4-bit",
        setup_effort="low",
        offline=True,
        embeddable_in=["python"],
        caveats="Apple-only; no CUDA path",
    ),
    RuntimeProfile(
        name="ONNX Runtime",
        target=ComputeTarget.NPU,
        runs_where="NPUs and accelerators via execution providers (DirectML on "
        "Windows/Copilot+ PCs, QNN on Snapdragon, OpenVINO on Intel)",
        good_for="Embeddings and small classifiers at very low power; same graph "
        "reused in the browser",
        model_formats=["ONNX"],
        throughput="Excellent for embedding/rerank models; not aimed at large-LLM decode",
        memory_note="Quantised MiniLM-class embedders are 20-90 MB",
        setup_effort="medium",
        offline=True,
        embeddable_in=["python", "node", "browser"],
        caveats="Provider support varies by OS and chip; verify with "
        "onnxruntime.get_available_providers()",
    ),
    RuntimeProfile(
        name="Transformers.js (ONNX Runtime Web)",
        target=ComputeTarget.BROWSER,
        runs_where="Any modern browser — WebGPU when present, WASM fallback",
        good_for="Client-side embeddings and small models with zero server; v4 rewrote "
        "the WebGPU runtime for up to ~4x speedups and a much smaller bundle",
        model_formats=["ONNX (quantised)"],
        throughput="WebGPU can be 10-15x WASM depending on model and hardware",
        memory_note="Keep models under ~2 GB; quantised embedders are tens of MB",
        setup_effort="low",
        offline=True,
        embeddable_in=["browser", "vscode", "node"],
        caveats="First load downloads and caches weights; WebGPU availability still "
        "varies across browsers and drivers",
    ),
    RuntimeProfile(
        name="sentence-transformers",
        target=ComputeTarget.CPU,
        runs_where="CPU, CUDA or Metal via torch",
        good_for="Highest-quality local embeddings with the least code",
        model_formats=["safetensors", "PyTorch"],
        throughput="Hundreds of short texts/sec on CPU for MiniLM-class models",
        memory_note="MiniLM-L6 ≈ 90 MB; torch itself is the heavy part of the install",
        setup_effort="low",
        offline=True,
        embeddable_in=["python"],
        caveats="Pulls in torch; use the ONNX export when install size matters",
    ),
]


@dataclass
class Capabilities:
    """What this specific machine can run right now."""

    system: str
    machine: str
    python_version: str
    apple_silicon: bool = False
    ollama_installed: bool = False
    torch_cuda: bool = False
    torch_mps: bool = False
    onnx_providers: list[str] = field(default_factory=list)
    sentence_transformers: bool = False
    recommended: str = ""

    def to_dict(self) -> dict:
        """Serialise for JSON APIs and the dashboard."""
        return asdict(self)


def detect_available() -> Capabilities:
    """Probe the local machine and recommend an embedding runtime.

    Import failures are expected and swallowed — every optional dependency here
    is genuinely optional, and the hashing embedder always works.
    """
    caps = Capabilities(
        system=platform.system(),
        machine=platform.machine(),
        python_version=platform.python_version(),
        apple_silicon=platform.system() == "Darwin" and platform.machine() == "arm64",
        ollama_installed=shutil.which("ollama") is not None,
    )
    try:
        import torch

        caps.torch_cuda = bool(torch.cuda.is_available())
        mps = getattr(torch.backends, "mps", None)
        caps.torch_mps = bool(mps and mps.is_available())
    except Exception:
        pass
    try:
        import onnxruntime

        caps.onnx_providers = list(onnxruntime.get_available_providers())
    except Exception:
        pass
    try:
        import sentence_transformers  # noqa: F401

        caps.sentence_transformers = True
    except Exception:
        pass

    if caps.sentence_transformers and (caps.torch_cuda or caps.torch_mps):
        caps.recommended = "SentenceTransformerEmbedder (GPU/Metal accelerated)"
    elif caps.sentence_transformers:
        caps.recommended = "SentenceTransformerEmbedder (CPU)"
    elif caps.ollama_installed:
        caps.recommended = "OllamaEmbedder (nomic-embed-text)"
    elif caps.onnx_providers:
        caps.recommended = f"OnnxEmbedder (providers: {', '.join(caps.onnx_providers[:2])})"
    else:
        caps.recommended = "HashingEmbedder (zero-dependency default)"
    return caps


def matrix_as_dicts() -> list[dict]:
    """The full runtime matrix, JSON-ready."""
    return [profile.to_dict() for profile in RUNTIME_MATRIX]


def by_target(target: ComputeTarget) -> list[RuntimeProfile]:
    """Runtimes that execute on a given compute target."""
    return [p for p in RUNTIME_MATRIX if p.target is target]
