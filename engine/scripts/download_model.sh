#!/usr/bin/env bash
# Idempotent model fetcher for the GGUF engine (llama.cpp).
#
# Why a download step at all: the model (~19.5 GB) is deliberately NOT baked
# into the Docker image. RunPod and most registries discourage >10 GB images,
# and re-pushing a 20 GB layer on every code change is painful. Instead the
# container downloads the weights on first boot onto a PERSISTENT volume, then
# skips the download on every subsequent boot.
#
# Configuration (all overridable via env):
#   HF_REPO            HuggingFace repo id          (default: unsloth/Qwen3.6-35B-A3B-GGUF)
#   HF_FILE            GGUF filename                (default: Qwen3.6-35B-A3B-UD-IQ4_NL_XL.gguf)
#   MODEL_DIR          where to store the file      (default: /models)
#   MODEL_DOWNLOAD_URL full URL override (optional; takes precedence over repo/file)
#   HF_TOKEN           bearer token for gated/private repos (optional)
#   MIN_SIZE_BYTES     skip-download size threshold (default: 1073741824 = 1 GiB)
set -euo pipefail

HF_REPO="${HF_REPO:-unsloth/Qwen3.6-35B-A3B-GGUF}"
HF_FILE="${HF_FILE:-Qwen3.6-35B-A3B-UD-IQ4_NL_XL.gguf}"
MODEL_DIR="${MODEL_DIR:-/models}"
MIN_SIZE_BYTES="${MIN_SIZE_BYTES:-1073741824}"

URL="${MODEL_DOWNLOAD_URL:-https://huggingface.co/${HF_REPO}/resolve/main/${HF_FILE}?download=true}"
DEST="${MODEL_DIR}/${HF_FILE}"

mkdir -p "${MODEL_DIR}"

# --- skip if already present and plausibly complete -------------------------
if [[ -f "${DEST}" ]]; then
  size=$(stat -c%s "${DEST}" 2>/dev/null || stat -f%z "${DEST}" 2>/dev/null || echo 0)
  if [[ "${size}" -ge "${MIN_SIZE_BYTES}" ]]; then
    echo "[download] model already present: ${DEST} (${size} bytes) — skipping"
    echo "${DEST}"
    exit 0
  fi
  echo "[download] partial file found (${size} bytes); resuming"
fi

echo "[download] fetching ${HF_FILE}"
echo "[download]   from: ${URL}"
echo "[download]   to:   ${DEST}"

AUTH_ARGS=()
if [[ -n "${HF_TOKEN:-}" ]]; then
  AUTH_ARGS=(-H "Authorization: Bearer ${HF_TOKEN}")
fi

# -L follow redirects (HF serves from a CDN), -C - resume, --fail surface HTTP
# errors as a non-zero exit, --retry for transient CDN hiccups.
curl -L --fail --retry 5 --retry-delay 5 --retry-connrefused \
     -C - "${AUTH_ARGS[@]}" \
     -o "${DEST}" "${URL}"

final_size=$(stat -c%s "${DEST}" 2>/dev/null || stat -f%z "${DEST}" 2>/dev/null || echo 0)
echo "[download] done: ${DEST} (${final_size} bytes)"
echo "${DEST}"
