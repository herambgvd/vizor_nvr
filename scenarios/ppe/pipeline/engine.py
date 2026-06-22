"""Person-level PPE compliance — the proven POC algorithm, ported VERBATIM.

This is the value of the plugin: temporal grace, evidence smoothing, stable-id
relinking across short occlusions, body-zone association, eligibility gating, and
per-track/per-PPE cooldown. The logic below is a faithful port of the validated
``run_video.py`` (ComplianceEngine, EvidenceSmoother, StableIdMapper,
associate_ppe, point_in_zone, deduplicate_persons, eligible_people,
positive_evidence, canonical_label, the Detection/PpeState dataclasses) — do NOT
re-derive or simplify it.

Two changes from the file version, both mechanical (not behavioural):
  * eligible_people takes explicit (frame_h, frame_w, gates) instead of an
    argparse Namespace.
  * positive_evidence takes an explicit no_hardhat_conf / negative_margin instead
    of args.

Detector inference is on Triton (inference/triton_engine.py); this module is the
pure stateful CPU logic that consumes Detection objects.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

# Body-zone rules: where (vertically, as a fraction of person height) a PPE item's
# centre must fall to belong to that person. Kept verbatim from the POC — the wide
# vest zone (0.10..0.95) was tuned to stop close/turned workers losing their vest.
DEFAULT_RULES: dict[str, tuple[float, float]] = {
    "Hardhat": (0.00, 0.42),
    "NO_Hardhat": (0.00, 0.42),
    "Safety_Vest": (0.10, 0.95),
}

# UI / config item name (lowercase) → canonical detector label used internally.
# The camera_config_schema multiselect speaks "helmet"/"vest"; the POC engine
# speaks "Hardhat"/"Safety_Vest".
ITEM_TO_CANONICAL: dict[str, str] = {
    "helmet": "Hardhat",
    "hardhat": "Hardhat",
    "vest": "Safety_Vest",
    "safety_vest": "Safety_Vest",
}
# Inverse, for operator-facing event payloads (report "helmet", not "Hardhat").
CANONICAL_TO_ITEM: dict[str, str] = {
    "Hardhat": "helmet",
    "Safety_Vest": "vest",
    "NO_Hardhat": "no_helmet",
    "NO_Safety_Vest": "no_vest",
}


def canonical_label(label: str) -> str:
    normalized = label.lower().replace("-", "_").replace(" ", "_")
    return {
        "person": "Person",
        "helmet": "Hardhat",
        "hardhat": "Hardhat",
        "vest": "Safety_Vest",
        "safety_vest": "Safety_Vest",
        "no_helmet": "NO_Hardhat",
        "no_hardhat": "NO_Hardhat",
        "no_vest": "NO_Safety_Vest",
        "no_safety_vest": "NO_Safety_Vest",
    }.get(normalized, label)


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    box: tuple[int, int, int, int]
    track_id: int | None = None


@dataclass
class PpeState:
    ever_seen: bool = False
    present_now: bool = False
    present_since: float | None = None
    missing_since: float | None = None
    violation: bool = False
    last_alert_at: float = -1e12


def point_in_zone(item: Detection, person: Detection, y_range: tuple[float, float]) -> bool:
    """Return whether an item's centre falls in a plausible zone of a person."""
    px1, py1, px2, py2 = person.box
    ix1, iy1, ix2, iy2 = item.box
    pw, ph = max(1, px2 - px1), max(1, py2 - py1)
    cx, cy = (ix1 + ix2) / 2, (iy1 + iy2) / 2
    # Small horizontal margin handles equipment that protrudes past the person box.
    return px1 - 0.12 * pw <= cx <= px2 + 0.12 * pw and py1 + y_range[0] * ph <= cy <= py1 + y_range[1] * ph


def associate_ppe(
    persons: list[Detection], items: list[Detection], rules: dict[str, tuple[float, float]]
) -> dict[int, dict[str, Detection]]:
    """Associate each PPE detection to the smallest compatible tracked person."""
    result: dict[int, dict[str, Detection]] = defaultdict(dict)
    for item in items:
        zone = rules.get(item.label)
        if not zone:
            continue
        candidates = [p for p in persons if p.track_id is not None and point_in_zone(item, p, zone)]
        if not candidates:
            continue
        person = min(candidates, key=lambda p: (p.box[2] - p.box[0]) * (p.box[3] - p.box[1]))
        current = result[person.track_id].get(item.label)
        if current is None or item.confidence > current.confidence:
            result[person.track_id][item.label] = item
    return result


