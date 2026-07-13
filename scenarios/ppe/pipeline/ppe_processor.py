"""Shared PPE frame processor — the SINGLE place the full pipeline lives, so the live
camera worker and the video-upload job behave IDENTICALLY.

This runs the CLIENT-PROVEN POC pipeline (gvd_ppe_poc) VERBATIM, on Triton inference:
  detect (Triton) → per-CATEGORY confidence gate (person 0.35 / PPE 0.50 / neg 0.50) →
  eligibility + dedup + ROI person-gate → raw ByteTrack ids (vizor_sdk, POC params) →
  ReIDTracker (stable global identity, 15-frame embed refresh, temporary-unknown) →
  AssociationEngine (tight body-region scoring) → ComplianceEngine (6-of-8 temporal
  confirm, min bbox area, per-track person-conf) → EventManager (OBSERVED→NEW→ACTIVE→
  RESOLVED→EXPIRED lifecycle) → emit ACTIONS.

It owns the cross-frame state and returns the SAME (persons, results, actions) contract
the shell (live/worker.py, live/video_job.py) already consumes, so persistence,
snapshots and drawing are unchanged. No DB / drawing / video I/O here.

results[tid] = {"present": set[canonical], "missing": [canonical], "fired": [(evt,label)]}
actions[tid] = {"action":"create","type":"violation","missing":[...]} on a new incident,
               {"action":"update", ...} while it continues, or None.
"""
from __future__ import annotations

import config

from .association_engine import AssociationEngine, NEG_OF
from .compliance_engine_poc import ComplianceEngine
from .engine import (
    Detection,
    deduplicate_persons,
    eligible_people,
)
from .event_manager import EventManager
from .reid_matcher import gid_to_int
from .reid_tracker import ReIDTracker
from .roi import in_roi

# UI item name (lowercase) → canonical detector label; used to map per-camera
# `required_items` (["helmet","vest"]) to canonical (["Hardhat","Safety_Vest"]).
from .engine import ITEM_TO_CANONICAL


def _reid_enabled() -> bool:
    return getattr(config, "PPE_REID", False)


