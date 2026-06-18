"""ByteTrack + Kalman face tracker — verbatim port of vizor-gpu's
ai_workers/frs/tracking/tracker.py (pure numpy, no behavioural change).

    tracker = ByteTracker(iou_threshold=0.08, max_age=120, high_thresh=0.4, low_thresh=0.1)
    results = tracker.update([(bbox_xyxy, confidence), ...])  # → [(track_id, bbox_xyxy), ...]

The worker tracks faces in detection order, so `assign_track_ids` adapts the
result back onto a per-detection list of ids (0 = unmatched)."""
from __future__ import annotations

import numpy as np


# ── Coordinate helpers ────────────────────────────────────────────────────────

def _xyxy_to_cxcywh(bbox: np.ndarray) -> np.ndarray:
    x1, y1, x2, y2 = bbox
    return np.array([(x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1], dtype=np.float64)


def _cxcywh_to_xyxy(cxcywh: np.ndarray) -> np.ndarray:
    cx, cy, w, h = cxcywh
    return np.array([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], dtype=np.float32)


# ── Kalman filter ─────────────────────────────────────────────────────────────

class _KalmanBoxFilter:
    """8-D Kalman filter for a single bounding-box track (constant velocity)."""

    _F = np.eye(8, dtype=np.float64)
    _F[:4, 4:] = np.eye(4)

    _H = np.zeros((4, 8), dtype=np.float64)
    _H[:4, :4] = np.eye(4)

    _Q = np.diag([1.0, 1.0, 1.0, 1.0, 0.25, 0.25, 0.10, 0.10]).astype(np.float64)
    _R = np.diag([1.0, 1.0, 10.0, 10.0]).astype(np.float64)
    _P0 = np.diag([10.0, 10.0, 10.0, 10.0, 1000.0, 1000.0, 500.0, 500.0]).astype(np.float64)

    def __init__(self, bbox_xyxy: np.ndarray):
        z = _xyxy_to_cxcywh(bbox_xyxy)
        self._x = np.array([z[0], z[1], z[2], z[3], 0, 0, 0, 0], dtype=np.float64)
        self._P = self._P0.copy()

    def predict(self) -> np.ndarray:
        self._x = self._F @ self._x
        self._P = self._F @ self._P @ self._F.T + self._Q
        self._x[2] = max(1.0, self._x[2])
        self._x[3] = max(1.0, self._x[3])
        return _cxcywh_to_xyxy(self._x[:4])

    def update(self, bbox_xyxy: np.ndarray) -> np.ndarray:
        z = _xyxy_to_cxcywh(bbox_xyxy)
        S = self._H @ self._P @ self._H.T + self._R
        K = self._P @ self._H.T @ np.linalg.inv(S)
        self._x = self._x + K @ (z - self._H @ self._x)
        self._P = (np.eye(8, dtype=np.float64) - K @ self._H) @ self._P
        self._x[2] = max(1.0, self._x[2])
        self._x[3] = max(1.0, self._x[3])
        return _cxcywh_to_xyxy(self._x[:4])

    @property
    def predicted_bbox(self) -> np.ndarray:
        return _cxcywh_to_xyxy(self._x[:4])


class _Track:
    __slots__ = ("bbox", "confidence", "age", "hits", "kalman")

    def __init__(self, bbox: np.ndarray, confidence: float):
        self.bbox = bbox.copy().astype(np.float32)
        self.confidence = confidence
        self.age = 0
        self.hits = 1
        self.kalman = _KalmanBoxFilter(bbox)


class ByteTracker:
    """ByteTrack-style tracker with per-track Kalman filter."""

    def __init__(self, iou_threshold: float = 0.08, max_age: int = 120,
                 high_thresh: float = 0.4, low_thresh: float = 0.1, **kwargs):
        self._iou_threshold = iou_threshold
        self._max_age = max_age
        self._high_thresh = high_thresh
        self._low_thresh = low_thresh
        self._next_id = 1
        self._tracks: dict[int, _Track] = {}

    def update(self, detections: list[tuple[np.ndarray, float]]) -> list[tuple[int, np.ndarray]]:
        if not detections:
            self._age_and_prune()
            return []

        det_boxes = np.array([d[0] for d in detections], dtype=np.float32)
        det_scores = np.array([d[1] for d in detections], dtype=np.float32)

        track_ids = list(self._tracks.keys())
        predicted_boxes = np.array(
            [self._tracks[tid].kalman.predict() for tid in track_ids], dtype=np.float32)
        for i, tid in enumerate(track_ids):
            self._tracks[tid].bbox = predicted_boxes[i]

        if not track_ids:
            return self._init_tracks(det_boxes, det_scores)

        high_mask = det_scores >= self._high_thresh
        low_mask = (~high_mask) & (det_scores >= self._low_thresh)
        high_idxs = np.where(high_mask)[0]
        low_idxs = np.where(low_mask)[0]

        matched_tracks: set[int] = set()
        matched_dets: set[int] = set()
        assignments: list[tuple[int, int]] = []

        if len(high_idxs) > 0:
            iou = _iou_matrix(predicted_boxes, det_boxes[high_idxs])
            a1, mt1, md1 = _greedy_match(iou, track_ids, high_idxs, self._iou_threshold)
            assignments.extend(a1)
            matched_tracks.update(mt1)
            matched_dets.update(md1)

        unmatched_track_idxs = [ti for ti, tid in enumerate(track_ids) if tid not in matched_tracks]
        if len(low_idxs) > 0 and unmatched_track_idxs:
            rem_boxes = predicted_boxes[unmatched_track_idxs]
            rem_ids = [track_ids[ti] for ti in unmatched_track_idxs]
            iou = _iou_matrix(rem_boxes, det_boxes[low_idxs])
            a2, mt2_local, md2 = _greedy_match(iou, rem_ids, low_idxs, self._iou_threshold)
            assignments.extend(a2)
            for local_ti in mt2_local:
                matched_tracks.add(unmatched_track_idxs[local_ti])
            matched_dets.update(md2)

        result: list[tuple[int, np.ndarray]] = []
        for tid, di in assignments:
            track = self._tracks[tid]
            updated = track.kalman.update(det_boxes[di])
            track.bbox = updated.astype(np.float32)
            track.age = 0
            track.hits += 1
            track.confidence = float(det_scores[di])
            result.append((tid, track.bbox))

        for di in range(len(det_boxes)):
            if di not in matched_dets and det_scores[di] >= self._high_thresh:
                tid = self._next_id
                self._next_id += 1
                self._tracks[tid] = _Track(det_boxes[di], float(det_scores[di]))
                result.append((tid, det_boxes[di]))

        assigned_tids = {tid for tid, _ in assignments}
        for tid in list(self._tracks.keys()):
            if tid not in matched_tracks and tid not in assigned_tids:
                self._tracks[tid].age += 1
                if self._tracks[tid].age > self._max_age:
                    del self._tracks[tid]

        return result

    def reset(self) -> None:
        self._tracks.clear()
        self._next_id = 1

    def _init_tracks(self, boxes: np.ndarray, scores: np.ndarray):
        result = []
        for i in range(len(boxes)):
            if scores[i] >= self._high_thresh:
                tid = self._next_id
                self._next_id += 1
                self._tracks[tid] = _Track(boxes[i], float(scores[i]))
                result.append((tid, boxes[i]))
        return result

    def _age_and_prune(self):
        for tid in list(self._tracks.keys()):
            self._tracks[tid].kalman.predict()
            self._tracks[tid].age += 1
            if self._tracks[tid].age > self._max_age:
                del self._tracks[tid]


def _iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    x1 = np.maximum(a[:, 0:1], b[:, 0].T)
    y1 = np.maximum(a[:, 1:2], b[:, 1].T)
    x2 = np.minimum(a[:, 2:3], b[:, 2].T)
    y2 = np.minimum(a[:, 3:4], b[:, 3].T)
    inter = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    union = area_a[:, None] + area_b[None, :] - inter + 1e-8
    return inter / union


def _greedy_match(iou_matrix, track_ids, det_indices, threshold):
    pairs = [(float(iou_matrix[ti, di]), ti, di)
             for ti in range(iou_matrix.shape[0])
             for di in range(iou_matrix.shape[1])]
    pairs.sort(key=lambda x: x[0], reverse=True)
    matched_track_ids: set = set()
    matched_det_local: set = set()
    matched_det_global: set = set()
    assignments = []
    for iou_val, ti, di in pairs:
        if ti in matched_track_ids or di in matched_det_local:
            continue
        if iou_val < threshold:
            break
        global_di = int(det_indices[di])
        assignments.append((track_ids[ti], global_di))
        matched_track_ids.add(track_ids[ti])
        matched_det_local.add(di)
        matched_det_global.add(global_di)
    return assignments, matched_track_ids, matched_det_global


def assign_track_ids(tracker: "ByteTracker", dets: list) -> list[int]:
    """Adapter for the worker: `dets` is a per-face list of (bbox_xyxy, conf).
    Runs the tracker and returns a parallel list of track ids (0 = unmatched),
    matching each input bbox to the tracker output by max IoU."""
    if not dets:
        tracker.update([])
        return []
    pairs = [(np.asarray(b, dtype=np.float32), float(c)) for b, c in dets]
    results = tracker.update(pairs)  # [(tid, bbox)]
    if not results:
        return [0] * len(dets)
    res_boxes = np.array([r[1] for r in results], dtype=np.float32)
    res_ids = [r[0] for r in results]
    in_boxes = np.array([p[0] for p in pairs], dtype=np.float32)
    iou = _iou_matrix(in_boxes, res_boxes)
    out = []
    for i in range(len(dets)):
        j = int(np.argmax(iou[i])) if iou.shape[1] else -1
        out.append(res_ids[j] if (j >= 0 and iou[i, j] > 0.3) else 0)
    return out