def box_iou(first: tuple[int, int, int, int], second: tuple[int, int, int, int]) -> float:
    x1, y1 = max(first[0], second[0]), max(first[1], second[1])
    x2, y2 = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    first_area = max(0, first[2] - first[0]) * max(0, first[3] - first[1])
    second_area = max(0, second[2] - second[0]) * max(0, second[3] - second[1])
    return intersection / max(first_area + second_area - intersection, 1)


def deduplicate_persons(persons: list[Detection], threshold: float = 0.85) -> list[Detection]:
    """Hide duplicate end-to-end tracks for the same physical person."""
    kept: list[Detection] = []
    for person in sorted(persons, key=lambda item: item.confidence, reverse=True):
        if all(box_iou(person.box, old.box) < threshold for old in kept):
            kept.append(person)
    return kept


class ComplianceEngine:
    def __init__(
        self,
        required: list[str],
        missing_grace: float,
        min_present: float,
        cooldown: float,
        alert_initial_missing: bool,
    ) -> None:
        self.required = required
        self.missing_grace = missing_grace
        self.min_present = min_present
        self.cooldown = cooldown
        self.alert_initial_missing = alert_initial_missing
        self.states: dict[int, dict[str, PpeState]] = defaultdict(lambda: defaultdict(PpeState))
        self.last_seen: dict[int, float] = {}

    def update(self, track_id: int, present: dict[str, Detection], now: float) -> list[tuple[str, str]]:
        self.last_seen[track_id] = now
        events: list[tuple[str, str]] = []
        for ppe in self.required:
            state = self.states[track_id][ppe]
            if ppe in present:
                state.present_now = True
                if state.present_since is None:
                    state.present_since = now
                # PPE is being detected right now: never flag a worker who is wearing
                # it. Clearing the missing timer and violation immediately stops false
                # alerts when a worker crosses the zone faster than min_present, or
                # when detection blinks for a frame. min_present still gates the
                # REMOVED distinction below.
                state.missing_since = None
                state.violation = False
                if now - state.present_since >= self.min_present:
                    state.ever_seen = True
                continue

            state.present_now = False
            state.present_since = None
            if state.missing_since is None:
                state.missing_since = now
            missing_for = now - state.missing_since
            eligible = state.ever_seen or self.alert_initial_missing
            if eligible and missing_for >= self.missing_grace and not state.violation:
                state.violation = True
                if now - state.last_alert_at >= self.cooldown:
                    event = "PPE_REMOVED" if state.ever_seen else "PPE_MISSING"
                    events.append((event, ppe))
                    state.last_alert_at = now
        return events

    def purge(self, now: float, max_age: float = 10.0) -> None:
        for track_id, last in list(self.last_seen.items()):
            if now - last > max_age:
                self.last_seen.pop(track_id, None)
                self.states.pop(track_id, None)


@dataclass
class StableTrack:
    box: tuple[int, int, int, int]
    last_seen: float


class StableIdMapper:
    """Reconnect short-lived tracker IDs to recently seen physical workers."""

    def __init__(self, max_age: float = 3.0) -> None:
        self.max_age = max_age
        self.next_id = 1
        self.raw_to_stable: dict[int, int] = {}
        self.tracks: dict[int, StableTrack] = {}

    @staticmethod
    def center_distance(first: tuple[int, int, int, int], second: tuple[int, int, int, int]) -> float:
        first_cx, first_cy = (first[0] + first[2]) / 2, (first[1] + first[3]) / 2
        second_cx, second_cy = (second[0] + second[2]) / 2, (second[1] + second[3]) / 2
        distance = ((first_cx - second_cx) ** 2 + (first_cy - second_cy) ** 2) ** 0.5
        scale = max(first[3] - first[1], second[3] - second[1], 1)
        return distance / scale

    def update(self, persons: list[Detection], now: float) -> list[Detection]:
        assigned: set[int] = set()
        output: list[Detection] = []
        pending: list[Detection] = []

        # Preserve established raw-ID mappings first.
        for person in persons:
            assert person.track_id is not None
            stable_id = self.raw_to_stable.get(person.track_id)
            if stable_id is not None and stable_id not in assigned:
                assigned.add(stable_id)
                self.tracks[stable_id] = StableTrack(person.box, now)
                output.append(Detection(person.label, person.confidence, person.box, stable_id))
            else:
                pending.append(person)

        # A new raw ID may be the same worker after a short occlusion. Reconnect it
        # only when spatial evidence is plausible and that stable ID is free.
        for person in pending:
            candidates = []
            for stable_id, old in self.tracks.items():
                if stable_id in assigned or now - old.last_seen > self.max_age:
                    continue
                overlap = box_iou(person.box, old.box)
                distance = self.center_distance(person.box, old.box)
                if overlap >= 0.05 or distance <= 0.75:
                    candidates.append((2.0 * overlap - distance, stable_id))
            if candidates:
                _, stable_id = max(candidates)
            else:
                stable_id = self.next_id
                self.next_id += 1
            assert person.track_id is not None
            self.raw_to_stable[person.track_id] = stable_id
            assigned.add(stable_id)
            self.tracks[stable_id] = StableTrack(person.box, now)
            output.append(Detection(person.label, person.confidence, person.box, stable_id))

        expired = {stable_id for stable_id, track in self.tracks.items() if now - track.last_seen > self.max_age * 3}
        for stable_id in expired:
            self.tracks.pop(stable_id, None)
        if expired:
            self.raw_to_stable = {raw: stable for raw, stable in self.raw_to_stable.items() if stable not in expired}
        return output


