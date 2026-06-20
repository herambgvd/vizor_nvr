"""Triton-backed vehicle detection + classification (model ``yolo26``).

REUSES the existing shared yolo26 model (COCO-ish classes) to attach a
vehicle_type to each plate read. yolo26 output is [1,300,6] like the plate model.
Per-COCO class ids: 2=car, 3=motorcycle, 5=bus, 7=truck (1=bicycle folded into
motorcycle for two-wheelers). Everything else maps to "other".

When a plate is read, `vehicle_type_for_plate` finds the vehicle box that best
encloses the plate box (the plate sits inside its vehicle) and returns that
vehicle's type. Fail-soft: returns None (vehicle_type omitted) on any failure, so
an unavailable / unready yolo26 never blocks a plate read.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

import config
from pipeline.types import Detection, letterbox, unletterbox_box

logger = logging.getLogger(__name__)

# COCO class id → canonical vehicle type. Two-wheelers (bicycle/motorcycle) both
# read as "motorcycle" for ANPR purposes (Milesight buckets two-wheelers together).
_COCO_VEHICLE = {
    1: "motorcycle",  # bicycle
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}


def _enclosure_ratio(inner, outer) -> float:
    """Fraction of `inner` (plate) box area covered by `outer` (vehicle) box. 1.0
    means the plate is fully inside the vehicle box."""
    ix1, iy1, ix2, iy2 = inner
    ox1, oy1, ox2, oy2 = outer
    iw = max(0, ix2 - ix1)
    ih = max(0, iy2 - iy1)
    iarea = iw * ih
    if iarea <= 0:
        return 0.0
    sx1, sy1 = max(ix1, ox1), max(iy1, oy1)
    sx2, sy2 = min(ix2, ox2), min(iy2, oy2)
    inter = max(0, sx2 - sx1) * max(0, sy2 - sy1)
    return inter / iarea


class VehicleClassifier:
    """Stateless YOLO vehicle detector on the shared Triton server."""

    def __init__(self) -> None:
        from vizor_sdk import TritonClient

        self.client = TritonClient(config.TRITON_URL)
        self.model = config.VEHICLE_MODEL_NAME
        self.input = config.VEHICLE_MODEL_INPUT
        self.output = config.VEHICLE_MODEL_OUTPUT
        self.imgsz = config.VEHICLE_MODEL_IMGSZ
        self.conf = config.VEHICLE_CONF

    @property
    def enabled(self) -> bool:
        return bool(self.model)

    def ready(self) -> bool:
        return bool(self.model) and self.client.model_ready(self.model)

    def status(self) -> dict[str, Any]:
        if not self.model:
            return {"enabled": False}
        return self.client.status({self.model: False})  # optional, not required

    def detect(self, frame_bgr: np.ndarray) -> list[Detection]:
        """Run yolo26 → list of vehicle Detection (car/motorcycle/bus/truck/other)
        in ORIGINAL frame pixels. Non-vehicle COCO classes are dropped."""
        if not self.model or frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
            return []
        h, w = frame_bgr.shape[:2]
        try:
            tensor, scale, pad_x, pad_y = letterbox(frame_bgr, self.imgsz)
        except Exception as exc:  # noqa: BLE001
            logger.warning("anpr vehicle letterbox failed: %s", exc)
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
            if score < self.conf:
                continue
            cls = int(round(float(row[5])))
            if cls not in _COCO_VEHICLE:
                continue  # not a vehicle class
            box = unletterbox_box(row, scale, pad_x, pad_y, w, h)
            if box is None:
                continue
            dets.append(Detection(_COCO_VEHICLE[cls], score, box, None))
        return dets

    def vehicle_type_for_plate(self, frame_bgr: np.ndarray, plate_box) -> Optional[str]:
        """Detect vehicles in the frame and return the type of the one best
        enclosing `plate_box`. None if no vehicle reasonably encloses the plate."""
        if not self.model:
            return None
        try:
            vehicles = self.detect(frame_bgr)
        except Exception:  # noqa: BLE001
            return None
        best_type, best_ratio = None, 0.0
        for v in vehicles:
            ratio = _enclosure_ratio(plate_box, v.box)
            if ratio > best_ratio:
                best_ratio, best_type = ratio, v.label
        # Require the plate to be mostly inside the vehicle box to trust the link.
        return best_type if best_ratio >= 0.5 else None


# Module-level singleton (lazy Triton connect inside TritonClient).
vehicle = VehicleClassifier()
