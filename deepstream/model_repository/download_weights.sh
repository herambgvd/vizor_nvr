#!/usr/bin/env bash
# =============================================================================
# Download Triton model weights — direct ONNX, no Python deps.
#
# yolov12m         → YOLOv8m person detector (Ultralytics, schema-compat)
# scrfd    → SCRFD-10G face detector
# arcface          → InsightFace buffalo_l recognition (R100 512-d)
#
# Phase 8: yolov12m + arcface are required for live FRS recognition.
# ppe_classifier weights ship with custom training (TAO toolkit).
# =============================================================================
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$REPO_DIR/yolov12m/1" "$REPO_DIR/scrfd/1" "$REPO_DIR/arcface/1"

dl() {
  local url="$1" out="$2"
  if [ -s "$out" ]; then
    echo "  exists: $out ($(du -h "$out" | cut -f1))"
    return 0
  fi
  echo "  fetching: $url"
  curl -fL --retry 3 --connect-timeout 15 --progress-bar "$url" -o "$out"
}

echo ">> yolov12m (person detector)"
dl "https://github.com/CVHub520/X-AnyLabeling/releases/download/v2.3.6/yolov8m.onnx" \
   "$REPO_DIR/yolov12m/1/model.onnx" \
 || dl "https://huggingface.co/Ultralytics/YOLOv8/resolve/main/yolov8m.onnx" \
       "$REPO_DIR/yolov12m/1/model.onnx"

echo ">> scrfd (face detector)"
dl "https://github.com/akanametov/yolo-face/releases/download/v0.0.0/scrfd.onnx" \
   "$REPO_DIR/scrfd/1/model.onnx" \
 || dl "https://huggingface.co/AdamCodd/YOLOv8n-face-detection/resolve/main/model.onnx" \
       "$REPO_DIR/scrfd/1/model.onnx"

echo ">> arcface (512-d face embedding)"
dl "https://huggingface.co/immich-app/buffalo_l/resolve/main/recognition.onnx" \
   "$REPO_DIR/arcface/1/model.onnx" \
 || dl "https://github.com/SthPhoenix/InsightFace-REST/releases/download/v0.5.0/glintr100.onnx" \
       "$REPO_DIR/arcface/1/model.onnx"

echo
echo "Models on disk:"
du -h "$REPO_DIR"/*/1/model.onnx
echo
echo "Done. Restart Triton: docker compose --profile ai restart triton"
