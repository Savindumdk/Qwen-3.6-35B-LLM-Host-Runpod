#!/usr/bin/env bash
# Build and push the RunPod all-in-one image to a container registry.
#
# Usage:
#   REGISTRY=ghcr.io/youruser TAG=v1 ./runpod/build-and-push.sh
#
# Then point a RunPod template at  $REGISTRY/qwen-runpod:$TAG
set -euo pipefail

REGISTRY="${REGISTRY:?set REGISTRY, e.g. ghcr.io/youruser or docker.io/youruser}"
IMAGE="${IMAGE:-qwen-runpod}"
TAG="${TAG:-v1}"
FULL="${REGISTRY}/${IMAGE}:${TAG}"

# Build from the repo root so COPY paths (gateway/, engine/, runpod/) resolve.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "[build] $FULL  (context: $ROOT)"
docker build --platform linux/amd64 -f "${ROOT}/runpod/Dockerfile" -t "${FULL}" "${ROOT}"

echo "[push]  $FULL"
docker push "${FULL}"

echo "[done]  use this image in your RunPod template: ${FULL}"
