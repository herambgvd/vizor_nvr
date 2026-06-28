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

from .association_v2 import associate_v2
from .compliance_v2 import ComplianceEngineV2, NEG_LABEL  # noqa: F401


def evaluate_frame(persons, items, engine: ComplianceEngineV2, *,
                   required: list[str], now: float, frame_w: int, frame_h: int,
                   item_floor, temporal_cache: dict, camera_id: str = "",
                   edge_margin: int = 4):
    """Associate + judge one frame.

    Returns: dict track_id -> {
        "fired":   list[(event, label)],          # PPE_MISSING events this frame
        "present": set[label],                    # worn required items (positive seen)
        "missing": list[label],                   # required items not worn (canonical)
    }
    `engine` carries the per-track timers across frames; `temporal_cache` carries the
    association stability bonus across frames (pass the SAME dicts each frame).
    """
    # confidence-floor the PPE boxes (person boxes already filtered by the caller).
    items = [it for it in items if it.confidence >= item_floor(it.label)]
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
        fired = engine.update(tid, present_map, neg_map, now, evaluable=evaluable)
        present = {lbl for lbl in present_map if lbl in required}
        missing = [lbl for lbl in required
                   if lbl in evaluable and lbl not in present_map]
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
