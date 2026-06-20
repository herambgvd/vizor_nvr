"""Per-camera ROI capture-zone gating for plate boxes.

The POC gated on the plate CENTER being inside an (x,y,w,h) capture zone. Here we
accept the NVR's per-camera ROI config (a normalised or pixel polygon, same shape
the PPE plugin uses) and test the plate-box center against it. No ROI configured
=> whole frame (always inside)."""
from __future__ import annotations

from typing import Any, Optional

try:
    import cv2
    import numpy as np
except Exception:  # noqa: BLE001
    cv2 = None
    np = None


def build_roi(roi_config: Any, frame_h: int, frame_w: int) -> Optional[Any]:
    """Build an (N,2) int32 polygon in current-frame pixels from a camera config.

    Accepts [[x,y],...] or [{"points":[[x,y],...]}] (first polygon used).
    Coordinates may be normalised (0..1) or pixel; a polygon whose max coord is
    <= 1.5 is treated as normalised and scaled to the frame. None => full-frame."""
    if not roi_config or np is None:
        return None
    poly = roi_config
    if isinstance(poly, list) and poly and isinstance(poly[0], dict):
        poly = poly[0].get("points") or poly[0].get("roi")
    if not poly or not isinstance(poly, list) or len(poly) < 3:
        return None
    try:
        arr = np.array(poly, dtype="float64")
    except Exception:  # noqa: BLE001
        return None
    if arr.ndim != 2 or arr.shape[1] != 2:
        return None
    if float(arr.max()) <= 1.5:
        arr[:, 0] *= frame_w
        arr[:, 1] *= frame_h
    return arr.astype("int32")


def plate_in_roi(plate_box, roi: Any) -> bool:
    """Plate counts as inside when its box CENTER is in the ROI (POC parity). No
    ROI => always inside."""
    if roi is None or cv2 is None:
        return True
    x1, y1, x2, y2 = plate_box
    cx, cy = float((x1 + x2) / 2), float((y1 + y2) / 2)
    return cv2.pointPolygonTest(roi, (cx, cy), False) >= 0
