# syntax=docker/dockerfile:1
# --- Gateway image ----------------------------------------------------------
# Small, CPU-only image. The gateway does no model work — it proxies to the
# engine — so it stays light (~150MB) and starts in well under a second.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# curl is only needed for the container HEALTHCHECK.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first for layer caching.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Copy source.
COPY app ./app

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /app/data \
 && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
  
# Liveness: the gateway answers /health as soon as the process is up.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${GATEWAY_PORT:-8000}/health" || exit 1

# Shell form so ${VARS} expand from the environment at runtime.
CMD uvicorn app.main:app \
      --host "${GATEWAY_HOST:-0.0.0.0}" \
      --port "${GATEWAY_PORT:-8000}" \
      --workers "${GATEWAY_WORKERS:-1}" \
      --no-access-log \
      --proxy-headers \
      --forwarded-allow-ips '*'
