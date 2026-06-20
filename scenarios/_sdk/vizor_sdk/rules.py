"""Zone / line / dwell rule engine for detect-track-rule scenarios.

Shared spatial-temporal plumbing for the scenarios that turn tracked boxes into
events. Pure-Python (numpy optional, not required), no external deps, fail-soft
— a bad or empty polygon makes `contains()` return False, never raises, so a
plugin degrades instead of crashing on operator-drawn garbage.

  * `point_in_polygon` / `bbox_center` — primitives.
  * `Zone`               — named polygon region            (PPE zone, Crowd area).
  * `LineCrossCounter`   — directional in/out tally line   (People In/Out).
  * `DwellTracker`       — continuous in-zone dwell timer   (Loitering).
  * `ZoneRuleEngine`     — many named Zones at once         (Crowd per-zone count).

Coordinates are whatever space the plugin feeds (pixels or normalised) — the
engine is unit-agnostic; just stay consistent within one scenario.
"""
from __future__ import annotations

from typing import Optional, Sequence

Point = tuple[float, float]
Bbox = Sequence[float]  # (x1, y1, x2, y2)


# ── Primitives ────────────────────────────────────────────────────────────────

def point_in_polygon(point: Point, polygon: list[Point]) -> bool:
    """Ray-casting point-in-polygon test. Returns False for a degenerate polygon
    (< 3 vertices) rather than raising — operators can draw bad shapes."""
    try:
        if not polygon or len(polygon) < 3:
            return False
        x, y = float(point[0]), float(point[1])
        inside = False
        n = len(polygon)
        j = n - 1
        for i in range(n):
            xi, yi = float(polygon[i][0]), float(polygon[i][1])
            xj, yj = float(polygon[j][0]), float(polygon[j][1])
            # Does a horizontal ray from (x, y) cross edge (j -> i)?
            intersects = ((yi > y) != (yj > y)) and (
                x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi)
            if intersects:
                inside = not inside
            j = i
        return inside
    except Exception:  # noqa: BLE001 — never let a rule check kill the worker
        return False


def bbox_center(bbox_xyxy: Bbox) -> Point:
    """Centroid of an (x1, y1, x2, y2) box. (0.0, 0.0) on malformed input."""
    try:
        x1, y1, x2, y2 = float(bbox_xyxy[0]), float(bbox_xyxy[1]), float(bbox_xyxy[2]), float(bbox_xyxy[3])
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
    except Exception:  # noqa: BLE001
        return (0.0, 0.0)


def _as_point(bbox_or_point: Bbox | Point) -> Point:
    """Accept either a 4-tuple bbox (use its center) or a 2-tuple point."""
    try:
        if len(bbox_or_point) >= 4:
            return bbox_center(bbox_or_point)
        return (float(bbox_or_point[0]), float(bbox_or_point[1]))
    except Exception:  # noqa: BLE001
        return (0.0, 0.0)


# ── Zone — PPE zone, Crowd area ────────────────────────────────────────────────

class Zone:
    """A named polygon region. Containment uses the bbox center so a person/object
    counts as "in" once their centroid is inside the drawn area."""

    def __init__(self, name: str, polygon: list[Point]):
        self.name = name
        # Coerce to a clean list of float pairs up-front; tolerate junk vertices.
        self.polygon: list[Point] = []
        try:
            for p in polygon or []:
                self.polygon.append((float(p[0]), float(p[1])))
        except Exception:  # noqa: BLE001
            self.polygon = []

    def contains(self, bbox_or_point: Bbox | Point) -> bool:
        """True if the bbox center (or raw point) falls inside the polygon. Empty
        or degenerate polygon -> always False, never raises."""
        return point_in_polygon(_as_point(bbox_or_point), self.polygon)


# ── LineCrossCounter — People In/Out ───────────────────────────────────────────

def _cross_sign(a: Point, b: Point, p: Point) -> float:
    """Sign of the cross product (b-a) x (p-a): which side of line a->b is p on?
    Positive = one side, negative = the other, ~0 = on the line."""
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


