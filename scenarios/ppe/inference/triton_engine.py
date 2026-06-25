"""Triton-backed PPE detection (model ``ppe_yolo26``).

Thin client over the shared SDK TritonClient. This module owns the YOLO
pre/post-processing — Triton runs the raw graph and batches across cameras:

  * preprocess: letterbox the BGR frame to 640×640 (aspect-preserving, grey pad),
    BGR→RGB, /255, HWC→CHW, add batch dim → fp32 [1,3,640,640].
  * infer: one call to the shared Triton server, input "images" → output "output0".
  * postprocess: decode [1,300,6] (x1,y1,x2,y2,score,class) rows, map the 11 class
    ids to canonical PPE labels, and UN-letterbox the boxes back to the original
    frame pixels (the inverse of the pad+scale applied in preprocess).

Output is a list of ``Detection`` (label, confidence, box, track_id=None) split by
the caller into persons vs PPE items — the same dataclass + canonical labels the
proven POC pipeline consumes, so the compliance logic is unchanged.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

import config
from pipeline.engine import Detection, canonical_label

logger = logging.getLogger(__name__)

# ppe_yolo26 class ids → raw model labels (then run through canonical_label()).
#   0=helmet 1=gloves 2=vest 3=boots 4=goggles 5=none 6=Person
#   7=no_helmet 8=no_goggle 9=no_gloves 10=no_boots
_CLASS_NAMES = {
    0: "helmet",
    1: "gloves",
    2: "vest",
    3: "boots",
    4: "goggles",
    5: "none",
    6: "Person",
    7: "no_helmet",
    8: "no_goggle",
    9: "no_gloves",
    10: "no_boots",
}


def _letterbox(bgr: np.ndarray, size: int) -> tuple[np.ndarray, float, int, int]:
    """Resize a BGR frame into a square `size`×`size` canvas, aspect-preserving,
    padded with grey (114). Returns (canvas_rgb_chw_batched, scale, pad_x, pad_y)
    where scale + pads invert the transform for box mapping."""
    import cv2

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


class PPEDetector:
    """Stateless YOLO PPE detector running on the shared Triton server."""

    def __init__(self) -> None:
        from vizor_sdk import TritonClient

        # Prefer gRPC (hard per-call timeout, no HTTP _post hang) when a gRPC URL is
        # configured — set by the worker-v2 path via TRITON_GRPC_URL + VIZOR_TRITON_GRPC.
        # Falls back to the HTTP URL + client for the legacy in-app path.
        import os
        grpc_url = os.environ.get("TRITON_GRPC_URL")
        if os.environ.get("VIZOR_TRITON_GRPC", "0").lower() in ("1", "true", "yes", "on") and grpc_url:
            self.client = TritonClient(grpc_url, grpc=True)
        else:
            self.client = TritonClient(config.TRITON_URL)
        self.model = config.PPE_MODEL_NAME
        self.input = config.PPE_MODEL_INPUT
        self.output = config.PPE_MODEL_OUTPUT
        self.imgsz = config.PPE_MODEL_IMGSZ

    # ── readiness ──────────────────────────────────────────────────────────
    def ready(self) -> bool:
        return self.client.model_ready(self.model)

    def status(self) -> dict[str, Any]:
        return self.client.status({self.model: True})

    # ── detect ─────────────────────────────────────────────────────────────
    def detect(self, frame_bgr: np.ndarray) -> list[Detection]:
        """Run ppe_yolo26 on a BGR frame → list of Detection in ORIGINAL frame
        pixel coordinates. Returns [] on any inference failure (fail-soft)."""
        if frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
            return []
        h, w = frame_bgr.shape[:2]
        try:
            tensor, scale, pad_x, pad_y = _letterbox(frame_bgr, self.imgsz)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ppe letterbox failed: %s", exc)
            return []
        out = self.client.infer_one(self.model, self.input, tensor, [self.output])
        if not out or self.output not in out:
            return []
        raw = np.asarray(out[self.output])
        # Expected [1,300,6]; tolerate [300,6] too.
        if raw.ndim == 3:
            raw = raw[0]
        if raw.ndim != 2 or raw.shape[-1] < 6:
            return []
        dets: list[Detection] = []
        inv = 1.0 / scale if scale else 1.0
        # The NMS-baked export pads the fixed 300 rows with very-low-score
        # detections (0.01–0.10). A floor below the lowest real per-class
        # threshold (no_hardhat 0.15) drops that noise so person tracking + PPE
        # association aren't polluted; per-class floors apply downstream.
        floor = config.DECODE_SCORE_FLOOR
        for row in raw:
            x1, y1, x2, y2, score, cls = (
                float(row[0]), float(row[1]), float(row[2]), float(row[3]),
                float(row[4]), int(round(float(row[5]))),
            )
            if score < floor:
                continue  # padded / empty / noise rows
            label = canonical_label(_CLASS_NAMES.get(cls, str(cls)))
            # Un-letterbox: subtract pad, divide by scale, clamp to frame.
            ox1 = (x1 - pad_x) * inv
            oy1 = (y1 - pad_y) * inv
            ox2 = (x2 - pad_x) * inv
            oy2 = (y2 - pad_y) * inv
            bx1 = int(max(0, min(w, ox1)))
            by1 = int(max(0, min(h, oy1)))
            bx2 = int(max(0, min(w, ox2)))
            by2 = int(max(0, min(h, oy2)))
            if bx2 <= bx1 or by2 <= by1:
                continue
            dets.append(Detection(label, score, (bx1, by1, bx2, by2), None))
        return dets

    def detect_crops(self, frame_bgr, persons, padding: float = 0.15) -> dict:
        """Second-stage PPE re-detection on per-person crops (the proven worker's
        detect_ppe_in_crops). Running the detector on an enlarged crop recovers
        small/distant PPE the full-frame pass misses, giving STEADY evidence
        instead of full-frame-only flicker. Returns {track_id: {label: Detection}}
        in ORIGINAL frame coordinates. PPE boxes are body-zone re-validated so a
        neighbour caught in the padded crop can't leak onto this track."""
        from pipeline.engine import point_in_zone, DEFAULT_RULES  # local import (cycle)

        out: dict = {}
        if not persons or frame_bgr is None:
            return out
        fh, fw = frame_bgr.shape[:2]
        for p in persons:
            tid = getattr(p, "track_id", None)
            if tid is None:
                continue
            x1, y1, x2, y2 = (int(v) for v in p.box)
            pw, ph = x2 - x1, y2 - y1
            cx1 = max(0, int(x1 - padding * pw)); cy1 = max(0, int(y1 - padding * ph))
            cx2 = min(fw, int(x2 + padding * pw)); cy2 = min(fh, int(y2 + padding * ph))
            crop = frame_bgr[cy1:cy2, cx1:cx2]
            if crop.size == 0:
                continue
            # detect() returns crop-local coords; shift back to full-frame.
            for d in self.detect(crop):
                bx1, by1, bx2, by2 = d.box
                item = Detection(d.label, d.confidence,
                                 (bx1 + cx1, by1 + cy1, bx2 + cx1, by2 + cy1), None)
                # Body-zone validate against THIS person (drops a neighbour's PPE).
                rule = DEFAULT_RULES.get(d.label)
                if rule is not None and not point_in_zone(item, p, rule):
                    continue
                prev = out.setdefault(tid, {}).get(d.label)
                if prev is None or item.confidence > prev.confidence:
                    out[tid][d.label] = item
        return out


# Module-level singleton (lazy Triton connect inside TritonClient).
detector = PPEDetector()
