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
# ONE request the full 128K context (PARALLEL_SLOTS=1), with the KV cache stored
# as q8_0 (near-lossless) so it fits alongside the ~19.5 GB weights on a 48 GB
# A6000 with room to spare. This pairs with a client (Zoo Code) doing context
# condensing for effectively unlimited conversations. Push CTX_SIZE toward the
# model's 262K native limit if VRAM allows; the model needs YaRN beyond that.
ARGS=(
  -m "${MODEL_PATH}"
  --host 0.0.0.0
  --port "${ENGINE_PORT:-8001}"
  --alias "${SERVED_MODEL_NAME:-qwen3.6-35b-a3b}"
  -ngl "${N_GPU_LAYERS:-999}"          # offload all layers to GPU
  -c "${CTX_SIZE:-131072}"             # total context (KV cache); 128K default
  -np "${PARALLEL_SLOTS:-1}"           # continuous-batching slots (1 = full ctx/req)
  -b "${BATCH_SIZE:-2048}"
  -ub "${UBATCH_SIZE:-512}"
  --cont-batching                      # continuous batching (throughput)
  --flash-attn "${FLASH_ATTN:-on}"     # flash attention (memory + speed)
  --jinja                              # REQUIRED for Qwen tool/function calling
  --reasoning-format "${REASONING_FORMAT:-auto}"   # split <think> into reasoning_content
  --metrics                            # Prometheus metrics at /metrics
  --threads "${THREADS:-8}"
  # Default sampling = Qwen's recommended thinking/coding preset (temp 0.6,
  # top_p 0.95, top_k 20, min_p 0, presence_penalty 0). These apply only when a
  # request omits the parameter, so a client (Zoo Code) that sends its own
  # temperature still wins. Override any via the SAMPLING_* env vars.
  --temp "${SAMPLING_TEMP:-0.6}"
  --top-p "${SAMPLING_TOP_P:-0.95}"
  --top-k "${SAMPLING_TOP_K:-20}"
  --min-p "${SAMPLING_MIN_P:-0.0}"
  --presence-penalty "${SAMPLING_PRESENCE_PENALTY:-0.0}"
)

# Optional flags, only added when their env var is set.
[[ -n "${ENGINE_API_KEY:-}" ]]      && ARGS+=( --api-key "${ENGINE_API_KEY}" )
[[ -n "${CHAT_TEMPLATE_FILE:-}" ]]  && ARGS+=( --chat-template-file "${CHAT_TEMPLATE_FILE}" )
[[ -n "${CACHE_TYPE_K:-}" ]]        && ARGS+=( --cache-type-k "${CACHE_TYPE_K}" )
[[ -n "${CACHE_TYPE_V:-}" ]]        && ARGS+=( --cache-type-v "${CACHE_TYPE_V}" )

# Locate the llama-server binary. The official llama.cpp images ship it at a
# fixed path with a full-path ENTRYPOINT (e.g. /app/llama-server) rather than on
# PATH, so a bare `llama-server` call fails with "not found" (exit 127). Detect
# it robustly so this works regardless of the base image's layout.
LLAMA_BIN="$(command -v llama-server 2>/dev/null || true)"
if [[ -z "${LLAMA_BIN}" ]]; then
  for p in /app/llama-server /llama-server /usr/local/bin/llama-server \
           /usr/bin/llama-server /opt/llama.cpp/llama-server /llama.cpp/llama-server; do
    [[ -x "${p}" ]] && { LLAMA_BIN="${p}"; break; }
  done
fi
if [[ -z "${LLAMA_BIN}" ]]; then
  LLAMA_BIN="$(find / -maxdepth 6 -name llama-server -type f 2>/dev/null | head -n1)"
fi
if [[ -z "${LLAMA_BIN}" ]]; then
  echo "FATAL: llama-server binary not found in image" >&2
  exit 1
fi

echo "[engine] using llama-server at: ${LLAMA_BIN}"
echo "[engine] starting: ${LLAMA_BIN} ${ARGS[*]} ${EXTRA_LLAMA_ARGS:-}"
# EXTRA_LLAMA_ARGS is intentionally unquoted to allow passing several flags.
exec "${LLAMA_BIN}" "${ARGS[@]}" ${EXTRA_LLAMA_ARGS:-}
