# ═══════════════════════════════════════════════════════════════
# IT Agents Guardrails — Containerfile
# Compatible with Podman (primary) and Docker
#
# Build targets:
#   podman build -t it-agents-guardrails .                # standard (no voice)
#   podman build --target voice -t it-agents-voice .      # + voice deps (CPU)
#   podman build --target voice-gpu -t it-agents-voice-gpu . # + CUDA
#
# Run:
#   podman run --rm -v $(pwd):/workspace it-agents-guardrails check
#   podman run --rm -v $(pwd):/workspace it-agents-voice voice-create my.wav
# ═══════════════════════════════════════════════════════════════

# ── Stage 1: dependency builder ─────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Build deps: gcc for C extensions, ffmpeg for audio format conversion
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Core deps (always installed)
COPY pyproject.toml .
RUN pip install --upgrade pip wheel setuptools && \
    pip install --prefix=/install \
        pyyaml~=6.0 \
        packaging~=24.0 \
        pydantic~=2.0 \
        pytest~=8.2 \
        pytest-asyncio~=0.23 \
        pytest-xdist~=3.5 \
        pytest-cov~=5.0 \
        ruff~=0.4

# ── Stage 2: voice dependency builder ────────────────────────────
FROM builder AS voice-builder

# Audio system libs for soundfile + librosa
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --prefix=/install \
        soundfile~=0.12 \
        numpy~=1.26 \
        resemblyzer~=0.1

# ── Stage 3: standard runtime (no voice) ────────────────────────
FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="IT Agents Guardrails"
LABEL org.opencontainers.image.description="AI coding guardrails + 10,000 IT agent roles"
LABEL org.opencontainers.image.version="1.1.0"
LABEL org.opencontainers.image.vendor="techivault5"
LABEL org.opencontainers.image.url="https://github.com/techivault5/future-agents"

# Non-root user (Podman-friendly — rootless by default)
RUN groupadd -g 1001 guardrails && \
    useradd -u 1001 -g guardrails -m -s /bin/bash guardrails

# Copy installed packages from builder
COPY --from=builder /install /usr/local

WORKDIR /app
COPY --chown=guardrails:guardrails . /app/

# Workspace mount point (dev project being scanned)
RUN mkdir -p /workspace /app/.cache && \
    chown -R guardrails:guardrails /workspace /app/.cache

RUN chmod +x /app/scripts/entrypoint.sh

USER guardrails

ENV WORKSPACE=/workspace \
    GUARDRAILS_MODE=check \
    PLATFORM_ENV=development \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    # Voice cloning engine (xtts | openvoice | elevenlabs | kokoro | stub)
    VOICE_ENGINE=stub \
    # ElevenLabs API key (set via -e or .env)
    ELEVENLABS_API_KEY="" \
    # OpenVoice checkpoint directory
    OPENVOICE_CKPT_DIR=/app/models/openvoice/checkpoints_v2 \
    # Voice registry location (can be mounted for persistence)
    VOICE_REGISTRY_DIR=/workspace/.voice-registry \
    # Voice accuracy target (0-10, improvement loop stops when reached)
    VOICE_TARGET_SCORE=9.5

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["check"]

# ── Stage 4: voice-enabled runtime (CPU) ────────────────────────
FROM runtime AS voice

USER root

# Audio system libraries (needed at runtime for soundfile/resemblyzer)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy voice deps from voice builder
COPY --from=voice-builder /install /usr/local

USER guardrails

LABEL org.opencontainers.image.title="IT Agents Guardrails + Voice"
LABEL org.opencontainers.image.description="Guardrails + voice cloning (CPU, resemblyzer)"

ENV VOICE_ENGINE=xtts

# ── Stage 5: GPU-accelerated voice runtime ───────────────────────
# FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04 AS voice-gpu
# Uncomment and extend the voice stage above for GPU/CUDA support.
# Requires NVIDIA Container Toolkit:
#   dnf install nvidia-container-toolkit
#   podman run --device nvidia.com/gpu=all ...
