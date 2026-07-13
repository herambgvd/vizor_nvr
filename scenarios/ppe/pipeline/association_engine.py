"""PPE→person association — client-proven POC logic (gvd_ppe_poc/utils/association_engine.py)
ported VERBATIM, adapted to the vizor Detection dataclass + vizor canonical labels.

Decides which PPE item belongs to which tracked person, turning raw detections into
worker-level PPE state. Pure geometry: body-region IoU + person overlap + center distance
+ confidence + temporal consistency. No Flask/torch/cv2.

Differences from the POC source (mechanical, NOT behavioural):
  * POC Detection has .canonical_class/.bbox/.conf/.center/.area; vizor Detection
    (pipeline.engine.Detection, frozen) has .label/.box/.confidence. We read those
    fields directly and compute center/area inline — identical maths.
  * POC labels are lowercase (person/helmet/no_helmet); vizor uses canonical labels
    (Person/Hardhat/Safety_Vest/NO_Hardhat/...). The region map + class sets below
    are the canonical equivalents. There is NO NO_Safety_Vest class in the model —
    vest is judged by absence in the compliance engine (same as the POC).
  * The vizor v2 association added a _HEAD_REGION_IOU_MIN gate; the POC has none, so we
    do NOT add it here (verbatim POC behaviour).

Scoring weights (0.42 region_iou / 0.22 person_overlap / 0.18 distance / 0.10 conf /
+0.12 temporal bonus), body-region geometry, ASSOCIATION_MIN_SCORE=0.28 and
TEMPORAL_ASSOC_BONUS=0.12 are the POC's exact values (config).
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

import config

from .engine import Detection

BBox = Tuple[float, float, float, float]

# Canonical person label + PPE / negative-PPE class sets (vizor canonical labels).
PERSON_LABEL = "Person"
PPE_CLASSES = {"Hardhat", "Safety_Vest", "Goggles", "Boots"}
NEGATIVE_PPE_CLASSES = {"NO_Hardhat", "NO_Safety_Vest", "NO_Goggles", "NO_Boots"}
# Map a canonical PPE label -> its negative counterpart, so the compliance engine can ask
# "is there a NO_x for this x?" (POC used the f"no_{ppe}" convention on lowercase labels).
NEG_OF: Dict[str, str] = {
    "Hardhat": "NO_Hardhat",
    "Safety_Vest": "NO_Safety_Vest",
    "Goggles": "NO_Goggles",
    "Boots": "NO_Boots",
}


def _bbox(d: Detection) -> BBox:
    return (float(d.box[0]), float(d.box[1]), float(d.box[2]), float(d.box[3]))


def _area(d: Detection) -> float:
    x1, y1, x2, y2 = _bbox(d)
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def _center(d: Detection) -> Tuple[float, float]:
    x1, y1, x2, y2 = _bbox(d)
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


@dataclass
class PersonAssociation:
    """A tracked person and the PPE (positive + negative) associated to them this frame."""

    person: Detection
    ppe: Dict[str, List[Detection]] = field(default_factory=lambda: defaultdict(list))
    negative_ppe: Dict[str, List[Detection]] = field(default_factory=lambda: defaultdict(list))
    scores: Dict[str, float] = field(default_factory=dict)

    def has_ppe(self, canonical_class: str) -> bool:
        return len(self.ppe.get(canonical_class, [])) > 0

    def has_negative(self, missing_class: str) -> bool:
        return len(self.negative_ppe.get(missing_class, [])) > 0


class AssociationEngine:
    """Assigns each PPE item to its best-scoring person (POC AssociationEngine)."""

    # Body region a PPE class must overlap to belong to a person (POC verbatim, canonical).
    BODY_REGION_BY_PPE = {
        "Hardhat": "head",
        "NO_Hardhat": "head",
        "Goggles": "head",
        "NO_Goggles": "head",
        "Safety_Vest": "torso",
        "NO_Safety_Vest": "torso",
        "Boots": "feet",
        "NO_Boots": "feet",
    }

    def __init__(self, camera_id: str):
        self.camera_id = camera_id
        # item cache-key -> person track_id it matched last frame (temporal bonus).
        self.temporal_cache: Dict[str, int] = {}
        self.history: Deque[Dict[str, int]] = deque(maxlen=30)

    def associate(self, detections: List[Detection]) -> List[PersonAssociation]:
        people = [d for d in detections if d.label == PERSON_LABEL]
        items = [d for d in detections
                 if d.label in PPE_CLASSES or d.label in NEGATIVE_PPE_CLASSES]

        associations = {p.track_id: PersonAssociation(person=p)
                        for p in people if p.track_id is not None}

        if not people or not items:
            return list(associations.values())

        frame_assignments: Dict[str, int] = {}

        for item in items:
            best_person: Optional[Detection] = None
            best_score = 0.0
            for person in people:
                score = self._score_pair(person, item)
                if score > best_score:
                    best_score = score
                    best_person = person

            if (best_person is not None and best_person.track_id is not None
                    and best_score >= config.ASSOCIATION_MIN_SCORE):
                pa = associations.get(best_person.track_id)
                if pa is None:
                    pa = PersonAssociation(best_person)
                    associations[best_person.track_id] = pa

                if item.label in NEGATIVE_PPE_CLASSES:
                    pa.negative_ppe[item.label].append(item)
                else:
                    pa.ppe[item.label].append(item)

                pa.scores[item.label] = max(
                    pa.scores.get(item.label, 0.0), round(best_score, 4))

                cache_key = self._cache_key(item)
                frame_assignments[cache_key] = best_person.track_id
                self.temporal_cache[cache_key] = best_person.track_id

        self.history.append(frame_assignments)
        return list(associations.values())

    def _score_pair(self, person: Detection, item: Detection) -> float:
        region_name = self.BODY_REGION_BY_PPE.get(item.label, "torso")
        region_box = self.body_region(_bbox(person), region_name)
        item_box = _bbox(item)

        region_iou = _iou(region_box, item_box)
        person_overlap = _intersection_area(_bbox(person), item_box) / max(_area(item), 1.0)
        distance_score = _normalized_center_distance_score(region_box, item_box)

        temporal_bonus = (config.TEMPORAL_ASSOC_BONUS
                          if self.temporal_cache.get(self._cache_key(item)) == person.track_id
                          else 0.0)

        score = (0.42 * region_iou + 0.22 * person_overlap + 0.18 * distance_score
                 + 0.10 * float(item.confidence) + temporal_bonus)
        return float(min(score, 1.0))

    def _cache_key(self, item: Detection) -> str:
        if item.track_id is not None:
            return f"{self.camera_id}:{item.label}:tid:{item.track_id}"
        cx, cy = _center(item)
        return f"{self.camera_id}:{item.label}:grid:{int(cx // 32)}:{int(cy // 32)}"

    @staticmethod
    def body_region(person_box: BBox, region: str) -> BBox:
        x1, y1, x2, y2 = person_box
        w, h = x2 - x1, y2 - y1
        if region == "head":
            return (x1 + 0.18 * w, y1, x2 - 0.18 * w, y1 + 0.28 * h)
        if region == "torso":
            return (x1 + 0.08 * w, y1 + 0.22 * h, x2 - 0.08 * w, y1 + 0.72 * h)
        if region == "hands":
            return (x1 - 0.05 * w, y1 + 0.25 * h, x2 + 0.05 * w, y1 + 0.78 * h)
        if region == "feet":
            return (x1 + 0.05 * w, y1 + 0.68 * h, x2 - 0.05 * w, y2)
        return person_box


def _intersection_area(a: BBox, b: BBox) -> float:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def _iou(a: BBox, b: BBox) -> float:
    inter = _intersection_area(a, b)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return float(inter / union) if union > 0 else 0.0


def _normalized_center_distance_score(region: BBox, item: BBox) -> float:
    rx = (region[0] + region[2]) / 2
    ry = (region[1] + region[3]) / 2
    ix = (item[0] + item[2]) / 2
    iy = (item[1] + item[3]) / 2
    rw = max(1.0, region[2] - region[0])
    rh = max(1.0, region[3] - region[1])
    norm_dist = (((rx - ix) / rw) ** 2 + ((ry - iy) / rh) ** 2) ** 0.5
    return float(max(0.0, 1.0 - norm_dist))
