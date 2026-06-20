"""Triton-backed plate detection (model ``anpr_plate``).

Thin client over the shared SDK TritonClient. Owns the YOLO pre/post-processing;
Triton runs the raw graph and batches across cameras:

  * preprocess: letterbox the BGR frame to 640×640 (aspect-preserving, grey pad),
    BGR→RGB, /255, HWC→CHW, add batch dim → fp32 [1,3,640,640].
  * infer: one call, input "images" → output "output0" [1,300,6]
    (x1,y1,x2,y2,score,class); single plate class, NMS baked into the graph.
  * postprocess: keep rows with score >= det_conf, UN-letterbox boxes back to the
    original frame pixels.

Returns a list of ``Detection(label="plate", ...)`` in ORIGINAL frame coordinates.
Fail-soft: returns [] on any inference failure (the POC's gating downstream).
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

import config
from pipeline.types import Detection, letterbox, unletterbox_box

logger = logging.getLogger(__name__)


class PlateDetector:
    """Stateless YOLO plate detector running on the shared Triton server."""

    def __init__(self) -> None:
        from vizor_sdk import TritonClient

        self.client = TritonClient(config.TRITON_URL)
        self.model = config.PLATE_MODEL_NAME
        self.input = config.PLATE_MODEL_INPUT
        self.output = config.PLATE_MODEL_OUTPUT
        self.imgsz = config.PLATE_MODEL_IMGSZ

    # ── readiness ──────────────────────────────────────────────────────────
    def ready(self) -> bool:
        return self.client.model_ready(self.model)

    def status(self) -> dict[str, Any]:
        return self.client.status({self.model: True})

    # ── detect ─────────────────────────────────────────────────────────────
    def detect(self, frame_bgr: np.ndarray, conf_thresh: float | None = None) -> list[Detection]:
        """Run anpr_plate on a BGR frame → list of plate Detection in ORIGINAL
        frame pixels. `conf_thresh` overrides the configured DET_CONF (per-camera)."""
        if frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
            return []
        thr = config.DET_CONF if conf_thresh is None else conf_thresh
        h, w = frame_bgr.shape[:2]
        try:
            tensor, scale, pad_x, pad_y = letterbox(frame_bgr, self.imgsz)
        except Exception as exc:  # noqa: BLE001
            logger.warning("anpr plate letterbox failed: %s", exc)
            return []
        out = self.client.infer_one(self.model, self.input, tensor, [self.output])
        if not out or self.output not in out:
            return []
        raw = np.asarray(out[self.output])
        if raw.ndim == 3:
            raw = raw[0]
        if raw.ndim != 2 or raw.shape[-1] < 6:
            return []
        dets: list[Detection] = []
        for row in raw:
            score = float(row[4])
            if score < thr:
                continue  # gate at det conf (POC default 0.6); also skips empty rows
            box = unletterbox_box(row, scale, pad_x, pad_y, w, h)
            if box is None:
                continue
            dets.append(Detection("plate", score, box, None))
        return dets


# Module-level singleton (lazy Triton connect inside TritonClient).
detector = PlateDetector()
