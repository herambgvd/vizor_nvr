"""Persistent worker identity — client-proven POC TrackerManager
(gvd_ppe_poc/utils/tracker_manager.py) ported, adapted to vizor's Triton ReID + the
frozen vizor Detection dataclass.

Sits ON TOP of the raw ByteTrack ids (which vizor produces via
vizor_sdk.assign_track_ids in the processor) and attaches a STABLE global identity to
each person by appearance:
  * sparse embedding refresh — re-extract the OSNet embedding only every N frames
    (PPE_REID_EMBED_REFRESH, POC 15) and reuse the cached one otherwise;
  * embedding smoothing — 0.8*old + 0.2*new so a single noisy crop doesn't move the id;
  * temporary-unknown handling — a below-threshold match keeps the track's PREVIOUS
    global id (via ReIDMatcher.match_poc) instead of forking a new one;
  * fallback ids — when ByteTrack yields no id, reuse the nearest recent track (<60px)
    or mint a new fallback id, so a brief tracker gap doesn't drop the worker.

Differences from the POC source (mechanical, NOT behavioural):
  * The OSNet embedding comes from inference.reid_engine.ReIDExtractor (Triton, 768-d),
    not torchreid FeatureExtractor (local, 512-d). The matcher cosine is dimension-
    agnostic, so the logic is unchanged; only the embedding source differs.
  * vizor Detection is frozen and carries no .metadata dict, so the resolved global id
    per track is returned as a {track_id: gid} map instead of being written onto the
    detection. The processor uses that map for compliance/events.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Dict, List, Optional, Tuple

import numpy as np

import config

from .engine import Detection
from .reid_matcher import ReIDMatcher


@dataclass
class _TrackState:
    track_id: int
    bbox: Tuple[float, float, float, float]
    first_seen: float = field(default_factory=time)
    last_seen: float = field(default_factory=time)
    age_frames: int = 0
    reid_global_id: Optional[str] = None
    embedding: Optional[np.ndarray] = None
    reid_similarity: float = 0.0


class ReIDTracker:
    """POC TrackerManager over vizor's Triton ReID. Resolves each already-tracked
    person to a stable global identity, returning a {track_id -> gid} map."""

    def __init__(self, camera_id: str, extractor):
        self.camera_id = camera_id
        self.extractor = extractor                 # inference.reid_engine.ReIDExtractor
        self.matcher = ReIDMatcher(
            threshold=config.PPE_REID_THRESHOLD,
            history=config.PPE_REID_HISTORY,
            max_unknown_frames=config.PPE_REID_MAX_UNKNOWN)
        self.tracks: Dict[int, _TrackState] = {}
        self._next_fallback_id = 1_000_000
        self._refresh = max(1, int(getattr(config, "PPE_REID_EMBED_REFRESH", 15)))
        self._max_age = float(getattr(config, "PPE_REID_MAX_AGE_SECONDS", 12.0))

    def update(self, frame, persons: List[Detection]) -> Dict[int, str]:
        """persons: tracked Detection list (track_id set). Returns {track_id -> gid}."""
        now_wall = time()
        seen_ids: set = set()
        gid_map: Dict[int, str] = {}

        for det in persons:
            if det.label != "Person":
                continue
            tid = det.track_id
            if tid is None:
                tid = self._assign_fallback_id(det)
            seen_ids.add(tid)
            state = self.tracks.get(tid)

            # Person crop for the embedding.
            x1, y1, x2, y2 = (int(v) for v in det.box)
            h, w = frame.shape[:2]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            if x2 <= x1 or y2 <= y1:
                continue

            # Sparse embedding refresh (POC: only every N frames or when missing).
            embedding = None
            try:
                if state is None or state.age_frames % self._refresh == 0 or state.embedding is None:
                    embedding = self.extractor.extract_person(frame, det.box)
                else:
                    embedding = state.embedding
            except Exception:  # noqa: BLE001
                embedding = None

            # ReID match (POC match_poc: temporary_unknown keeps the previous identity).
            reid_result = None
            try:
                reid_result = self.matcher.match_poc(embedding, now_wall) if embedding is not None else None
            except Exception:  # noqa: BLE001
                reid_result = None

            reid_identity = "unknown"
            reid_sim = 0.0
            if reid_result is not None:
                reid_identity = reid_result.get("identity_id", "unknown")
                reid_sim = round(float(reid_result.get("similarity", 0.0)), 3)
                if reid_identity == ReIDMatcher.TEMPORARY_UNKNOWN:
                    reid_identity = state.reid_global_id if state is not None else "unknown"

            if state is None:
                self.tracks[tid] = _TrackState(
                    track_id=tid, bbox=det.box, reid_global_id=reid_identity,
                    embedding=embedding, reid_similarity=reid_sim)
            else:
                state.bbox = det.box
                state.last_seen = now_wall
                state.age_frames += 1
                # Embedding smoothing (POC 0.8*old + 0.2*new).
                if embedding is not None and state.embedding is not None:
                    try:
                        state.embedding = 0.8 * state.embedding + 0.2 * embedding
                    except Exception:  # noqa: BLE001
                        state.embedding = embedding
                elif embedding is not None:
                    state.embedding = embedding
                if reid_identity not in ("unknown", None):
                    state.reid_global_id = reid_identity
                state.reid_similarity = reid_sim

            gid = self.tracks[tid].reid_global_id
            if gid and gid != "unknown":
                gid_map[tid] = gid

        # Drop tracks unseen beyond 2x the max-age (POC).
        stale = [tid for tid, st in self.tracks.items()
                 if tid not in seen_ids and now_wall - st.last_seen > self._max_age * 2]
        for tid in stale:
            self.tracks.pop(tid, None)
        # Bound the matcher identity table by age too.
        try:
            self.matcher.purge(now_wall, max_age=self._max_age * 2)
        except Exception:  # noqa: BLE001
            pass

        return gid_map

    def _assign_fallback_id(self, det: Detection) -> int:
        x1, y1, x2, y2 = det.box
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        best_id, best_dist = None, float("inf")
        for tid, state in self.tracks.items():
            sx = (state.bbox[0] + state.bbox[2]) / 2.0
            sy = (state.bbox[1] + state.bbox[3]) / 2.0
            dist = ((cx - sx) ** 2 + (cy - sy) ** 2) ** 0.5
            if dist < best_dist and dist < 60:
                best_id, best_dist = tid, dist
        if best_id is not None:
            return best_id
        self._next_fallback_id += 1
        return self._next_fallback_id
