"""Triton/ONNX pre/post-processing for FRS models.

Ported verbatim from vizor-gpu ai_workers/frs/inference/preprocess.py. Pure
numpy/OpenCV — no inference-client coupling.
"""
from __future__ import annotations

import os

import cv2
import numpy as np


# ── AntiSpoofing ─────────────────────────────────────────────────────────────

AS_SIZE = (80, 80)
AS_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
AS_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

# MiniFASNet / Silent-Face anti-spoof export: classes {0: 2D-fake, 1: live,
# 2: 3D-fake}. Live class is index 1. Override per-deploy via FRS_LIVE_CLASS_INDEX.
try:
    AS_LIVE_INDEX = int(os.environ.get("FRS_LIVE_CLASS_INDEX", "1"))
except ValueError:
    AS_LIVE_INDEX = 1


def preprocess_antispoofing(crop: np.ndarray) -> np.ndarray:
    img = cv2.resize(crop, AS_SIZE).astype(np.float32) / 255.0
    img = (img - AS_MEAN) / AS_STD
    img = img.transpose(2, 0, 1)
    return img[np.newaxis].astype(np.float32)


def postprocess_antispoofing(raw_output: np.ndarray) -> float:
    """Softmax over the flattened output; return the live-class probability."""
    scores = _softmax(raw_output.flatten())
    idx = AS_LIVE_INDEX if 0 <= AS_LIVE_INDEX < scores.size else scores.size - 1
    return float(scores[idx])


# ── ArcFace ──────────────────────────────────────────────────────────────────

ARCFACE_SIZE = (112, 112)


def preprocess_arcface(aligned: np.ndarray) -> np.ndarray:
    """(112,112,3) BGR uint8 → (1,3,112,112) FP32 in [-1, 1]."""
    img = aligned.astype(np.float32)
    img = (img - 127.5) / 128.0
    img = img.transpose(2, 0, 1)
    return img[np.newaxis].astype(np.float32)


def postprocess_arcface(raw_output: np.ndarray) -> np.ndarray:
    """Return L2-normalised 512-d embedding."""
    embedding = raw_output.flatten().astype(np.float32)
    norm = float(np.linalg.norm(embedding))
    if norm > 0:
        embedding = embedding / norm
    return embedding


# ── Utilities ────────────────────────────────────────────────────────────────

def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - np.max(x))
    return e / e.sum()


def normalize_embedding(emb: np.ndarray) -> np.ndarray:
    arr = np.asarray(emb, dtype=np.float32).flatten()
    n = float(np.linalg.norm(arr))
    return arr / n if n > 0 else arr