class PPEProcessor:
    """Stateful per-source PPE pipeline (POC logic on Triton). One per camera / video job.

    required: canonical labels to enforce (e.g. ["Hardhat","Safety_Vest"]).
    item_floor: kept for API compatibility; the POC uses per-CATEGORY gates
                (PERSON_CONF / PPE_CONF / NEG_PPE_CONF) applied here, so per-item
                floors are not consulted in the ported path.
    """

    def __init__(self, *, required, item_floor=None, missing_grace=None, cooldown=None,
                 camera_id: str = "", person_conf=None, min_person_frac=None):
        from vizor_sdk import ByteTracker
        self.required = list(required)
        self.item_floor = item_floor
        self.camera_id = camera_id
        # Person detection gate + min-size eligibility. Per-camera UI sliders still flow
        # in via person_conf / min_person_frac; default to POC constants.
        self.person_conf = (person_conf if person_conf is not None
                            else getattr(config, "PERSON_CONF", 0.35))
        self.min_person_frac = (min_person_frac if min_person_frac is not None
                                else getattr(config, "MIN_PERSON_FRAC", 0.08))

        # ByteTrack with POC custom_bytetrack.yaml params (0.45 / 0.10 / 0.80 / 120).
        self.tracker = ByteTracker(
            iou_threshold=getattr(config, "PPE_TRACK_MATCH_THRESH", 0.80),
            max_age=getattr(config, "PPE_TRACK_BUFFER", 120),
            high_thresh=getattr(config, "PPE_TRACK_HIGH_THRESH", 0.45),
            low_thresh=getattr(config, "PPE_TRACK_LOW_THRESH", 0.10))

        # POC pure-logic engines. Compliance rules default to the required canonical set.
        self.assoc = AssociationEngine(camera_id)
        self.compliance = ComplianceEngine(
            camera_rules={"mandatory_ppe": self.required,
                          "min_person_confidence": getattr(config, "MIN_PERSON_CONFIDENCE", 0.50)})
        self.events = EventManager(camera_id)

        # Re-ID (stable identity) — Triton extractor + POC tracker, fail-soft.
        self.reid_tracker = None
        if _reid_enabled():
            try:
                from inference.reid_engine import ReIDExtractor
                extractor = ReIDExtractor()
                extractor.warmup()
                self.reid_tracker = ReIDTracker(camera_id, extractor)
            except Exception:  # noqa: BLE001
                self.reid_tracker = None

        # track_id -> event_key of the incident created for it, so a later "update"/
        # "create" action can be routed back to the same event row via the shell.
        self._tid_event_key: dict = {}

    def _negatives_present(self, assoc) -> set:
        return {lbl for lbl in assoc.negative_ppe if assoc.negative_ppe[lbl]}

    def process(self, frame, now: float, roi, frame_w: int, frame_h: int):
        """Run one frame. Returns (persons, results, actions) — see module docstring."""
        from vizor_sdk import assign_track_ids
        from inference.triton_engine import detector

        detections = detector.detect(frame)

        # Per-CATEGORY confidence gate (POC detector._parse_results): persons at
        # PERSON_CONF, positive PPE at PPE_CONF, negatives at NEG_PPE_CONF.
        ppe_conf = getattr(config, "PPE_CONF", 0.50)
        neg_conf = getattr(config, "NEG_PPE_CONF", 0.50)
        all_persons, items = [], []
        for d in detections:
            if d.label == "Person":
                if d.confidence >= self.person_conf:
                    all_persons.append(d)
            elif d.label.startswith("NO_"):
                if d.confidence >= neg_conf:
                    items.append(d)
            elif d.label == "none":
                continue
            else:
                if d.confidence >= ppe_conf:
                    items.append(d)

        persons = deduplicate_persons(
            eligible_people(all_persons, frame_h, frame_w, config.MIN_PERSON_HEIGHT,
                            config.MIN_FOOT_Y, config.BORDER_MARGIN,
                            config.MAX_PERSON_ASPECT, self.min_person_frac))
        if roi is not None:
            persons = [p for p in persons if in_roi(p, roi)]
        if not persons:
            self.events.purge(now)
            return [], {}, {}

        # Raw ByteTrack ids (POC-param tracker).
        dets_for_track = [(list(p.box), float(p.confidence)) for p in persons]
        raw_ids = assign_track_ids(self.tracker, dets_for_track)
        tracked = [Detection(p.label, p.confidence, p.box, rid)
                   for p, rid in zip(persons, raw_ids) if rid]
        if not tracked:
            self.events.purge(now)
            return [], {}, {}
        persons = tracked

        # ReID → stable global identity per track (POC TrackerManager). gid_map: tid -> gid.
        gid_map: dict = {}
        if self.reid_tracker is not None:
            gid_map = self.reid_tracker.update(frame, persons)

        def _reid_lookup(tid):
            return gid_map.get(tid)

        # Associate PPE to persons, then judge compliance (POC engines).
        associations = self.assoc.associate(persons + items)
        assoc_by_tid = {a.person.track_id: a for a in associations
                        if a.person.track_id is not None}
        violations = self.compliance.evaluate(associations, reid_lookup=_reid_lookup)

        # Lifecycle: turn confirmed violations into create/update actions per event key.
        ev_actions = self.events.update(violations, now)

        # Build the (results, actions) contract keyed by track_id (int the shell expects).
        results: dict = {}
        actions: dict = {}
        # Which required items each person is currently missing (from this frame's
        # violations) and which are present (associated positives).
        missing_by_tid: dict = {}
        for v in violations:
            missing_by_tid.setdefault(v["track_id"], []).append(v["required_ppe"])

        for person in persons:
            tid = person.track_id
            if tid is None:
                continue
            assoc = assoc_by_tid.get(tid)
            present = set()
            if assoc is not None:
                present = {lbl for lbl in assoc.ppe if assoc.ppe[lbl]}
            missing = missing_by_tid.get(tid, [])
            results[tid] = {"fired": [], "present": present, "missing": missing}

            # Route this track's event action (identity → event key).
            identity = gid_map.get(tid) or f"track_{tid}"
            act = None
            for vtype in (f"missing_{r}" for r in missing):
                key = (self.camera_id, identity, vtype)
                a = ev_actions.get(key)
                if a is None:
                    continue
                if a["action"] == "create":
                    self._tid_event_key[tid] = key
                    act = {"action": "create", "type": "violation",
                           "missing": missing, "_key": key}
                    break
                if a["action"] == "update" and act is None:
                    act = {"action": "update", "event_id": a["event_id"],
                           "obs_count": a["observation_count"],
                           "duration_s": a["duration_s"], "_key": key}
            actions[tid] = act

        self.events.purge(now)
        return persons, results, actions

    def set_event_id(self, tid, event_id: str) -> None:
        key = self._tid_event_key.get(tid)
        if key is not None:
            self.events.set_event_id(key, event_id)

    def purge(self, now: float) -> None:
        self.events.purge(now)