class EvidenceSmoother:
    """Hold PPE evidence across frames so single-frame flicker cannot decide
    compliance. PPE is present only when seen in ≥ ``min_hits`` of the last
    ``window`` frames for that track+label; the best recent detection is kept so
    the engine still receives a confidence + box. Explicit negatives (NO_*) pass
    through unsmoothed — they gate positives elsewhere."""

    def __init__(self, window: int = 8, min_hits: int = 3) -> None:
        self.window = window
        self.min_hits = min_hits
        self.history: dict[int, dict[str, list[tuple[int, Detection]]]] = defaultdict(lambda: defaultdict(list))

    def update(self, track_id: int, observations: dict[str, Detection], frame_no: int) -> dict[str, Detection]:
        smoothed: dict[str, Detection] = {}
        track = self.history[track_id]
        seen_labels = set(observations) | set(track)
        for label in seen_labels:
            hits = track[label]
            if label in observations:
                hits.append((frame_no, observations[label]))
            # drop entries outside the sliding window
            hits[:] = [(fn, det) for fn, det in hits if frame_no - fn < self.window]
            if len(hits) >= self.min_hits:
                smoothed[label] = max(hits, key=lambda h: h[1].confidence)[1]
            if not hits:
                track.pop(label, None)
        # pass through explicit negatives unsmoothed (they gate positives elsewhere)
        for label, det in observations.items():
            if label.startswith("NO_"):
                smoothed[label] = det
        return smoothed

    def purge(self, active: set[int]) -> None:
        for track_id in list(self.history):
            if track_id not in active:
                self.history.pop(track_id, None)


def eligible_people(
    persons: list[Detection],
    frame_h: int,
    frame_w: int,
    min_person_height: int,
    min_foot_y: float,
    border_margin: int,
    max_aspect: float = 5.0,
    min_person_frac: float = 0.0,
) -> list[Detection]:
    """Suppress partial-edge tracks and camera artifacts from compliance decisions.

    `max_aspect` rejects absurdly tall+thin boxes (height/width) that the detector
    sometimes hallucinates as a 'person' on standing objects — a water bottle, a
    pole, a chair leg. A real standing/seated worker tops out around 4:1; a bottle
    runs much higher, so this drops the false person without touching real ones.

    `min_person_frac` (height as a fraction of the frame) drops far/small people —
    e.g. someone at a distant doorway — who are too low-res for reliable PPE
    detection and tend to produce false PPE (a plain shirt read as a vest)."""
    min_frac_px = min_person_frac * frame_h if min_person_frac > 0 else 0
    accepted = []
    for person in persons:
        x1, _y1, x2, y2 = person.box
        height = y2 - person.box[1]
        width = max(1, x2 - x1)
        aspect = height / width
        touches_edge = x1 <= border_margin or x2 >= frame_w - border_margin
        foot_too_high = y2 < min_foot_y * frame_h
        if (height >= min_person_height and height >= min_frac_px
                and not touches_edge and not foot_too_high and aspect <= max_aspect):
            accepted.append(person)
    return accepted


def positive_evidence(
    observations: dict[str, Detection], no_hardhat_conf: float, negative_margin: float
) -> dict[str, Detection]:
    """Resolve positive/explicit-negative helmet evidence for compliance state."""
    resolved = {label: detection for label, detection in observations.items() if label in {"Hardhat", "Safety_Vest"}}
    positive = resolved.get("Hardhat")
    negative = observations.get("NO_Hardhat")
    if negative and negative.confidence >= no_hardhat_conf and (
        positive is None or negative.confidence > positive.confidence * negative_margin
    ):
        resolved.pop("Hardhat", None)
    return resolved
