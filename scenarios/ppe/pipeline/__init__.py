"""PPE compliance pipeline — the ported POC stateful logic + ROI gating."""
from .engine import (  # noqa: F401
    CANONICAL_TO_ITEM,
    DEFAULT_RULES,
    ITEM_TO_CANONICAL,
    ComplianceEngine,
    Detection,
    EvidenceSmoother,
    StableIdMapper,
    associate_ppe,
    canonical_label,
    deduplicate_persons,
    eligible_people,
    evaluable_items,
    point_in_zone,
    positive_evidence,
)
from .roi import build_roi, in_roi  # noqa: F401
from .association_v2 import associate_v2, body_region  # noqa: F401
from .compliance_v2 import ComplianceEngineV2, ITEM_LABEL, NEG_LABEL  # noqa: F401
from .process_v2 import evaluate_frame, PresenceSmoother  # noqa: F401
from .reid_matcher import ReIDMatcher, gid_to_int  # noqa: F401
