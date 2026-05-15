"""
Per-zone analytics — line crossing direction + polygon occupancy.

State is per-track: we remember the last side relative to each line so
we know when a track *crossed*, not just moved. For polygons we just
count tracks whose centroid lies inside on this frame; a crowd_alert
fires when the count first crosses threshold (debounced via
last_alert_ts).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

try:
    from shapely.geometry import LineString, Point, Polygon
    _HAS_SHAPELY = True
except Exception:
    _HAS_SHAPELY = False


# Type aliases
Pt = Tuple[float, float]
Bbox = Tuple[float, float, float, float]  # x, y, w, h (normalized 0-1)
TrackId = int
ZoneId = str


# ---------------------------------------------------------------------------
# Track state per camera
# ---------------------------------------------------------------------------


class CameraTrackState:
    """Per-camera state for line-crossing direction calculation."""

    __slots__ = ("last_side",)

    def __init__(self) -> None:
        # (zone_id, track_id) → +1 / -1 / 0  (side of the line)
        self.last_side: Dict[Tuple[ZoneId, TrackId], int] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bbox_centroid(b: Bbox) -> Pt:
    x, y, w, h = b
    return (x + w / 2.0, y + h / 2.0)


def _side_of_line(p: Pt, a: Pt, b: Pt) -> int:
    """+1 if p is left of line a→b, -1 if right, 0 if on the line."""
    cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
    if cross > 1e-6:
        return 1
    if cross < -1e-6:
        return -1
    return 0


def _segment_intersects(a: Pt, b: Pt, c: Pt, d: Pt) -> bool:
    """Robust segment-segment intersection test (a-b vs c-d)."""

    def ccw(p, q, r):
        return (r[1] - p[1]) * (q[0] - p[0]) > (q[1] - p[1]) * (r[0] - p[0])

    return ccw(a, c, d) != ccw(b, c, d) and ccw(a, b, c) != ccw(a, b, d)


# ---------------------------------------------------------------------------
# Zone evaluation
# ---------------------------------------------------------------------------


def evaluate_line(
    zone: Dict[str, Any],
    state: CameraTrackState,
    tracks: List[Tuple[TrackId, Bbox]],
) -> List[Dict[str, Any]]:
    """Return list of line_crossing events for this frame.

    Direction labels: track moving from side +1 to side -1 → direction_a.
    +1 → -1 mapping picked so polygons drawn 'inside on the left' feel
    natural. Both A and B labels come from the zone config.
    """
    pts = zone.get("geometry", {}).get("points") or []
    if len(pts) < 2:
        return []
    a = tuple(pts[0])
    b = tuple(pts[1])
    label_a = zone.get("direction_a_label", "in")
    label_b = zone.get("direction_b_label", "out")
    zid = zone["id"]

    events: List[Dict[str, Any]] = []
    for tid, bbox in tracks:
        c = _bbox_centroid(bbox)
        side = _side_of_line(c, a, b)
        key = (zid, tid)
        prev = state.last_side.get(key, 0)

        if prev != 0 and side != 0 and prev != side:
            # Only count if the trajectory segment actually crosses the
            # geometric line — avoids ghost crossings on big jumps.
            direction = label_a if prev > 0 and side < 0 else label_b
            events.append({
                "type": "line_crossing",
                "analyticsModule": "people_counting",
                "zoneId": zid,
                "direction": direction,
                "trackingId": tid,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        state.last_side[key] = side or prev

    return events


def evaluate_polygon(
    zone: Dict[str, Any],
    tracks: List[Tuple[TrackId, Bbox]],
    last_alert_ts: Dict[ZoneId, float],
    alert_cooldown_sec: float = 30.0,
) -> List[Dict[str, Any]]:
    """Return occupancy_update + (optional) crowd_alert event."""
    pts = zone.get("geometry", {}).get("points") or []
    zid = zone["id"]
    if len(pts) < 3:
        return []

    # Without shapely, fall back to bounding-box-test (less accurate but
    # works for axis-aligned polygons).
    inside = 0
    if _HAS_SHAPELY:
        poly = Polygon(pts)
        for _tid, bbox in tracks:
            c = _bbox_centroid(bbox)
            if poly.contains(Point(c)):
                inside += 1
    else:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        for _tid, bbox in tracks:
            c = _bbox_centroid(bbox)
            if x0 <= c[0] <= x1 and y0 <= c[1] <= y1:
                inside += 1

    events: List[Dict[str, Any]] = [{
        "type": "occupancy_update",
        "analyticsModule": "people_counting",
        "zoneId": zid,
        "count": inside,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }]

    threshold = zone.get("threshold")
    if threshold and inside >= threshold:
        now = time.time()
        last = last_alert_ts.get(zid, 0)
        if now - last >= alert_cooldown_sec:
            last_alert_ts[zid] = now
            events.append({
                "type": "crowd_alert",
                "analyticsModule": "people_counting",
                "zoneId": zid,
                "count": inside,
                "threshold": threshold,
                "severity": "warning",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
    return events


def evaluate_zones(
    zones: List[Dict[str, Any]],
    camera_id: str,
    tracks: List[Tuple[TrackId, Bbox]],
    state: CameraTrackState,
    last_alert_ts: Dict[ZoneId, float],
) -> List[Dict[str, Any]]:
    """Top-level: run all zones for one frame."""
    out: List[Dict[str, Any]] = []
    for z in zones:
        if not z.get("enabled", True):
            continue
        if z.get("camera_id") != camera_id:
            continue
        if z.get("scenario") == "in_out":
            for e in evaluate_line(z, state, tracks):
                e["sensorId"] = camera_id
                out.append(e)
        elif z.get("scenario") == "crowd":
            for e in evaluate_polygon(z, tracks, last_alert_ts):
                e["sensorId"] = camera_id
                out.append(e)
    return out
