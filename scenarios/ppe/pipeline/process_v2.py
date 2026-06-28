"""Shared per-frame PPE evaluation (v2 logic) used by BOTH the live worker and the
video-upload job, so they behave identically.

Given the tracked persons + raw PPE detections for one frame, it:
  1. filters PPE boxes by per-item confidence floor,
  2. associates them to persons with the AI-Powered tight-region IoU scorer
     (associate_v2 — fixes neighbour-helmet cross-assignment),
  3. runs the direct has-positive / has-negative compliance rule (ComplianceEngineV2)
     with missing-grace + cooldown,
  4. returns, per person, the fired events + the worn/missing item map for drawing.

The caller owns detection, tracking, ROI gating, snapshots, event emission and drawing —
this module is only the associate + judge core, so it stays free of I/O.
"""
from __future__ import annotations

from collections import deque

from .association_v2 import associate_v2
from .compliance_v2 import ComplianceEngineV2, NEG_LABEL  # noqa: F401


class PresenceSmoother:
    """Per-(track, item) sliding-window vote that absorbs single-frame detection blinks.
    An item counts as WORN when it was positively associated in >= `min_frac` of the last
    `window` frames the worker appeared — so a helmet that flickers off for a frame or two
    doesn't flip the worker to a violation (the source of compliant<->missing churn)."""

    def __init__(self, window: int = 8, min_frac: float = 0.4):
        self.window = window
        self.min_frac = min_frac
        self._hist: dict = {}      # (track_id, label) -> deque[0/1]

    def update(self, track_id, label: str, seen: bool) -> bool:
        key = (track_id, label)
        dq = self._hist.get(key)
        if dq is None:
            dq = deque(maxlen=self.window)
            self._hist[key] = dq
        dq.append(1 if seen else 0)
        return (sum(dq) / len(dq)) >= self.min_frac

    def purge(self, active: set) -> None:
        for key in [k for k in self._hist if k[0] not in active]:
            self._hist.pop(key, None)


def evaluate_frame(persons, items, engine: ComplianceEngineV2, *,
                   required: list[str], now: float, frame_w: int, frame_h: int,
                   item_floor=None, temporal_cache: dict, camera_id: str = "",
                   edge_margin: int = 4, conf_floor: float | None = None,
                   smoother: "PresenceSmoother | None" = None):
    """Associate + judge one frame.

    Returns: dict track_id -> {
        "fired":   list[(event, label)],          # PPE_MISSING events this frame
        "present": set[label],                    # worn required items (positive seen)
        "missing": list[label],                   # required items not worn (canonical)
    }
    `engine` carries the per-track timers across frames; `temporal_cache` carries the
    association stability bonus across frames (pass the SAME dicts each frame).
    Uses ONE uniform `conf_floor` for all PPE boxes (AI-Powered style, default 0.35) —
    the per-item `item_floor` callable is only used if conf_floor is None.
    """
    if conf_floor is None:
        try:
            import config
            conf_floor = config.V2_PPE_CONF
        except Exception:  # noqa: BLE001
            conf_floor = 0.35
    # confidence-floor the PPE boxes (person boxes already filtered by the caller).
    items = [it for it in items if it.confidence >= conf_floor]
    linked, negatives = associate_v2(persons, items, temporal_cache, camera_id)

    out: dict = {}
    for person in persons:
        tid = person.track_id
        if tid is None:
            continue
        present_map = linked.get(tid, {})
        neg_map = negatives.get(tid, {})
        # Only judge head items when the head is actually in-frame (box not at the very
        # top edge). Torso/feet items are always evaluable.
        evaluable = _evaluable(person.box, frame_h, required, edge_margin)
        # Smooth each required item's presence over a sliding window so a one/two-frame
        # helmet blink doesn't flip the worker (the compliant<->missing churn).
        if smoother is not None:
            worn = set()
            for lbl in required:
                if smoother.update(tid, lbl, lbl in present_map):
                    worn.add(lbl)
            present_for_rule = {lbl: present_map[lbl] for lbl in present_map if lbl in worn}
            for lbl in worn:
                present_for_rule.setdefault(lbl, present_map.get(lbl))
        else:
            present_for_rule = present_map
            worn = {lbl for lbl in present_map if lbl in required}
        fired = engine.update(tid, present_for_rule, neg_map, now, evaluable=evaluable)
        present = {lbl for lbl in worn if lbl in required}
        missing = [lbl for lbl in required
                   if lbl in evaluable and lbl not in present]
        out[tid] = {"fired": fired, "present": present, "missing": missing}
    return out


_HEAD = {"Hardhat", "Goggles"}


def _evaluable(box, frame_h: int, required: list[str], edge_margin: int) -> set:
    """Head items are skippable only when the head is cropped at the top frame edge."""
    _, y1, _, _ = box
    head_cut = y1 <= max(edge_margin, 0.02 * frame_h)
    out = set()
    for label in required:
        if label in _HEAD and head_cut:
            continue
        out.add(label)
    return out
