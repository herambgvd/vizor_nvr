# Triton Model Repository

Mounted at `/models` in the `triton` container. Each subdirectory is one
model. Triton auto-loads everything that matches its config.

## Layout

```
model_repository/
  yolov12m/                  # Person detector (used by People Counting)
    config.pbtxt
    1/
      model.onnx
  scrfd/             # Face detector (FRS)
    config.pbtxt
    1/
      model.onnx
  arcface/                   # Face embedding 512-d (FRS)
    config.pbtxt
    1/
      model.onnx
```

## Model sourcing

1. **yolov12m / scrfd** — convert TAO PeopleNet weights or use
   the Ultralytics export:
   ```bash
   pip install ultralytics
   yolo export model=yolo12m.pt format=onnx imgsz=640 dynamic=true
   ```
2. **arcface** — InsightFace `buffalo_l` ONNX:
   ```bash
   wget https://github.com/deepinsight/insightface/.../arcface_r100.onnx
   ```

Place ONNX file at `<model>/1/model.onnx` then `docker compose --profile
ai restart triton`. Triton validates config + auto-loads.

## Verifying

```bash
curl http://localhost:8000/v2/models/yolov12m/ready
# → 200 OK if model loaded successfully
```

## Note

Phase 4 ships `config.pbtxt` files. ONNX weights must be downloaded by
the operator (size + licensing) — not bundled in the image.
