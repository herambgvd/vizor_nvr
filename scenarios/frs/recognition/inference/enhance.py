"""Crop enhancement: pad → resize → denoise → sharpen.

Ported verbatim from vizor-gpu ai_workers/frs/inference/enhance.py. Pure
numpy/OpenCV. (Super-resolution is intentionally omitted — it was Triton-backed
and optional; ArcFace handles small faces acceptably without it.)
"""
from __future__ import annotations

import cv2
import numpy as np


def pad_bbox(bbox: np.ndarray, frame_w: int, frame_h: int, pad_ratio: float) -> np.ndarray:
    x1, y1, x2, y2 = [float(v) for v in bbox]
    w = x2 - x1
    h = y2 - y1
    dx = w * pad_ratio
    dy = h * pad_ratio
    nx1 = max(0.0, x1 - dx)
    ny1 = max(0.0, y1 - dy)
    nx2 = min(float(frame_w - 1), x2 + dx)
    ny2 = min(float(frame_h - 1), y2 + dy)
    return np.array([nx1, ny1, nx2, ny2], dtype=np.float32)


def crop_with_padding(frame: np.ndarray, bbox: np.ndarray, pad_ratio: float = 0.25) -> tuple[np.ndarray, np.ndarray]:
    h, w = frame.shape[:2]
    pb = pad_bbox(bbox, w, h, pad_ratio)
    x1, y1, x2, y2 = [int(round(v)) for v in pb]
    crop = frame[y1:y2, x1:x2]
    return crop, pb


def bicubic_resize_square(crop: np.ndarray, size: int = 224) -> np.ndarray:
    if crop.size == 0:
        return np.zeros((size, size, 3), dtype=np.uint8)
    h, w = crop.shape[:2]
    scale = size / max(h, w)
    nh, nw = int(round(h * scale)), int(round(w * scale))
    resized = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_CUBIC)
    canvas = np.zeros((size, size, 3), dtype=resized.dtype)
    oy = (size - nh) // 2
    ox = (size - nw) // 2
    canvas[oy:oy + nh, ox:ox + nw] = resized
    return canvas


def denoise(img: np.ndarray) -> np.ndarray:
    return cv2.fastNlMeansDenoisingColored(img, None, 5, 5, 7, 21)


def sharpen(img: np.ndarray, strength: float = 0.6) -> np.ndarray:
    blurred = cv2.GaussianBlur(img, (0, 0), sigmaX=1.2)
    return cv2.addWeighted(img, 1.0 + strength, blurred, -strength, 0)


def enhance_crop(
    frame: np.ndarray,
    bbox: np.ndarray,
    pad_ratio: float = 0.25,
    target_size: int = 224,
    do_denoise: bool = True,
    do_sharpen: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    """Full chain: pad → crop → resize → denoise → sharpen. Returns (enhanced, padded_bbox)."""
    crop, padded = crop_with_padding(frame, bbox, pad_ratio)
    resized = bicubic_resize_square(crop, target_size)
    if do_denoise:
        resized = denoise(resized)
    if do_sharpen:
        resized = sharpen(resized)
    return resized, padded
