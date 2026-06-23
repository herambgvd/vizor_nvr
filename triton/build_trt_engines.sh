#!/usr/bin/env bash
# Build the TensorRT FP16 engines for every scenario from the committed ONNX +
# config.pbtxt. The .plan files are GPU/TRT-version specific and gitignored, so run
# this on the target box after the ONNX weights are in place. Uses trtexec inside
# the running Triton container (gvd_ai_triton).
#
# Usage: ./build_trt_engines.sh            # build all
#        ./build_trt_engines.sh scrfd_10g  # build one
set -euo pipefail

TRITON=${TRITON_CONTAINER:-gvd_ai_triton}
WS=${TRT_WORKSPACE_MB:-2048}

# model -> trtexec shape flags (empty = fixed shape, no flag needed)
declare -A SHAPES=(
  [ppe_yolo26]=""
  [anpr_plate]=""
  [yolo26]=""
  [arcface_r50]="--shapes=input.1:1x3x112x112"
  [fairface]="--shapes=input:1x3x224x224"
  [antispoofing]="--shapes=input:1x3x80x80"
  [person_reid]="--shapes=input:1x3x256x128"
  [scrfd_10g]="--minShapes=input.1:1x3x320x320 --optShapes=input.1:1x3x640x640 --maxShapes=input.1:1x3x1280x1280"
  [ppocr_v6]="--minShapes=x:1x3x48x80 --optShapes=x:1x3x48x320 --maxShapes=x:1x3x48x640"
  [clothing_yolos]="--minShapes=pixel_values:1x3x224x224 --optShapes=pixel_values:1x3x512x512 --maxShapes=pixel_values:1x3x800x800"
)

build_one() {
  local m=$1
  local trt="${m}_trt"
  echo "=== building ${trt} ==="
  docker exec "$TRITON" bash -c "
    /usr/src/tensorrt/bin/trtexec \
      --onnx=/models/${m}/1/model.onnx \
      --saveEngine=/tmp/${m}.plan \
      --fp16 --memPoolSize=workspace:${WS} ${SHAPES[$m]} \
      2>&1 | grep -iE 'Engine built|GPU Compute Time.*median|FAILED|Error' | tail -2"
  docker cp "${TRITON}:/tmp/${m}.plan" "$(dirname "$0")/model_repository/${trt}/1/model.plan"
  echo "    -> model_repository/${trt}/1/model.plan"
}

if [ $# -gt 0 ]; then
  build_one "$1"
else
  for m in "${!SHAPES[@]}"; do build_one "$m"; done
fi
echo "done. Triton will load the *_trt models named in docker-compose.ai.yml --load-model."
