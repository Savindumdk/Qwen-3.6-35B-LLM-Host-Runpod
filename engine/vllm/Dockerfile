# syntax=docker/dockerfile:1
# --- vLLM engine (alternative backend) --------------------------------------
# Built on the official vLLM OpenAI image. vLLM downloads the model from HF on
# first boot into HF_HOME, which we point at the persistent /models volume so
# weights survive restarts.
#
# Pin a concrete vLLM version for reproducibility (newer = better Qwen3 MoE +
# tool/reasoning-parser support).
FROM vllm/vllm-openai:latest

COPY engine/vllm/entrypoint.sh /engine/entrypoint.sh
RUN chmod +x /engine/entrypoint.sh

# Cache HF downloads on the mounted volume (set the mount to /models).
ENV HF_HOME=/models/hf \
    HF_HUB_CACHE=/models/hf \
    ENGINE_PORT=8001

EXPOSE 8001

# The base image's entrypoint is the vLLM API server; override with our wrapper
# (which itself calls `vllm serve`).
ENTRYPOINT ["/engine/entrypoint.sh"]
