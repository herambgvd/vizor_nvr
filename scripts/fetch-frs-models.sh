#!/usr/bin/env bash
# =============================================================================
# fetch-frs-models.sh — load the FRS scenario's ONNX models into ./models.
#
# The FRS plugin runs SCRFD (face detector) + ArcFace (512-d embedder) and an
# optional MiniFASNet anti-spoof model in-process via onnxruntime-gpu. The model
# weights are large binaries and are NOT committed to git (.gitignore). This is
# the single command an operator runs once to load them.
#
# Source resolution per model (first hit wins):
#   1. Already present in ./models      → skipped.
#   2. $FRS_MODEL_BASE_URL/<file>       → downloaded (curl).
#   3. A local path passed via env      → copied.
#
# Usage:
#   FRS_MODEL_BASE_URL=https://models.internal/frs ./scripts/fetch-frs-models.sh
#   # or copy from a local export dir:
#   FRS_MODEL_SRC_DIR=/var/lib/vizor/triton-models ./scripts/fetch-frs-models.sh
#
# The antispoof model is OPTIONAL — recognition runs without it (liveness off).
# =============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELS_DIR="${FRS_MODELS_DIR:-$ROOT_DIR/models}"
BASE_URL="${FRS_MODEL_BASE_URL:-}"
SRC_DIR="${FRS_MODEL_SRC_DIR:-}"

# model_file  required(yes/no)  triton_export_subpath
MODELS=(
  "scrfd_10g.onnx|yes|scrfd_10g/1/model.onnx"
  "arcface_r50.onnx|yes|arcface_r50/1/model.onnx"
  "antispoofing.onnx|no|antispoofing/1/model.onnx"
  "fairface.onnx|no|fairface/1/model.onnx"
)

mkdir -p "$MODELS_DIR"
echo "[fetch-frs-models] target: $MODELS_DIR"

fetch_one() {
  local file="$1" required="$2" triton_sub="$3"
  local dest="$MODELS_DIR/$file"

  if [[ -f "$dest" ]]; then
    echo "  ✓ $file (already present)"
    return 0
  fi

  # 2. Copy from a local Triton export dir, if provided.
  if [[ -n "$SRC_DIR" ]]; then
    for candidate in "$SRC_DIR/$file" "$SRC_DIR/$triton_sub"; do
      if [[ -f "$candidate" ]]; then
        cp "$candidate" "$dest"
        echo "  ✓ $file (copied from $candidate)"
        return 0
      fi
    done
  fi

  # 3. Download from a base URL, if provided.
  if [[ -n "$BASE_URL" ]]; then
    echo "  ↓ $file (downloading from $BASE_URL/$file)"
    if curl -fSL "$BASE_URL/$file" -o "$dest.tmp"; then
      mv "$dest.tmp" "$dest"
      echo "  ✓ $file"
      return 0
    fi
    rm -f "$dest.tmp"
  fi

  if [[ "$required" == "yes" ]]; then
    echo "  ✗ $file MISSING (required). Set FRS_MODEL_BASE_URL or FRS_MODEL_SRC_DIR." >&2
    return 1
  fi
  echo "  - $file skipped (optional, not found)"
  return 0
}

rc=0
for entry in "${MODELS[@]}"; do
  IFS='|' read -r file required triton_sub <<<"$entry"
  fetch_one "$file" "$required" "$triton_sub" || rc=1
done

echo
if [[ $rc -eq 0 ]]; then
  echo "[fetch-frs-models] done. Restart the FRS plugin to pick up the models:"
  echo "  docker compose -f docker-compose.yml -f docker-compose.ai-base.yml -f docker-compose.frs.yml up -d frs"
else
  echo "[fetch-frs-models] required model(s) missing — see errors above." >&2
fi
exit $rc
