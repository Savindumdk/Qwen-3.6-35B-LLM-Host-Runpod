# syntax=docker/dockerfile:1
# =============================================================================
# RunPod ALL-IN-ONE image: llama.cpp engine + FastAPI gateway in one container.
#
# RunPod Pods run a single container, so we bundle both processes and supervise
# them with supervisord. Built FROM the official llama.cpp CUDA server image so
# we inherit a GPU-ready `llama-server`; we add Python + the gateway on top.
#
# The model is downloaded at runtime to the persistent /workspace volume — it is
# NOT baked into the image (keeps the image small and within registry limits).
#
# Build from the REPO ROOT so the COPY paths resolve:
#   docker build -f runpod/Dockerfile -t ghcr.io/<you>/qwen-runpod:v1 .
# =============================================================================
FROM ghcr.io/ggml-org/llama.cpp:server-cuda

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-venv curl ca-certificates supervisor \
 && rm -rf /var/lib/apt/lists/*

# --- gateway (isolated venv avoids PEP-668 system-package conflicts) ---------
RUN python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY gateway/requirements.txt /app/requirements.txt
# Gateway deps + the HuggingFace CLI with hf_transfer for fast, robust,
# parallel-chunk model downloads (used by engine/scripts/download_model.sh).
RUN pip install --no-cache-dir -r /app/requirements.txt "huggingface_hub[hf_transfer]"
COPY gateway/app /app/app

# --- engine scripts ----------------------------------------------------------
COPY engine/scripts/download_model.sh /engine/scripts/download_model.sh
COPY engine/llamacpp/entrypoint.sh    /engine/entrypoint.sh
RUN chmod +x /engine/scripts/download_model.sh /engine/entrypoint.sh

# --- supervisor --------------------------------------------------------------
COPY runpod/supervisord.conf /etc/supervisor/supervisord.conf

# Defaults tuned for RunPod: model + HF cache land on the persistent /workspace
# volume so they survive pod stop/restart and are downloaded only once.
ENV MODEL_DIR=/workspace/models \
    HF_HOME=/workspace/hf \
    HF_HUB_CACHE=/workspace/hf \
    LLAMA_CACHE=/workspace/hf \
    HF_HUB_ENABLE_HF_TRANSFER=1 \
    HF_REPO=unsloth/Qwen3.6-35B-A3B-GGUF \
    HF_FILE=Qwen3.6-35B-A3B-UD-IQ4_NL_XL.gguf \
    SERVED_MODEL_NAME=qwen3.6-35b-a3b \
    DEFAULT_MODEL=qwen3.6-35b-a3b \
    ENGINE_PORT=8001 \
    UPSTREAM_BASE_URL=http://127.0.0.1:8001/v1 \
    GATEWAY_PORT=8000 \
    CTX_SIZE=65536 \
    PARALLEL_SLOTS=2 \
    LOG_JSON=true \
    ANALYTICS_ENABLED=true \
    DATABASE_URL=sqlite+aiosqlite:////workspace/gateway.db

# Expose ONLY the gateway. Declare 8000 as an HTTP port in the RunPod template.
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${GATEWAY_PORT:-8000}/health" || exit 1

ENTRYPOINT ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf"]
