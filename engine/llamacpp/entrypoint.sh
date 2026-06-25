#!/usr/bin/env bash
# llama.cpp engine entrypoint.
#
# llama.cpp's llama-server is OpenAI-compatible AND natively serves the exact
# Unsloth IQ4_NL GGUF (vLLM cannot: it rejects the qwen3moe GGUF architecture).
# It also gives us, for free, the vLLM-equivalent optimizations the brief asks
# for: paged/streamed KV cache, continuous batching (--cont-batching), prompt
# (prefix) caching across requests, flash attention, and GPU offload — all
# built in, no custom KV logic.
set -euo pipefail

HF_FILE="${HF_FILE:-Qwen3.6-35B-A3B-UD-IQ4_NL_XL.gguf}"
MODEL_DIR="${MODEL_DIR:-/models}"
MODEL_PATH="${MODEL_DIR}/${HF_FILE}"

# 1) Fetch weights onto the persistent volume (idempotent; skips if present).
bash /engine/scripts/download_model.sh

if [[ ! -f "${MODEL_PATH}" ]]; then
  echo "FATAL: model not found at ${MODEL_PATH} after download" >&2
  exit 1
fi

# 2) Assemble llama-server flags.
#
# CTX_SIZE is the TOTAL KV-cache context shared across PARALLEL_SLOTS, so the
# effective per-request window is CTX_SIZE / PARALLEL_SLOTS. Defaults below give
# 2 concurrent requests of ~32K tokens each, which fits comfortably alongside
# the ~19.5 GB weights on a 48 GB A6000. Raise CTX_SIZE for longer context if
# VRAM allows; quantize the KV cache (CACHE_TYPE_K/V=q8_0) to stretch it further.
ARGS=(
  -m "${MODEL_PATH}"
  --host 0.0.0.0
  --port "${ENGINE_PORT:-8001}"
  --alias "${SERVED_MODEL_NAME:-qwen3.6-35b-a3b}"
  -ngl "${N_GPU_LAYERS:-999}"          # offload all layers to GPU
  -c "${CTX_SIZE:-65536}"              # total context (KV cache)
  -np "${PARALLEL_SLOTS:-2}"           # continuous-batching slots
  -b "${BATCH_SIZE:-2048}"
  -ub "${UBATCH_SIZE:-512}"
  --cont-batching                      # continuous batching (throughput)
  --flash-attn "${FLASH_ATTN:-on}"     # flash attention (memory + speed)
  --jinja                              # REQUIRED for Qwen tool/function calling
  --reasoning-format "${REASONING_FORMAT:-auto}"   # split <think> into reasoning_content
  --metrics                            # Prometheus metrics at /metrics
  --threads "${THREADS:-8}"
)

# Optional flags, only added when their env var is set.
[[ -n "${ENGINE_API_KEY:-}" ]]      && ARGS+=( --api-key "${ENGINE_API_KEY}" )
[[ -n "${CHAT_TEMPLATE_FILE:-}" ]]  && ARGS+=( --chat-template-file "${CHAT_TEMPLATE_FILE}" )
[[ -n "${CACHE_TYPE_K:-}" ]]        && ARGS+=( --cache-type-k "${CACHE_TYPE_K}" )
[[ -n "${CACHE_TYPE_V:-}" ]]        && ARGS+=( --cache-type-v "${CACHE_TYPE_V}" )

echo "[engine] starting llama-server: ${ARGS[*]} ${EXTRA_LLAMA_ARGS:-}"
# EXTRA_LLAMA_ARGS is intentionally unquoted to allow passing several flags.
exec llama-server "${ARGS[@]}" ${EXTRA_LLAMA_ARGS:-}
