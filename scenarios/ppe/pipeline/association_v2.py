"""PPE→person association, ported from the AI-Powered PPE Detection System (the logic
that gave the accurate front-view results) and adapted to vizor's Detection API and
canonical labels.

Why this exists: vizor's original associate_ppe() matched a PPE box to a person when the
box CENTRE fell inside a loose body-zone band (helmet anywhere in the top 42% of a person
box). On crowded / overlapping scenes that cross-assigned a neighbour's helmet to a
bare-headed worker → false "compliant". This version scores each (person, item) pair by
IoU against a TIGHT body region + overlap + centre-distance + detection confidence, and
assigns the item to its single best-scoring person above a minimum score — so a helmet
only counts for the person whose head it actually sits on.

Labels are vizor-canonical: "Hardhat"/"Safety_Vest"/"Goggles"/"Boots" and the negatives
"NO_Hardhat"/"NO_Safety_Vest"/"NO_Goggles"/"NO_Boots".
"""
from __future__ import annotations

from .engine import Detection

# Which body region each canonical PPE label lives in.
_REGION_BY_LABEL = {
    "Hardhat": "head", "NO_Hardhat": "head",
    "Goggles": "head", "NO_Goggles": "head",
    "Safety_Vest": "torso", "NO_Safety_Vest": "torso",
    "gloves": "hands", "NO_gloves": "hands",
    "Boots": "feet", "NO_Boots": "feet",
}

_MIN_SCORE = 0.28          # AI-Powered ASSOCIATION_MIN_SCORE
_TEMPORAL_BONUS = 0.12     # AI-Powered TEMPORAL_ASSOC_BONUS


def _intersection_area(a, b) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def _iou(a, b) -> float:
    inter = _intersection_area(a, b)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return float(inter / union) if union > 0 else 0.0


def _center_distance_score(region, item) -> float:
    rx, ry = (region[0] + region[2]) / 2, (region[1] + region[3]) / 2
    ix, iy = (item[0] + item[2]) / 2, (item[1] + item[3]) / 2
    rw, rh = max(1.0, region[2] - region[0]), max(1.0, region[3] - region[1])
    d = (((rx - ix) / rw) ** 2 + ((ry - iy) / rh) ** 2) ** 0.5
    return float(max(0.0, 1.0 - d))


def body_region(box, region: str):
    """Tight body sub-box for a person (AI-Powered geometry). Head is a small band at
    the very top so a helmet must really sit on THIS person's head to associate."""
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if region == "head":
        return (x1 + 0.18 * w, y1, x2 - 0.18 * w, y1 + 0.28 * h)
    if region == "torso":
        return (x1 + 0.08 * w, y1 + 0.22 * h, x2 - 0.08 * w, y1 + 0.72 * h)
    if region == "hands":
        return (x1 - 0.05 * w, y1 + 0.25 * h, x2 + 0.05 * w, y1 + 0.78 * h)
    if region == "feet":
        return (x1 + 0.05 * w, y1 + 0.68 * h, x2 - 0.05 * w, y2)
    return box


def _score_pair(person: Detection, item: Detection, temporal_hit: bool) -> float:
    region = _REGION_BY_LABEL.get(item.label, "torso")
    region_box = body_region(person.box, region)
    region_iou = _iou(region_box, item.box)
    item_area = max(1.0, (item.box[2] - item.box[0]) * (item.box[3] - item.box[1]))
    person_overlap = _intersection_area(person.box, item.box) / item_area
    dist = _center_distance_score(region_box, item.box)
    bonus = _TEMPORAL_BONUS if temporal_hit else 0.0
    score = (0.42 * region_iou + 0.22 * person_overlap
             + 0.18 * dist + 0.10 * item.confidence + bonus)
    return float(min(score, 1.0))


def associate_v2(persons: list[Detection], items: list[Detection],
                 temporal_cache: dict | None = None,
                 camera_id: str = "") -> tuple[dict, dict]:
    """Assign each PPE item to its single best-scoring person (score >= _MIN_SCORE).

    Returns (linked, negatives):
      linked    : {track_id: {label: Detection}}   positive PPE per person
      negatives : {track_id: {label: Detection}}   NO_* PPE per person
    `temporal_cache` (optional) persists item→track assignments across frames for a small
    stability bonus; pass the same dict each frame to enable it.
    """
    linked: dict[int, dict[str, Detection]] = {}
    negatives: dict[int, dict[str, Detection]] = {}
    tc = temporal_cache if temporal_cache is not None else {}
    if not persons or not items:
        return linked, negatives

    for item in items:
        best_person = None
        best_score = 0.0
        key = _cache_key(camera_id, item)
        for person in persons:
            if person.track_id is None:
                continue
            hit = tc.get(key) == person.track_id
            s = _score_pair(person, item, hit)
            if s > best_score:
                best_score, best_person = s, person
        if best_person is None or best_score < _MIN_SCORE:
            continue
        tid = best_person.track_id
        bucket = negatives if item.label.startswith("NO_") else linked
        slot = bucket.setdefault(tid, {})
        cur = slot.get(item.label)
        if cur is None or item.confidence > cur.confidence:
            slot[item.label] = item
        tc[key] = tid
    return linked, negatives


def _cache_key(camera_id: str, item: Detection) -> str:
    if item.track_id is not None:
        return f"{camera_id}:{item.label}:tid:{item.track_id}"
    cx = (item.box[0] + item.box[2]) / 2
    cy = (item.box[1] + item.box[3]) / 2
    return f"{camera_id}:{item.label}:grid:{int(cx // 32)}:{int(cy // 32)}"
