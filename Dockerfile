# Phase 10: production image for the bot process (bot.py).
#
# Build:
#   docker build -t pipecat-voicedesk-bot .
#
# Run (pointed at Postgres/Redis reachable from the container, and with
# provider keys set):
#   docker run --rm -p 7860:7860 --env-file .env pipecat-voicedesk-bot

FROM python:3.12-slim AS builder

# ffmpeg/libsrtp/libsndfile headers are needed to build aiortc (WebRTC) and
# soundfile's native dependencies during `uv sync`.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libavdevice-dev \
    libavfilter-dev \
    libopus-dev \
    libsndfile1 \
    libsrtp2-dev \
    libvpx-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /uvx /usr/local/bin/

WORKDIR /app

# Install dependencies first, separately from app code, so `docker build`
# only re-resolves them when pyproject.toml/uv.lock actually change.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

COPY . .
RUN uv sync --locked --no-dev

# Nothing in this project uses a GPU (faster-whisper and sentence-transformers
# both run on CPU here), but uv.lock is a universal, cross-platform lock, so
# its Linux torch entry is always the CUDA-enabled build: several gigabytes
# of NVIDIA libraries this image never touches. --locked (needed above, for
# every other package's version to match the lock exactly) pins that same
# entry; this second, unlocked install swaps just torch for PyTorch's own
# CPU-only build afterward. The builder stage pays for both downloads, but
# only this final .venv is copied into the runtime image below, so the
# shipped image carries the small wheel, not the large one.
RUN uv pip install --torch-backend cpu --reinstall-package torch torch

FROM python:3.12-slim AS runtime

# Runtime-only shared libraries (no -dev/build-essential needed here).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libavdevice61 \
    libopus0 \
    libsndfile1 \
    libsrtp2-1 \
    libvpx9 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 voicedesk
WORKDIR /app

COPY --from=builder --chown=voicedesk:voicedesk /app /app

USER voicedesk
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

EXPOSE 7860

# Binds 0.0.0.0 so the platform's networking (Render/Railway, or a plain
# `docker run -p`) can reach it; --host is a pipecat dev-runner CLI flag,
# still applicable here since bot.py's __main__ calls that same runner.
CMD ["python", "bot.py", "--host", "0.0.0.0", "--port", "7860"]
