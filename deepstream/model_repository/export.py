# =============================================================================
# Export ONNX weights into Triton model_repository tree.
#
#   yolov12m   → ultralytics yolov8m → ONNX (person detector, schema-aliased)
#   scrfd      → insightface buffalo_l/det_10g.onnx (face detector, anchor-free)
#   arcface    → insightface buffalo_l/w600k_r50.onnx (512-d embedding)
#
# yolov12m is an alias slot — config.pbtxt outer name stays stable so we can
# hot-swap real YOLOv12 weights later without changing DeepStream parsers.
# =============================================================================
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

OUT_ROOT = Path("/out")


def export_yolo(weights: str, dst: Path, imgsz: int = 640) -> None:
    from ultralytics import YOLO

    print(f">> exporting {weights} → {dst}", flush=True)
    model = YOLO(weights)
    onnx_path = model.export(format="onnx", imgsz=imgsz, opset=12, simplify=True, dynamic=False)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(onnx_path, dst)
    print(f"   wrote {dst} ({dst.stat().st_size // 1024} KB)", flush=True)


def _pull_buffalo_l(model_filename: str, dst: Path) -> None:
    """Trigger insightface buffalo_l download, then copy the requested
    sub-model ONNX into the Triton tree."""
    from insightface.app import FaceAnalysis

    print(f">> downloading insightface buffalo_l ({model_filename})", flush=True)
    # Only need the model bundle on disk — allowed_modules irrelevant for copy.
    FaceAnalysis(name="buffalo_l", allowed_modules=["detection", "recognition"]).prepare(ctx_id=-1)

    home = Path(os.environ.get("INSIGHTFACE_HOME", str(Path.home() / ".insightface")))
    candidates = list(home.rglob(model_filename))
    if not candidates:
        raise FileNotFoundError(f"{model_filename} not found under {home}")
    src = candidates[0]
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    print(f"   wrote {dst} ({dst.stat().st_size // 1024} KB)", flush=True)


def export_scrfd(dst: Path) -> None:
    _pull_buffalo_l("det_10g.onnx", dst)


def export_arcface(dst: Path) -> None:
    _pull_buffalo_l("w600k_r50.onnx", dst)


def main() -> int:
    targets = sys.argv[1:] or ["yolov12m", "scrfd", "arcface"]
    for t in targets:
        if t == "yolov12m":
            export_yolo("yolov8m.pt", OUT_ROOT / "yolov12m" / "1" / "model.onnx", imgsz=640)
        elif t == "scrfd":
            export_scrfd(OUT_ROOT / "scrfd" / "1" / "model.onnx")
        elif t == "arcface":
            export_arcface(OUT_ROOT / "arcface" / "1" / "model.onnx")
        else:
            print(f"unknown target: {t}", file=sys.stderr)
            return 2
    print("done.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
