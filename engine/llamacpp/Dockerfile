# syntax=docker/dockerfile:1
# --- llama.cpp CUDA server engine -------------------------------------------
# Built on the official upstream CUDA server image, which ships a prebuilt,
# GPU-enabled `llama-server`. We only layer in our download + launch scripts.
#
# Pin a concrete tag (not :latest) for reproducible deploys. Use a RECENT build:
# IQ4_NL had a llama.cpp regression in older builds, and the `--flash-attn on`
# value syntax + `--reasoning-format` require a current server.
FROM ghcr.io/ggml-org/llama.cpp:server-cuda

# curl is used by the model downloader; bash for the entrypoint arrays.
# (The base image is Ubuntu-based; install only if missing.)
RUN (command -v curl >/dev/null 2>&1 || (apt-get update \
      && apt-get install -y --no-install-recommends curl ca-certificates \
      && rm -rf /var/lib/apt/lists/*)) || true

COPY engine/scripts/download_model.sh /engine/scripts/download_model.sh
COPY engine/llamacpp/entrypoint.sh   /engine/entrypoint.sh
RUN chmod +x /engine/scripts/download_model.sh /engine/entrypoint.sh

# Persisted model cache (mount a volume here in compose / RunPod).
ENV MODEL_DIR=/models \
    HF_FILE=Qwen3.6-35B-A3B-UD-IQ4_NL_XL.gguf \
    HF_REPO=unsloth/Qwen3.6-35B-A3B-GGUF \
    ENGINE_PORT=8001

EXPOSE 8001

# Override the base image's llama-server entrypoint with our wrapper.
ENTRYPOINT ["/engine/entrypoint.sh"]
