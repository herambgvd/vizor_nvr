"""PPE compliance rule engine — client-proven POC logic
(gvd_ppe_poc/utils/compliance_engine.py) ported VERBATIM, adapted to the vizor
Detection dataclass + vizor canonical labels.

Converts PPE associations into violation decisions. The core is the temporal
confirmation: a required item is only reported missing when it is absent NOW *and*
was absent in >= PPE_CONFIRM_MIN_MISSING of the last PPE_CONFIRM_WINDOW observed
frames (6-of-8 by default). This kills single-frame association dropouts (a worker
turning sideways, a brief occlusion) — the mechanism that gives the POC its stable,
low-false-alarm vest/helmet alerts.

Differences from the POC source (mechanical, NOT behavioural):
  * Reads the vizor Detection fields (.confidence/.box) instead of POC .conf/.bbox.
  * required PPE + negative lookups use vizor canonical labels (Hardhat/Safety_Vest/
    Goggles/Boots and their NO_* counterparts). Vest has no NO_Safety_Vest class in
    the model, so it is judged by absence (has_positive == False) exactly like the POC.
  * The ReID global id is supplied per-track by the caller (vizor Detection is frozen
    and carries no metadata dict) via reid_lookup; temporal smoothing still keys on the
    ByteTrack/stable track_id, identical to the POC.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Deque, Dict, List, Optional

import config

from .association_engine import NEG_OF, PersonAssociation


@dataclass
class ComplianceRuleSet:
    mandatory_ppe: List[str]                 # canonical labels, e.g. ["Hardhat","Safety_Vest"]
    optional_ppe: List[str]
    min_person_confidence: float = 0.50

    @classmethod
    def from_camera_rules(cls, rules: Optional[Dict]) -> "ComplianceRuleSet":
        rules = rules or {}
        return cls(
            mandatory_ppe=rules.get("mandatory_ppe", ["Hardhat", "Safety_Vest"]),
            optional_ppe=rules.get("optional_ppe", ["Goggles", "Boots"]),
            min_person_confidence=float(
                rules.get("min_person_confidence", config.MIN_PERSON_CONFIDENCE)),
        )


class ComplianceEngine:
    """POC ComplianceEngine — temporal-confirmed per-item violation decisions."""

    def __init__(self, camera_rules: Optional[Dict] = None):
        self.rules = ComplianceRuleSet.from_camera_rules(camera_rules)
        # track_id -> ppe -> deque[bool]  (True = the item was missing that frame)
        self._ppe_history: Dict[object, Dict[str, Deque[bool]]] = {}
        self._track_last_seen: Dict[object, int] = {}
        self._frame_no: int = 0

    def _confirm_missing(self, track_id, ppe: str, missing_now: bool) -> bool:
        """Record this frame's observation and decide whether ``ppe`` should be
        reported missing for ``track_id`` right now — only when currently missing AND
        missing in >= PPE_CONFIRM_MIN_MISSING of the last PPE_CONFIRM_WINDOW frames."""
        window = max(1, config.PPE_CONFIRM_WINDOW)
        need = max(1, config.PPE_CONFIRM_MIN_MISSING)

        by_ppe = self._ppe_history.setdefault(track_id, {})
        hist = by_ppe.get(ppe)
        if hist is None or hist.maxlen != window:
            hist = deque(hist or (), maxlen=window)
            by_ppe[ppe] = hist
        hist.append(bool(missing_now))

        if not missing_now:
            return False
        return sum(hist) >= min(need, len(hist)) and len(hist) >= min(need, window)

    def _prune_history(self, active_tracks: set) -> None:
        for tid in active_tracks:
            self._track_last_seen[tid] = self._frame_no
        if len(self._ppe_history) <= 512:
            return
        stale = [tid for tid, seen in self._track_last_seen.items()
                 if self._frame_no - seen > 120]
        for tid in stale:
            self._ppe_history.pop(tid, None)
            self._track_last_seen.pop(tid, None)

    def evaluate(self, associations: List[PersonAssociation],
                 reid_lookup: Optional[Callable[[object], Optional[str]]] = None
                 ) -> List[Dict]:
        """Return the list of confirmed violation dicts (POC shape). reid_lookup maps a
        track_id -> stable ReID global id (or None); the caller supplies it since the
        frozen vizor Detection carries no metadata."""
        violations: List[Dict] = []
        self._frame_no += 1
        active_tracks: set = set()

        for assoc in associations:
            person = assoc.person

            if (float(person.confidence) < self.rules.min_person_confidence
                    or person.track_id is None):
                continue

            px1, py1, px2, py2 = person.box
            person_area = max(0.0, px2 - px1) * max(0.0, py2 - py1)
            if person_area < config.MIN_PERSON_BBOX_AREA:
                continue

            reid_global_id = reid_lookup(person.track_id) if reid_lookup else None

            # Temporal smoothing keys on the (stable) track_id, NOT the reid gid — the
            # gid can be absent on some frames and would flap the confirmation window.
            smooth_key = f"track_{person.track_id}"
            active_tracks.add(smooth_key)

            for ppe in self.rules.mandatory_ppe:
                negative_class = NEG_OF.get(ppe, f"NO_{ppe}")
                has_positive = assoc.has_ppe(ppe)
                has_negative = assoc.has_negative(negative_class)

                missing_now = has_negative or (not has_positive)

                if self._confirm_missing(smooth_key, ppe, missing_now):
                    confidence = self._violation_confidence(assoc, ppe, negative_class)
                    violations.append({
                        "track_id": person.track_id,
                        "reid_global_id": reid_global_id,
                        "camera_id": None,
                        "violation_type": f"missing_{ppe}",
                        "required_ppe": ppe,
                        "confidence": confidence,
                        "person_bbox": list(person.box),
                        "person_confidence": float(person.confidence),
                        "timestamp": datetime.utcnow().isoformat(),
                        "severity": self._severity_level(confidence),
                    })

        self._prune_history(active_tracks)
        return violations

    def _violation_confidence(self, assoc: PersonAssociation, ppe: str,
                              negative_class: str) -> float:
        if assoc.has_negative(negative_class):
            neg_conf = max([float(d.confidence)
                            for d in assoc.negative_ppe[negative_class]] or [0.75])
            return float(min(0.98, neg_conf + 0.10))

        person_conf = float(assoc.person.confidence)
        assoc_penalty = assoc.scores.get(ppe, 0.0)
        return float(max(0.45, min(0.82, person_conf - 0.10 + assoc_penalty * 0.2)))

    @staticmethod
    def _severity_level(confidence: float) -> str:
        if confidence >= 0.90:
            return "critical"
        if confidence >= 0.75:
            return "high"
        if confidence >= 0.60:
            return "medium"
        return "low"
