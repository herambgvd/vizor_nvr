"""Shared pipeline value types + the YOLO letterbox helper used by both Triton
detectors (plate + vehicle). Kept dependency-light so inference/ can import it
without pulling in the OCR / voting code."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

try:
    import cv2
    import numpy as np
except Exception:  # noqa: BLE001
    cv2 = None
    np = None


@dataclass
class Detection:
    """A single detection in ORIGINAL frame pixel coordinates.

    box is (x1, y1, x2, y2). label is the canonical class string (plate / car /
    truck / ...). track_id is filled later by the tracker (None until then)."""
    label: str
    confidence: float
    box: Tuple[int, int, int, int]
    track_id: Optional[int] = None


def letterbox(bgr, size: int):
    """Resize a BGR frame into a square `size`×`size` canvas, aspect-preserving,
    padded with grey (114). Returns (tensor[1,3,size,size] fp32 RGB, scale, pad_x,
    pad_y) where scale + pads invert the transform for box mapping. Verbatim from
    the PPE Triton detector so both detectors share one proven transform."""
    h, w = bgr.shape[:2]
    scale = min(size / max(1, w), size / max(1, h))
    new_w, new_h = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    resized = cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    pad_x = (size - new_w) // 2
    pad_y = (size - new_h) // 2
    canvas[pad_y:pad_y + new_h, pad_x:pad_x + new_w] = resized
    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    arr = rgb.astype(np.float32) / 255.0
    arr = np.transpose(arr, (2, 0, 1))[None, ...]  # [1,3,size,size]
    return arr, scale, pad_x, pad_y


def unletterbox_box(row, scale, pad_x, pad_y, frame_w, frame_h):
    """Invert letterbox for one [x1,y1,x2,y2] box (model space → frame pixels),
    clamped to the frame. Returns (x1,y1,x2,y2) ints or None if degenerate."""
    inv = 1.0 / scale if scale else 1.0
    x1, y1, x2, y2 = float(row[0]), float(row[1]), float(row[2]), float(row[3])
    ox1 = (x1 - pad_x) * inv
    oy1 = (y1 - pad_y) * inv
    ox2 = (x2 - pad_x) * inv
    oy2 = (y2 - pad_y) * inv
    bx1 = int(max(0, min(frame_w, ox1)))
    by1 = int(max(0, min(frame_h, oy1)))
    bx2 = int(max(0, min(frame_w, ox2)))
    by2 = int(max(0, min(frame_h, oy2)))
    if bx2 <= bx1 or by2 <= by1:
        return None
    return (bx1, by1, bx2, by2)
