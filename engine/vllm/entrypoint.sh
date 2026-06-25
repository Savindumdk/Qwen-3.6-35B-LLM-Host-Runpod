#!/usr/bin/env bash
# vLLM engine entrypoint (ALTERNATIVE backend).
#
# IMPORTANT: vLLM cannot serve the Unsloth IQ4_NL *GGUF* of this model — it
# recognizes the IQ4_NL quant but rejects the `qwen3moe` GGUF architecture
# ("not supported yet"). So the vLLM path serves an official/community
# vLLM-native quant instead (AWQ by default; GPTQ-Int4 or FP8 also work), which
# vLLM downloads straight from HuggingFace. This is the higher-throughput,
# higher-concurrency path; the llama.cpp path is the one that runs your exact
# downloaded GGUF.
set -euo pipefail

# A vLLM-loadable quant of Qwen3.6-35B-A3B (NOT the GGUF). Override as needed:
#   QuantTrio/Qwen3.6-35B-A3B-AWQ        (awq_marlin)
#   Qwen/Qwen3.6-35B-A3B-FP8             (fp8)
#   Qwen/Qwen3.5-35B-A3B-GPTQ-Int4       (gptq_marlin)
VLLM_MODEL="${VLLM_MODEL:-QuantTrio/Qwen3.6-35B-A3B-AWQ}"

ARGS=(
  serve "${VLLM_MODEL}"
  --host 0.0.0.0
  --port "${ENGINE_PORT:-8001}"
  --served-model-name "${SERVED_MODEL_NAME:-qwen3.6-35b-a3b}"
  --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION:-0.90}"
  --max-model-len "${MAX_MODEL_LEN:-32768}"
  --max-num-seqs "${MAX_NUM_SEQS:-16}"
  --enable-prefix-caching            # reuse shared prompt prefixes (PagedAttention)
  --enable-auto-tool-choice          # OpenAI tool calling
  # qwen3_coder is the parser the official Unsloth/Qwen model card specifies for
  # this model's native XML tool-call format (NOT hermes).
  --tool-call-parser "${TOOL_CALL_PARSER:-qwen3_coder}"
  --reasoning-parser "${REASONING_PARSER:-qwen3}"
)

# Only pass --quantization when explicitly set (no fallback in the test, or it
# would always be added). When unset, vLLM infers the quant from the repo's
# config.json (it auto-detects AWQ/GPTQ/FP8), so leaving it blank is valid.
[[ -n "${VLLM_QUANTIZATION:-}" ]] && ARGS+=( --quantization "${VLLM_QUANTIZATION}" )
[[ -n "${KV_CACHE_DTYPE:-}" ]]   && ARGS+=( --kv-cache-dtype "${KV_CACHE_DTYPE}" )
[[ -n "${ENGINE_API_KEY:-}" ]]   && ARGS+=( --api-key "${ENGINE_API_KEY}" )

echo "[engine] starting vLLM: ${ARGS[*]} ${EXTRA_VLLM_ARGS:-}"
exec vllm "${ARGS[@]}" ${EXTRA_VLLM_ARGS:-}
