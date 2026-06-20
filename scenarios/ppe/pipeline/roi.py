"""Per-camera ROI gating — a worker counts as inside the zone when its foot-point
(bottom-centre) is in the configured polygon. Ported from the POC's load_roi /
in_roi, adapted to the NVR's per-camera config (a normalised or pixel polygon
list) instead of a JSON file keyed by stream name.
"""
from __future__ import annotations

from typing import Any, Optional

try:
    import cv2
    import numpy as np
except Exception:  # noqa: BLE001
    cv2 = None
    np = None

from pipeline.engine import Detection


def build_roi(roi_config: Any, frame_h: int, frame_w: int) -> Optional[Any]:
    """Build an (N,2) int32 polygon in current-frame pixels from a camera config.

    Accepts:
      * [[x,y], ...]                          — single polygon
      * [{"points": [[x,y],...]}, ...]        — list-of-polygons (first used)
    Coordinates may be normalised (0..1) or pixel. A polygon whose max coord is
    ≤ 1.5 is treated as normalised and scaled to the frame. Returns None for no
    ROI (full-frame)."""
    if not roi_config or np is None:
        return None
    poly = roi_config
    # Unwrap list-of-polygons {points:[...]} → first polygon.
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
    # Normalised polygon → scale to pixels.
    if float(arr.max()) <= 1.5:
        arr[:, 0] *= frame_w
        arr[:, 1] *= frame_h
    return arr.astype("int32")


def in_roi(person: Detection, roi: Any) -> bool:
    """Person counts as inside when its foot-point (bottom-centre) is in the ROI."""
    if roi is None or cv2 is None:
        return True
    x1, _, x2, y2 = person.box
    foot = (float((x1 + x2) / 2), float(y2))
    return cv2.pointPolygonTest(roi, foot, False) >= 0
