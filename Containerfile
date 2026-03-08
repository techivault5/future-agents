# ═══════════════════════════════════════════════════════════════
# IT Agents Guardrails — Containerfile
# Compatible with Podman (primary) and Docker
#
# Build:  podman build -t it-agents-guardrails .
# Run:    podman run --rm -v $(pwd):/workspace it-agents-guardrails
# ═══════════════════════════════════════════════════════════════

# ── Stage 1: dependency builder ─────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency spec and install into /install prefix
COPY pyproject.toml .
RUN pip install --upgrade pip wheel setuptools && \
    pip install --prefix=/install pyyaml packaging pytest pytest-asyncio ruff pydantic

# ── Stage 2: runtime image ──────────────────────────────────────
FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="IT Agents Guardrails"
LABEL org.opencontainers.image.description="AI coding guardrails — secrets, packages, structure"
LABEL org.opencontainers.image.version="1.0.0"
LABEL org.opencontainers.image.vendor="techivault5"

# Non-root user (Podman-friendly — rootless by default)
RUN groupadd -g 1001 guardrails && \
    useradd -u 1001 -g guardrails -m -s /bin/bash guardrails

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# App directory (the guardrails source lives here)
WORKDIR /app

# Copy the entire project
COPY --chown=guardrails:guardrails . /app/

# Workspace is where the dev project being scanned lives
# Mounted at runtime: -v /path/to/your/project:/workspace
RUN mkdir -p /workspace && chown guardrails:guardrails /workspace

# Make entrypoint executable
RUN chmod +x /app/scripts/entrypoint.sh

# Drop to non-root
USER guardrails

# Default workspace path (override with -e WORKSPACE=/workspace)
ENV WORKSPACE=/workspace \
    GUARDRAILS_MODE=check \
    PLATFORM_ENV=development \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

ENTRYPOINT ["/app/scripts/entrypoint.sh"]

# Default: run guardrails check on /workspace
CMD ["check"]
