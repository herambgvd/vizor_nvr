"""Age + gender prediction via FairFace (ResNet-34).

Ported verbatim from vizor-gpu ai_workers/frs/inference/fairface.py.
Model output: 18 logits — [0:7] race (ignored), [7:9] gender (0=Male,1=Female),
[9:18] age (9 buckets). Input 224×224 RGB ImageNet-normalised NCHW fp32.
"""
from __future__ import annotations

import os

import cv2
import numpy as np

FAIRFACE_SIZE = (224, 224)

AGE_BUCKET_LABELS = ["0-2", "3-9", "10-19", "20-29", "30-39", "40-49", "50-59", "60-69", "70+"]
_AGE_BUCKET_MID = [1, 6, 15, 25, 35, 45, 55, 65, 75]

_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def preprocess_fairface(crop: np.ndarray) -> np.ndarray:
    img = cv2.resize(crop, FAIRFACE_SIZE) if crop.shape[:2] != FAIRFACE_SIZE else crop
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    img = (img - _IMAGENET_MEAN) / _IMAGENET_STD
    img = img.transpose(2, 0, 1)
    return img[np.newaxis].astype(np.float32)


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max())
    return e / e.sum()


def postprocess_fairface(raw: np.ndarray) -> dict:
    """Return {gender, gender_confidence, age, age_range}."""
    out = np.asarray(raw, dtype=np.float32).flatten()
    if out.size < 18:
        return {"gender": None, "gender_confidence": 0.0, "age": None, "age_range": None}

    try:
        _male_idx = int(os.environ.get("FRS_FAIRFACE_MALE_INDEX", "0"))
    except ValueError:
        _male_idx = 0
    _male_idx = 0 if _male_idx not in (0, 1) else _male_idx
    try:
        _min_conf = float(os.environ.get("FRS_FAIRFACE_MIN_CONF", "0.65"))
    except ValueError:
        _min_conf = 0.65

    g_probs = _softmax(out[7:9])
    g_idx = int(np.argmax(g_probs))
    g_conf = float(g_probs[g_idx])
    if g_conf < _min_conf:
        gender, g_conf = None, 0.0
    else:
        gender = "male" if g_idx == _male_idx else "female"

    a_probs = _softmax(out[9:18])
    a_idx = int(np.argmax(a_probs))
    return {
        "gender": gender,
        "gender_confidence": g_conf,
        "age": _AGE_BUCKET_MID[a_idx],
        "age_range": AGE_BUCKET_LABELS[a_idx],
    }
