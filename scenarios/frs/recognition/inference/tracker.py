"""Lightweight IoU tracker.

The full vizor-gpu pipeline uses ByteTrack; this plugin samples frames at a low
FPS, so a simple greedy IoU matcher is enough to give detections a stable
track_id across consecutive frames — which is all the consensus voting needs.
Pure numpy, per-camera instance.
"""
from __future__ import annotations

import time


def _iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / ua if ua > 0 else 0.0


class IouTracker:
    def __init__(self, iou_threshold: float = 0.3, max_age: float = 3.0):
        self.iou_threshold = iou_threshold
        self.max_age = max_age           # seconds before a stale track is dropped
        self._tracks: dict[int, dict] = {}   # track_id -> {bbox, last_ts}
        self._next_id = 1

    def update(self, bboxes: list, now_ts: float | None = None) -> list[int]:
        """Assign a track_id to each bbox (list of [x1,y1,x2,y2]). Returns ids
        aligned to the input order."""
        now_ts = now_ts if now_ts is not None else time.time()
        # Drop stale tracks.
        for tid in [t for t, v in self._tracks.items() if now_ts - v["last_ts"] > self.max_age]:
            self._tracks.pop(tid, None)

        assigned: list[int] = []
        used: set[int] = set()
        for bbox in bboxes:
            best_id, best_iou = None, self.iou_threshold
            for tid, v in self._tracks.items():
                if tid in used:
                    continue
                score = _iou(bbox, v["bbox"])
                if score >= best_iou:
                    best_iou, best_id = score, tid
            if best_id is None:
                best_id = self._next_id
                self._next_id += 1
            self._tracks[best_id] = {"bbox": bbox, "last_ts": now_ts}
            used.add(best_id)
            assigned.append(best_id)
        return assigned
