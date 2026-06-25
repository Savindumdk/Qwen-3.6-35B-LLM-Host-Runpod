#!/usr/bin/env bash
# Idempotent, resilient model fetcher for the GGUF engine.
#
# Why a download step at all: the model (~19.5 GB) is deliberately NOT baked
# into the Docker image. Instead the container downloads the weights on first
# boot onto a PERSISTENT volume, then skips on every subsequent boot.
#
# Two download backends, picked automatically:
#   1. `hf download` (huggingface_hub) with hf_transfer — FAST (parallel chunks)
#      and robust (resumes its own partials, verifies integrity). Used when the
#      `hf` CLI is available (the RunPod all-in-one image installs it).
#   2. A hardened `curl` resume loop — fallback when `hf` isn't present. It keeps
#      resuming through dropped connections instead of giving up, so a flaky
#      HuggingFace CDN connection can't bounce the whole engine container.
#
# Config (all overridable via env):
#   HF_REPO            default: unsloth/Qwen3.6-35B-A3B-GGUF
#   HF_FILE            default: Qwen3.6-35B-A3B-UD-IQ4_NL_XL.gguf
#   MODEL_DIR          default: /models
#   HF_TOKEN           optional; avoids anonymous-download throttling (faster!)
#   MODEL_DOWNLOAD_URL optional full-URL override (curl path only)
set -uo pipefail

HF_REPO="${HF_REPO:-unsloth/Qwen3.6-35B-A3B-GGUF}"
HF_FILE="${HF_FILE:-Qwen3.6-35B-A3B-UD-IQ4_NL_XL.gguf}"
MODEL_DIR="${MODEL_DIR:-/models}"
DEST="${MODEL_DIR}/${HF_FILE}"
mkdir -p "${MODEL_DIR}"

localsize() { stat -c%s "${DEST}" 2>/dev/null || stat -f%z "${DEST}" 2>/dev/null || echo 0; }

URL="${MODEL_DOWNLOAD_URL:-https://huggingface.co/${HF_REPO}/resolve/main/${HF_FILE}?download=true}"
AUTH=()
[[ -n "${HF_TOKEN:-}" ]] && AUTH=(-H "Authorization: Bearer ${HF_TOKEN}")

# Best-effort authoritative size (Content-Length of the redirected resolve URL).
# Used to confirm completeness; if it can't be determined we rely on the
# backend's own success signal instead.
EXPECTED="$(curl -sIL "${AUTH[@]}" "${URL}" 2>/dev/null \
  | awk 'BEGIN{IGNORECASE=1}/^content-length:/{v=$2} END{gsub(/[^0-9]/,"",v); print v+0}')" || EXPECTED=0
EXPECTED="${EXPECTED:-0}"

echo "[download] file:     ${DEST}"
echo "[download] expected: ${EXPECTED} bytes; have: $(localsize) bytes"

# Already complete? Only skip when we can CONFIRM the full size — never skip on a
# partial file (which would make llama-server try to load a truncated model).
if [[ "${EXPECTED}" -gt 0 && "$(localsize)" -ge "${EXPECTED}" ]]; then
  echo "[download] already complete — skipping"
  echo "${DEST}"
  exit 0
fi

# --- Fast path: huggingface_hub CLI (hf_transfer) ----------------------------
HF_BIN="$(command -v hf || command -v huggingface-cli || true)"
if [[ -n "${HF_BIN}" ]]; then
  echo "[download] using ${HF_BIN} (hf_transfer=${HF_HUB_ENABLE_HF_TRANSFER:-unset})"
  attempt=0
  while (( attempt < 30 )); do
    attempt=$((attempt + 1))
    echo "[download] hf download attempt ${attempt} ..."
    # hf download resumes its own partials and verifies integrity; --local-dir
    # places the file directly at MODEL_DIR/HF_FILE. HF_TOKEN is read from env.
    if "${HF_BIN}" download "${HF_REPO}" "${HF_FILE}" --local-dir "${MODEL_DIR}"; then
      if [[ -f "${DEST}" ]]; then
        echo "[download] done via hf: $(localsize) bytes"
        echo "${DEST}"
        exit 0
      fi
    fi
    echo "[download] hf attempt ${attempt} did not complete; retrying in 10s"
    sleep 10
  done
  echo "[download] hf exhausted retries; falling back to curl"
fi

# --- Fallback: resumable curl loop that survives connection drops ------------
attempt=0
while true; do
  attempt=$((attempt + 1))
  echo "[download] curl attempt ${attempt} (have $(localsize)/${EXPECTED:-?} bytes) ..."
  # --retry 100 + --retry-all-errors keeps curl itself resuming through drops,
  # so transient failures don't exit the script and bounce the engine.
  if curl -L --fail --retry 100 --retry-delay 10 --retry-all-errors \
       --retry-connrefused -C - "${AUTH[@]}" -o "${DEST}" "${URL}"; then
    if [[ "${EXPECTED}" -le 0 || "$(localsize)" -ge "${EXPECTED}" ]]; then
      break
    fi
  fi
  if (( attempt >= 100 )); then
    echo "[download] FATAL: giving up after ${attempt} attempts" >&2
    exit 1
  fi
  echo "[download] interrupted; resuming in 5s ..."
  sleep 5
done

echo "[download] done: $(localsize) bytes"
echo "${DEST}"
