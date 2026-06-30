"""Shared PPE frame processor — the SINGLE place the full AI-Powered pipeline lives, so
the live camera worker and the video-upload job behave IDENTICALLY.

Per frame it does: detect → person filter (conf / eligibility / dedup) → ROI gate →
ByteTrack (AI-Powered params) + stable relink → Re-ID remap to a stable global identity →
tight-region association (associate_v2) + per-item compliance (ComplianceEngineV2) +
presence smoothing → event lifecycle (one incident per worker, create-then-upsert).

It owns the cross-frame state (tracker, stable mapper, re-id matcher + cache, presence
smoother, compliance engine, lifecycle) so the caller just feeds frames and emits/draws
from the returned actions. No DB / drawing / video I/O here.
"""
from __future__ import annotations

import os

import config

from .association_v2 import associate_v2  # noqa: F401
from .compliance_v2 import ComplianceEngineV2
from .engine import (
    Detection,
    StableIdMapper,
    deduplicate_persons,
    eligible_people,
)
from .event_lifecycle import EventLifecycle
from .process_v2 import PresenceSmoother, evaluate_frame
from .reid_matcher import ReIDMatcher, gid_to_int
from .roi import in_roi


def _reid_enabled() -> bool:
    return getattr(config, "PPE_REID", False)


