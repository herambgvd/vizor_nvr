"""Scenario-specific detection — the one place you call your Triton model.

Replace the body of `detect()` with your model's pre-processing, the Triton call
(via the SDK TritonClient), and post-processing. Return a list of Detection.
Everything else (frame pulling, tracking, events) is handled by the SDK + logic.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from vizor_sdk import TritonClient

from config.settings import config


@dataclass
class Detection:
    bbox: tuple[float, float, float, float]   # x1, y1, x2, y2
    confidence: float
    label: str = ""
    meta: dict = field(default_factory=dict)


# One shared Triton client for this plugin.
_triton = TritonClient(config.TRITON_URL)


def models_ready() -> bool:
    return _triton.all_ready(config.DETECTOR_MODEL)


def status() -> dict:
    return _triton.status({config.DETECTOR_MODEL: True})


def detect(frame_bgr: np.ndarray) -> list[Detection]:
    """Run the scenario model on one BGR frame and return detections.

    TEMPLATE STUB — replace with real pre/post-processing for your model.
    Example skeleton for a YOLO-style detector:

        tensor = preprocess(frame_bgr)                    # -> NCHW fp32
        out = _triton.infer_one(config.DETECTOR_MODEL, "images", tensor, ["output0"])
        if not out:
            return []
        boxes = postprocess(out["output0"], conf=config.MIN_CONFIDENCE)
        return [Detection(bbox=b.xyxy, confidence=b.score, label=b.cls) for b in boxes]
    """
    # Stub: no detections until a real model + pre/post is wired in.
    return []
