"""ArcFace 112x112 alignment.

Ported from vizor-gpu ai_workers/frs/inference/align.py. 5-point affine warp to
the canonical ArcFace template; on missing/zero landmarks a YuNet detector
recovers landmarks before falling back to an expanded center-crop. Includes the
light NLM denoise the reference live pipeline applies before ArcFace.
"""
from __future__ import annotations

import os

import cv2
import numpy as np

AF_SIZE = (112, 112)
YUNET_MODEL_PATH = os.environ.get("FRS_YUNET_MODEL", "/models/yunet.onnx")
DENOISE_ALIGNED = os.environ.get("FRS_DENOISE_ALIGNED", "true").lower() in ("1", "true", "yes", "on")
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

    # No usable SCRFD landmarks → try YuNet to recover 5-point landmarks so we
    # still get a geometrically-aligned crop (profile / partial / low-light).
    yunet_lms = extract_landmarks_yunet(frame, bbox, fw, fh)
    if yunet_lms is not None:
        M, _ = cv2.estimateAffinePartial2D(
            yunet_lms.astype(np.float32), AF_SRC_LANDMARKS, method=cv2.LMEDS,
        )
        if M is not None:
            return cv2.warpAffine(frame, M, AF_SIZE, borderValue=0)

    # Last resort: expanded center-crop → resize (unaligned).
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


_yunet = None


def _get_yunet():
    """Lazily load YuNet CPU ONNX. Returns None if model missing."""
    global _yunet
    if _yunet is None:
        try:
            _yunet = cv2.FaceDetectorYN.create(YUNET_MODEL_PATH, "", (160, 160), 0.5, 0.3, 5000)
        except Exception:
            _yunet = False  # sentinel — don't retry each frame
    return _yunet if _yunet else None


def extract_landmarks_yunet(frame, bbox, fw, fh):
    """Run YuNet on an expanded face crop; return 5-point landmarks (frame coords)."""
    det = _get_yunet()
    if det is None:
        return None
    x1, y1, x2, y2 = bbox.astype(float)
    bw, bh = x2 - x1, y2 - y1
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    side = max(bw, bh) * 1.5
    cx1 = int(max(0, cx - side / 2)); cy1 = int(max(0, cy - side / 2))
    cx2 = int(min(fw, cx + side / 2)); cy2 = int(min(fh, cy + side / 2))
    crop = frame[cy1:cy2, cx1:cx2]
    if crop.size == 0:
        return None
    ch, cw = crop.shape[:2]
    det.setInputSize((cw, ch))
    try:
        _, faces = det.detect(crop)
    except Exception:
        return None
    if faces is None or len(faces) == 0:
        return None
    best = faces[np.argmax(faces[:, -1])]
    return np.array([
        [best[4] + cx1, best[5] + cy1], [best[6] + cx1, best[7] + cy1],
        [best[8] + cx1, best[9] + cy1], [best[10] + cx1, best[11] + cy1],
        [best[12] + cx1, best[13] + cy1],
    ], dtype=np.float32)


def denoise_face(face: np.ndarray) -> np.ndarray:
    """Light NLM denoise on the aligned 112x112 crop (matches reference live path)."""
    if face is None or face.size == 0 or not DENOISE_ALIGNED:
        return face
    try:
        return cv2.fastNlMeansDenoisingColored(face, None, 3, 3, 7, 21)
    except Exception:
        return face
