"""Direction + speed estimation (Milesight-parity features).

DIRECTION — a single tripwire line via the SDK LineCrossCounter. Operator draws
one line in the camera config; when a tracked vehicle's center crosses it we tag
the read "in" (negative->positive side) or "out". Direction is omitted if no line
is configured.

SPEED — HONEST ESTIMATE ONLY, single-camera, requires calibration. Two supported
calibrations (per camera, operator-entered):
  * two lines a known real-world distance apart: speed = distance_m / (t2 - t1)
    when the vehicle's center crosses line A then line B (km/h = m/s * 3.6).
  * one line + metres-per-pixel scale: speed from track displacement across the
    line region (less accurate — flagged as estimate).
If NO calibration is configured, speed is NOT computed (never faked). Even when
configured, single-camera speed is an ESTIMATE and depends on calibration
accuracy + the vehicle travelling roughly along the calibrated axis.

This module is a thin per-camera state holder keyed by track id; the worker feeds
it each frame and reads the result back when the track's session closes.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from vizor_sdk import LineCrossCounter


def _as_line(cfg) -> Optional[tuple]:
    """Parse a line config into ((x1,y1),(x2,y2)) in pixel space, or None.

    Accepts {"p1":[x,y],"p2":[x,y]} or [[x,y],[x,y]]; coords may be normalised
    (0..1) — scaled later by the worker which knows the frame size, OR pixel. We
    keep raw here and let the worker pass frame size to scale()."""
    if not cfg:
        return None
    try:
        if isinstance(cfg, dict):
            p1, p2 = cfg.get("p1"), cfg.get("p2")
        elif isinstance(cfg, (list, tuple)) and len(cfg) >= 2:
            p1, p2 = cfg[0], cfg[1]
        else:
            return None
        if not (p1 and p2):
            return None
        return ((float(p1[0]), float(p1[1])), (float(p2[0]), float(p2[1])))
    except Exception:  # noqa: BLE001
        return None


def _scale_point(pt, frame_w, frame_h):
    x, y = pt
    if 0.0 <= x <= 1.5 and 0.0 <= y <= 1.5:  # normalised
        return (x * frame_w, y * frame_h)
    return (x, y)


class MotionEstimator:
    """Per-camera direction + speed state. Built once per worker from its config."""

    def __init__(self, config: dict, frame_w: int, frame_h: int):
        self.frame_w = frame_w
        self.frame_h = frame_h
        self._direction: dict[int, str] = {}   # track_id -> last crossing direction
        self._speed: dict[int, float] = {}     # track_id -> estimated km/h

        # Direction line (also acts as line A for the 2-line speed calibration).
        line_a = _as_line(config.get("direction_line") or config.get("speed_line_a"))
        self._counter = None
        if line_a:
            p1 = _scale_point(line_a[0], frame_w, frame_h)
            p2 = _scale_point(line_a[1], frame_w, frame_h)
            self._counter = LineCrossCounter(p1, p2)
            self._line_a = (p1, p2)
        else:
            self._line_a = None

        # Speed calibration.
        self.speed_enabled = bool(config.get("speed_enabled"))
        self._line_b = None
        self._distance_m = None
        self._m_per_px = None
        if self.speed_enabled:
            line_b = _as_line(config.get("speed_line_b"))
            if line_b:
                self._line_b = (_scale_point(line_b[0], frame_w, frame_h),
                                _scale_point(line_b[1], frame_w, frame_h))
                self._counter_b = LineCrossCounter(*self._line_b) if self._line_b else None
            try:
                d = config.get("speed_distance_m")
                self._distance_m = float(d) if d not in (None, "") else None
            except (TypeError, ValueError):
                self._distance_m = None
            try:
                mpp = config.get("speed_m_per_px")
                self._m_per_px = float(mpp) if mpp not in (None, "") else None
            except (TypeError, ValueError):
                self._m_per_px = None
        # Two-line crossing timestamps per track for the distance/time estimate.
        self._cross_a_t: dict[int, float] = {}

    @property
    def has_direction(self) -> bool:
        return self._counter is not None

    def update(self, track_id: int, center) -> None:
        """Feed one frame's center for a track. Updates direction + (if calibrated)
        the speed estimate. `center` is a pixel (cx, cy)."""
        now = time.monotonic()
        if self._counter is not None:
            d = self._counter.update(track_id, center)
            if d:
                self._direction[track_id] = d
                # Two-line speed: record the time the vehicle crossed line A.
                if self.speed_enabled and self._line_b and self._distance_m:
                    self._cross_a_t[track_id] = now
        if self.speed_enabled and self._line_b and self._distance_m and getattr(self, "_counter_b", None) is not None:
            db = self._counter_b.update(track_id, center)
            if db and track_id in self._cross_a_t:
                dt = now - self._cross_a_t.pop(track_id)
                if dt > 0.05:  # ignore implausibly fast (same-frame) crossings
                    mps = self._distance_m / dt
                    self._speed[track_id] = round(mps * 3.6, 1)

    def direction_for(self, track_id: int) -> Optional[str]:
        return self._direction.get(track_id)

    def speed_for(self, track_id: int) -> Optional[float]:
        """Estimated km/h for a track, or None if uncalibrated / not measurable."""
        if not self.speed_enabled:
            return None
        return self._speed.get(track_id)

    def forget(self, track_id: int) -> None:
        self._direction.pop(track_id, None)
        self._speed.pop(track_id, None)
        self._cross_a_t.pop(track_id, None)
        if self._counter is not None:
            self._counter.forget(track_id)
        if getattr(self, "_counter_b", None) is not None:
            self._counter_b.forget(track_id)
