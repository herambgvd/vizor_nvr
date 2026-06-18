"""Photometric augmentation for enrollment.

Ported verbatim from vizor-gpu ai_workers/frs/inference/augment.py. Produces 6
variants per real photo (brightness ±25, contrast ×1.20 / ×0.85, gamma 0.8 / 1.2)
stored with `synthetic=True` in Qdrant so they boost recall without affecting the
user-visible photo count.
"""
from __future__ import annotations

import cv2
import numpy as np


def _clip(img: np.ndarray) -> np.ndarray:
    return np.clip(img, 0, 255).astype(np.uint8)


def generate_photometric_variants(aligned: np.ndarray) -> list[dict]:
    """Return a list of `{"image": np.ndarray, "tag": str}` — 6 deterministic variants."""
    variants: list[dict] = []

    variants.append({"image": _clip(aligned.astype(np.int16) + 25), "tag": "brighter"})
    variants.append({"image": _clip(aligned.astype(np.int16) - 25), "tag": "darker"})

    for alpha, tag in ((1.20, "contrast_hi"), (0.85, "contrast_lo")):
        adjusted = ((aligned.astype(np.float32) - 128.0) * alpha) + 128.0
        variants.append({"image": _clip(adjusted), "tag": tag})

    for gamma, tag in ((0.8, "gamma_lo"), (1.2, "gamma_hi")):
        inv = 1.0 / gamma
        lut = np.array([((i / 255.0) ** inv) * 255 for i in range(256)], dtype=np.uint8)
        variants.append({"image": cv2.LUT(aligned, lut), "tag": tag})

    return variants