class LineCrossCounter:
    """Directional people counter for a single tripwire line (x1,y1)->(x2,y2).

    Feed each track's centroid every frame via `update(track_id, center)`. When a
    track's centroid flips from one side of the line to the other, we register one
    crossing and tally it as "in" (negative->positive side) or "out"
    (positive->negative). The first sighting of a track only seeds its side — no
    phantom count. `.in_count` / `.out_count` hold the running totals."""

    def __init__(self, p1: Point, p2: Point):
        self.p1 = (float(p1[0]), float(p1[1]))
        self.p2 = (float(p2[0]), float(p2[1]))
        self.in_count = 0
        self.out_count = 0
        self._last_side: dict[int, float] = {}  # track_id -> last cross sign

    def update(self, track_id: int, center: Point) -> Optional[str]:
        """Return "in"/"out" on a crossing event for this track, else None."""
        try:
            side = _cross_sign(self.p1, self.p2, (float(center[0]), float(center[1])))
        except Exception:  # noqa: BLE001
            return None
        prev = self._last_side.get(track_id)
        # On-line readings (~0) are ambiguous — hold the previous side, don't count.
        if abs(side) < 1e-9:
            return None
        cur = 1.0 if side > 0 else -1.0
        self._last_side[track_id] = cur
        if prev is None or prev == cur:
            return None  # first sighting, or no side change
        if cur > 0:  # crossed negative -> positive
            self.in_count += 1
            return "in"
        self.out_count += 1
        return "out"

    def forget(self, track_id: int) -> None:
        """Drop a track's remembered side (e.g. when its track dies)."""
        self._last_side.pop(track_id, None)

    def reset(self) -> None:
        self.in_count = 0
        self.out_count = 0
        self._last_side.clear()


# ── DwellTracker — Loitering ───────────────────────────────────────────────────

class DwellTracker:
    """Accumulates continuous time each track spends inside a zone, for loitering.

    Call `update(track_id, in_zone, now)` once per frame per track. While the
    track stays in-zone the dwell clock keeps adding wall-clock deltas; the moment
    it leaves, its timer resets to zero. `exceeded()` answers the loitering rule
    ("> threshold_s continuous"). `prune(now)` drops tracks not seen recently so
    the dict can't grow unbounded over a long-running stream."""

    def __init__(self, stale_after_s: float = 30.0):
        self._stale_after_s = stale_after_s
        # track_id -> (dwell_seconds, last_seen_now, was_in_zone)
        self._state: dict[int, tuple[float, float, bool]] = {}

    def update(self, track_id: int, in_zone: bool, now: float) -> float:
        """Update and return the track's current continuous dwell seconds."""
        try:
            now = float(now)
        except Exception:  # noqa: BLE001
            return 0.0
        dwell, last_seen, was_in = self._state.get(track_id, (0.0, now, False))
        if in_zone:
            if was_in:
                dwell += max(0.0, now - last_seen)  # extend continuous dwell
            else:
                dwell = 0.0  # just entered — start the clock fresh
            self._state[track_id] = (dwell, now, True)
            return dwell
        # Out of zone -> reset the continuous timer.
        self._state[track_id] = (0.0, now, False)
        return 0.0

    def dwell(self, track_id: int) -> float:
        """Current continuous dwell seconds for a track (0 if unknown)."""
        return self._state.get(track_id, (0.0, 0.0, False))[0]

    def exceeded(self, track_id: int, threshold_s: float) -> bool:
        """True if the track has dwelled continuously past the loitering threshold."""
        return self.dwell(track_id) >= float(threshold_s)

    def prune(self, now: float) -> None:
        """Drop tracks not seen within `stale_after_s` of `now`."""
        try:
            now = float(now)
        except Exception:  # noqa: BLE001
            return
        for tid in list(self._state.keys()):
            if now - self._state[tid][1] > self._stale_after_s:
                del self._state[tid]

    def forget(self, track_id: int) -> None:
        self._state.pop(track_id, None)


# ── ZoneRuleEngine — Crowd per-zone count ──────────────────────────────────────

class ZoneRuleEngine:
    """Convenience holder for multiple named Zones. Lets a crowd/PPE plugin ask
    "which zones is this point in?" and "how many of these centroids are in zone
    X?" without juggling Zone objects itself."""

    def __init__(self, zones: Optional[list[Zone]] = None):
        self.zones: dict[str, Zone] = {}
        for z in zones or []:
            self.zones[z.name] = z

    def add_zone(self, name: str, polygon: list[Point]) -> Zone:
        z = Zone(name, polygon)
        self.zones[name] = z
        return z

    def which_zones(self, point: Bbox | Point) -> list[str]:
        """Names of every zone whose polygon contains this point/bbox center."""
        return [name for name, z in self.zones.items() if z.contains(point)]

    def count_in_zone(self, zone_name: str, centers: list[Bbox | Point]) -> int:
        """Crowd count: how many of `centers` fall inside the named zone. Unknown
        zone -> 0, never raises."""
        z = self.zones.get(zone_name)
        if z is None:
            return 0
        return sum(1 for c in centers if z.contains(c))
