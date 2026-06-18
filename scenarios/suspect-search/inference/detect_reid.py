"""Triton-backed person/object detection (yolo26) + ReID embedding (person_reid).

Replaces the in-process onnxruntime sessions. Pre/post-processing is identical to
the prior runtime so detections + embeddings are unchanged — only the transport
moves to the shared Triton server.
"""
from __future__ import annotations

import io
from typing import Any

import numpy as np
from PIL import Image

from .triton_client import infer, model_ready

_DET_MODEL = "yolo26"
_DET_IN, _DET_OUT = "images", "output0"
_DET_HW = 640

_REID_MODEL = "person_reid"
_REID_IN, _REID_OUT = "input", "output"
_REID_HW = (256, 128)             # height, width


def detector_ready() -> bool:
    return model_ready(_DET_MODEL)


def reid_ready() -> bool:
    return model_ready(_REID_MODEL)


def detect(frame_bytes: bytes) -> tuple[list[np.ndarray] | None, tuple[int, int]]:
    """Run yolo26 → raw output tensor(s) + the (w,h) the model saw. Returns
    (outputs, size) or (None, size). Caller parses rows (keeps existing
    _parse_yolo_rows logic for class mapping / NMS)."""
    image = Image.open(io.BytesIO(frame_bytes)).convert("RGB")
    resized = image.resize((_DET_HW, _DET_HW))
    arr = np.asarray(resized).astype("float32") / 255.0
    arr = np.transpose(arr, (2, 0, 1))[None, ...]
    out = infer(_DET_MODEL, {_DET_IN: arr}, [_DET_OUT])
    if not out:
        return None, (_DET_HW, _DET_HW)
    return [out[_DET_OUT]], (_DET_HW, _DET_HW)


def reid_embedding(crop_bytes: bytes) -> list[float] | None:
    """Run person_reid → L2-normalised 768-d appearance embedding, or None."""
    h, w = _REID_HW
    image = Image.open(io.BytesIO(crop_bytes)).convert("RGB").resize((w, h))
    arr = np.asarray(image).astype("float32") / 255.0
    arr = np.transpose(arr, (2, 0, 1))[None, ...]
    out = infer(_REID_MODEL, {_REID_IN: arr}, [_REID_OUT])
    if not out:
        return None
    vec = np.asarray(out[_REID_OUT]).reshape(-1).astype("float32")
    norm = float(np.linalg.norm(vec)) or 1.0
    return [float(x / norm) for x in vec]
