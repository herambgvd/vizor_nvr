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

    # Horizontal flip — face symmetry, boosts recall across yaw (vizor-app parity).
    variants.append({"image": cv2.flip(aligned, 1), "tag": "flip"})

    # Multi-scale crops — widen recall across distance (vizor-app parity:
    # INTER_CUBIC resize, BORDER_REFLECT_101 padding, pad = round(H*0.12)).
    H, W = aligned.shape[:2]
    m = round(H * 0.06)
    if H - 2 * m > 8 and W - 2 * m > 8:
        tight = aligned[m:H - m, m:W - m]
        variants.append({"image": cv2.resize(tight, (W, H), interpolation=cv2.INTER_CUBIC), "tag": "scale_tight"})
    pad = round(H * 0.12)
    loose = cv2.copyMakeBorder(aligned, pad, pad, pad, pad, cv2.BORDER_REFLECT_101)
    variants.append({"image": cv2.resize(loose, (W, H), interpolation=cv2.INTER_CUBIC), "tag": "scale_loose"})

    # Mild GEOMETRIC variants — synthesise the look of an angled / overhead camera
    # from a frontal enrolment photo, so a top-down CCTV view still matches without
    # the operator having to enrol that exact angle. Kept SMALL on purpose: large
    # warps would blur identity and cause cross-person false matches. A gentle
    # pitch-down perspective + a small in-plane tilt cover the common deviations a
    # ceiling/corner camera adds on top of what the affine alignment already removes.
    variants.extend(_geometric_variants(aligned, H, W))

    return variants


def _geometric_variants(aligned: np.ndarray, H: int, W: int) -> list[dict]:
    out: list[dict] = []
    border = cv2.BORDER_REFLECT_101

    # Small in-plane rotations (±8°) — roll the alignment leaves on tilted heads.
    for ang, tag in ((8.0, "rot_cw"), (-8.0, "rot_ccw")):
        M = cv2.getRotationMatrix2D((W / 2.0, H / 2.0), ang, 1.0)
        out.append({"image": cv2.warpAffine(aligned, M, (W, H), borderMode=border),
                    "tag": tag})

    # Gentle "looking-down" perspective — squeeze the top edge inward so the face
    # foreshortens like an overhead view. dx ~ 12% of width.
    dx = W * 0.12
    src = np.float32([[0, 0], [W, 0], [0, H], [W, H]])
    dst = np.float32([[dx, 0], [W - dx, 0], [0, H], [W, H]])
    Mp = cv2.getPerspectiveTransform(src, dst)
    out.append({"image": cv2.warpPerspective(aligned, Mp, (W, H), borderMode=border),
                "tag": "persp_down"})

    return out