class PPEProcessor:
    """Stateful per-source PPE pipeline. One instance per camera / per video job.

    required: canonical labels to enforce (e.g. ["Hardhat","Safety_Vest"]).
    item_floor: callable label -> confidence floor (per-camera UI sliders). When None a
                uniform floor is used.
    """

    def __init__(self, *, required, item_floor=None, missing_grace=None, cooldown=None,
                 camera_id: str = "", person_conf=None, min_person_frac=None):
        from vizor_sdk import ByteTracker
        self.required = list(required)
        self.item_floor = item_floor
        self.camera_id = camera_id
        # Per-camera eligibility gates from the UI sliders (shim config). Default to the
        # module constants when not supplied so behaviour is unchanged for callers that
        # don't pass them. Previously process() read config.PERSON_CONF /
        # config.MIN_PERSON_FRAC directly, so the per-camera sliders were DEAD.
        self.person_conf = (person_conf if person_conf is not None
                            else getattr(config, "PERSON_CONF", 0.20))
        self.min_person_frac = (min_person_frac if min_person_frac is not None
                                else getattr(config, "MIN_PERSON_FRAC", 0.05))
        grace = missing_grace if missing_grace is not None else getattr(
            config, "V2_MISSING_GRACE", 1.0)
        self.cooldown = cooldown if cooldown is not None else config.COOLDOWN

        # ByteTrack high_thresh = the confidence needed to START a new track. It MUST be
        # <= the person-detection floor (PERSON_CONF, default 0.20), otherwise low-confidence
        # people (night / far / dim cameras detect at ~0.2-0.4) never establish a track →
        # track_id stays 0 → they're skipped → NO events. The AI-Powered yaml's 0.45 was
        # tuned for a bright webcam and silently dropped every dim worker here. Default it
        # to PERSON_CONF so anything detected can also be tracked.
        _high = getattr(config, "PPE_TRACK_HIGH_THRESH", None)
        if _high is None:
            _high = min(getattr(config, "PERSON_CONF", 0.20), 0.30)
        self.tracker = ByteTracker(
            iou_threshold=getattr(config, "PPE_TRACK_MATCH_THRESH", 0.30),
            max_age=getattr(config, "PPE_TRACK_BUFFER", 150),
            high_thresh=_high,
            low_thresh=getattr(config, "PPE_TRACK_LOW_THRESH", 0.05))
        self.stable = StableIdMapper(getattr(config, "STABLE_ID_MAX_AGE", 12.0))
        self.engine = ComplianceEngineV2(self.required, grace, self.cooldown)
        # Presence smoothing driven by config, not hardcoded. A lower min_frac credits a
        # worn item that only detects intermittently (favours not falsely flagging).
        self.smoother = PresenceSmoother(
            window=int(getattr(config, "SMOOTH_WINDOW", 15)),
            min_frac=float(getattr(config, "PPE_PRESENCE_MIN_FRAC", 0.3)))
        self.lifecycle = EventLifecycle(
            enter_frames=getattr(config, "PPE_LIFECYCLE_ENTER_FRAMES", 3),
            expire_s=getattr(config, "PPE_LIFECYCLE_EXPIRE_S", 8.0),
            dup_cooldown_s=getattr(config, "PPE_LIFECYCLE_DUP_COOLDOWN_S", 30.0))
        self.temporal_cache: dict = {}

        # Re-ID (stable identity) — own extractor + matcher, fail-soft.
        self.reid = self.matcher = None
        self._reid_gid: dict = {}
        if _reid_enabled():
            try:
                from inference.reid_engine import ReIDExtractor
                self.reid = ReIDExtractor()
                self.reid.warmup()
                self.matcher = ReIDMatcher(config.PPE_REID_THRESHOLD,
                                           config.PPE_REID_HISTORY,
                                           config.PPE_REID_MAX_UNKNOWN)
            except Exception:  # noqa: BLE001
                self.reid = self.matcher = None

    def process(self, frame, now: float, roi, frame_w: int, frame_h: int):
        """Run one frame. Returns (persons, results, actions):
          persons: list[Detection] kept this frame (track_id = stable global id)
          results: {tid: {"fired","present","missing"}} from evaluate_frame
          actions: {tid: lifecycle action dict or None}  (create / update / None)
        The caller draws + emits from these (it owns snapshots, DB, video write)."""
        from vizor_sdk import assign_track_ids
        from inference.triton_engine import detector  # module singleton OK in caller thread

        detections = detector.detect(frame)
        all_persons, items = [], []
        for d in detections:
            if d.label == "Person":
                if d.confidence >= self.person_conf:
                    all_persons.append(d)
            else:
                items.append(d)

        persons = deduplicate_persons(
            eligible_people(all_persons, frame_h, frame_w, config.MIN_PERSON_HEIGHT,
                            config.MIN_FOOT_Y, config.BORDER_MARGIN,
                            config.MAX_PERSON_ASPECT, self.min_person_frac))
        if roi is not None:
            persons = [p for p in persons if in_roi(p, roi)]
        if not persons:
            self.engine.purge(now)
            self.lifecycle.purge(now)
            return [], {}, {}

        dets_for_track = [(list(p.box), float(p.confidence)) for p in persons]
        raw_ids = assign_track_ids(self.tracker, dets_for_track)
        raw_tracked = [Detection(p.label, p.confidence, p.box, rid)
                       for p, rid in zip(persons, raw_ids) if rid]
        if not raw_tracked:
            self.engine.purge(now)
            return [], {}, {}
        persons = self.stable.update(raw_tracked, now)

        # Re-ID remap → stable global identity.
        if self.reid is not None and self.matcher is not None:
            remapped = []
            for p in persons:
                if p.track_id is None:
                    remapped.append(p)
                    continue
                gid = self._reid_gid.get(p.track_id)
                if gid is None:
                    emb = self.reid.extract_person(frame, p.box)
                    g = self.matcher.match(emb, now) if emb is not None else None
                    gid = gid_to_int(g) if g else p.track_id
                    self._reid_gid[p.track_id] = gid
                remapped.append(Detection(p.label, p.confidence, p.box, gid))
            persons = remapped

        results = evaluate_frame(
            persons, items, self.engine, required=self.required, now=now,
            frame_w=frame_w, frame_h=frame_h, item_floor=self.item_floor,
            temporal_cache=self.temporal_cache, camera_id=self.camera_id,
            smoother=self.smoother)

        actions: dict = {}
        for person in persons:
            tid = person.track_id
            if tid is None:
                continue
            res = results.get(tid, {"fired": [], "present": set(), "missing": []})
            actions[tid] = self.lifecycle.update(
                tid, compliant=not bool(res["missing"]),
                missing=res["missing"], now=now)
        return persons, results, actions

    def set_event_id(self, tid, event_id: str) -> None:
        self.lifecycle.set_event_id(tid, event_id)

    def purge(self, now: float) -> None:
        self.engine.purge(now)
        self.lifecycle.purge(now)
