"""Central ROI / bbox / line geometry helpers.

Single source of truth for the spatial primitives every scenario
needs. Existing scenario-local helpers
(`frs/inference/quality.py:point_in_polygon`,
`people_management/geometry.py:point_in_polygon`) duplicated this
logic with subtle differences in epsilon handling and ROI shape
parsing. New code should import from here; existing call sites will
migrate in Phase A3 follow-up edits.

## Conventions

- **Coordinates** — all polygon / line vertices are normalised to
  ``[0.0, 1.0]`` in image space. Bboxes are pixel-space `(x1, y1,
  x2, y2)`; the helpers below convert internally.
- **Polygon shape acceptance** — `roi_polygons` may be a list of
  bare point arrays (`[[x, y], ...]`) OR a list of dicts with a
  ``"points"`` key (`[{"points": [[x, y], ...], "label": "..."}]`).
  Both legacy and new frontends are supported.
- **Containment** — :func:`bbox_centroid_in_any_roi` uses the bbox
  centroid (operator-expected behaviour). Use
  :func:`bbox_corners_in_any_roi` only when you specifically need
  strict containment (e.g. safety-critical "person fully inside
  exclusion zone" semantics).
"""
from __future__ import annotations

import logging
from typing import Iterable, Sequence

logger = logging.getLogger("vizor.worker.geometry")

Point = tuple[float, float]


def normalise_polygon_list(roi_polygons: Iterable) -> list[list[tuple[float, float]]]:
    """Coerce the various persisted ROI shapes into a flat list of
    point arrays. Invalid entries silently dropped."""
    out: list[list[tuple[float, float]]] = []
    if not roi_polygons:
        return out
    for poly in roi_polygons:
        if poly is None:
            continue
        if isinstance(poly, dict):
            pts = poly.get("points") or []
        elif isinstance(poly, (list, tuple)):
            pts = poly
        else:
            continue
        norm: list[tuple[float, float]] = []
        for p in pts:
            try:
                norm.append((float(p[0]), float(p[1])))
            except (TypeError, ValueError, IndexError):
                continue
        if len(norm) >= 3:
            out.append(norm)
    return out


def point_in_polygon(px: float, py: float, polygon: Sequence[Point]) -> bool:
    """Ray-casting test in normalised coords. Half-open on y to avoid
    counting a shared vertex twice."""
    n = len(polygon)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > py) != (yj > py):
            x_intersect = (xj - xi) * (py - yi) / ((yj - yi) or 1e-12) + xi
            if px < x_intersect:
                inside = not inside
        j = i
    return inside


def bbox_centroid(bbox: Sequence[float]) -> tuple[float, float]:
    """Return `(cx, cy)` pixel-space centroid for `(x1, y1, x2, y2)`."""
    x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]
    return (float((x1 + x2) * 0.5), float((y1 + y2) * 0.5))


def bbox_centroid_in_any_roi(
    bbox: Sequence[float], fw: int, fh: int, roi_polygons: Iterable,
) -> bool:
    """True if the bbox centroid lies inside ANY of the polygons."""
    polys = normalise_polygon_list(roi_polygons)
    if not polys:
        return True
    cx_px, cy_px = bbox_centroid(bbox)
    if fw <= 0 or fh <= 0:
        return False
    cx_norm = cx_px / float(fw)
    cy_norm = cy_px / float(fh)
    return any(point_in_polygon(cx_norm, cy_norm, p) for p in polys)


def bbox_corners_in_any_roi(
    bbox: Sequence[float], fw: int, fh: int, roi_polygons: Iterable,
) -> bool:
    """True if ALL FOUR corners lie inside the SAME polygon. Strict
    containment — use only when the scenario requires the whole
    object inside the zone."""
    polys = normalise_polygon_list(roi_polygons)
    if not polys or fw <= 0 or fh <= 0:
        return False
    x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]
    corners = [
        (x1 / fw, y1 / fh),
        (x2 / fw, y1 / fh),
        (x2 / fw, y2 / fh),
        (x1 / fw, y2 / fh),
    ]
    for poly in polys:
        if all(point_in_polygon(cx, cy, poly) for cx, cy in corners):
            return True
    return False


def line_side(p: Point, a: Point, b: Point) -> float:
    """Signed cross product. >0 = left of A->B, <0 = right, 0 = on line."""
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def crossed_in_direction(
    prev: Point, cur: Point, a: Point, b: Point, direction_in: str,
) -> str | None:
    """Canonical line-crossing detector. See module docstring."""
    s_prev = line_side(prev, a, b)
    s_cur = line_side(cur, a, b)
    if s_prev == 0 and s_cur == 0:
        return None
    if (s_prev >= 0) == (s_cur >= 0):
        return None
    abx, aby = b[0] - a[0], b[1] - a[1]
    denom = abx * (cur[1] - prev[1]) - aby * (cur[0] - prev[0])
    if abs(denom) < 1e-12:
        return None
    t = ((prev[0] - a[0]) * (cur[1] - prev[1]) - (prev[1] - a[1]) * (cur[0] - prev[0])) / denom
    if t < 0 or t > 1:
        return None
    moved_to_b_side = s_cur < 0
    direction = (direction_in or "").lower()
    if direction == "b_to_a":
        return "in" if not moved_to_b_side else "out"
    return "in" if moved_to_b_side else "out"


def clamp_bbox_to_frame(
    bbox: Sequence[float], fw: int, fh: int,
) -> tuple[int, int, int, int]:
    """Clamp `(x1, y1, x2, y2)` to integer pixel coords inside the
    frame. Returns zero-area on degenerate input."""
    x1 = max(0, min(int(fw), int(bbox[0])))
    y1 = max(0, min(int(fh), int(bbox[1])))
    x2 = max(0, min(int(fw), int(bbox[2])))
    y2 = max(0, min(int(fh), int(bbox[3])))
    if x2 <= x1 or y2 <= y1:
        return (x1, y1, x1, y1)
    return (x1, y1, x2, y2)


def iou(a: Sequence[float], b: Sequence[float]) -> float:
    """Axis-aligned IoU."""
    ax1, ay1, ax2, ay2 = a[0], a[1], a[2], a[3]
    bx1, by1, bx2, by2 = b[0], b[1], b[2], b[3]
    ix1 = max(ax1, bx1); iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2); iy2 = min(ay2, by2)
    iw = max(0.0, ix2 - ix1); ih = max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    aa = max(0.0, (ax2 - ax1)) * max(0.0, (ay2 - ay1))
    bb = max(0.0, (bx2 - bx1)) * max(0.0, (by2 - by1))
    union = aa + bb - inter
    return float(inter / union) if union > 0 else 0.0
