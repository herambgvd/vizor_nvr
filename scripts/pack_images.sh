#!/usr/bin/env bash
# Pack the Vizor NVR images into ./_ship/*.tar.gz for Google-Drive transfer to a
# client with no registry. Custom images carry the app; base images are the ones the
# client doesn't already have. Run from the repo root after `docker compose ... build`.
set -euo pipefail

OUT="${1:-_ship}"
mkdir -p "$OUT"

# Custom app images (built from this repo).
CUSTOM=(
  vizor_nvr-backend
  vizor_nvr-frontend
  vizor_nvr-migrate
  vizor_nvr-frs
  vizor_nvr-ppe
)

# Base images to ship. The client wipes EVERYTHING, so ship the full set the stack
# needs. (No separate nvidia/cuda image — it's only a build base, baked into the frs/ppe
# images; no compose service pulls it.)
BASE=(
  nvcr.io/nvidia/tritonserver:24.08-py3
  timescale/timescaledb:2.17.2-pg16
  postgres:16-alpine
  redis:7-alpine
  qdrant/qdrant:v1.18.0
  rustfs/rustfs:latest
  alexxit/go2rtc:1.9.9
  nginx:1.27-alpine
)

pack() {
  local img="$1"
  # safe filename
  local fn; fn="$(echo "$img" | tr '/:' '__').tar.gz"
  if ! docker image inspect "$img" >/dev/null 2>&1; then
    echo "!! missing image: $img  (build/pull it first)" >&2
    return 1
  fi
  echo ">> saving $img -> $OUT/$fn"
  docker save "$img" | gzip -1 > "$OUT/$fn"
}

echo "== custom images =="
for i in "${CUSTOM[@]}"; do pack "$i"; done
echo "== base images =="
for i in "${BASE[@]}"; do pack "$i" || true; done

echo
echo "Done. Files in $OUT/:"
ls -lh "$OUT"
echo
echo "Upload $OUT/*.tar.gz to Google Drive, plus: docker-compose*.yml, .env,"
echo "triton/model_repository/ (ONNX only — exclude *_trt/1/*.plan), triton/build_trt_engines.sh,"
echo "scenarios/*/scenario.json, and DEPLOY_SMCC.md."
