"""ArcFace 112x112 alignment.

Ported from vizor-gpu ai_workers/frs/inference/align.py. 5-point affine warp to
the canonical ArcFace template, with an expanded center-crop fallback when
landmarks are unavailable. Pure OpenCV.

The YuNet landmark-fallback path from the source is dropped here — SCRFD already
emits 5-point landmarks for every detection, so the affine warp path is always
taken in practice; the center-crop fallback covers the no-landmark case.
"""
from __future__ import annotations

import cv2
import numpy as np

AF_SIZE = (112, 112)
AF_SRC_LANDMARKS = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)


def align_face(
    frame: np.ndarray,
    bbox: np.ndarray,
    landmarks: np.ndarray | None,
    fw: int,
    fh: int,
) -> np.ndarray:
    """Return 112x112 aligned face crop via affine warp to the ArcFace template."""
    if landmarks is not None and not np.all(landmarks == 0):
        M, _ = cv2.estimateAffinePartial2D(
            landmarks.astype(np.float32), AF_SRC_LANDMARKS, method=cv2.LMEDS,
        )
        if M is not None:
            return cv2.warpAffine(frame, M, AF_SIZE, borderValue=0)

    # Fallback: expanded center-crop → resize.
    x1, y1, x2, y2 = bbox.astype(float)
    bw, bh = x2 - x1, y2 - y1
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    side = max(bw, bh) * 1.3
    x1 = int(max(0, cx - side / 2))
    y1 = int(max(0, cy - side / 2))
    x2 = int(min(fw, cx + side / 2))
    y2 = int(min(fh, cy + side / 2))
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return np.zeros((*AF_SIZE, 3), dtype=np.uint8)
    return cv2.resize(crop, AF_SIZE)
