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
    point_in_zone,
    positive_evidence,
)
from .roi import build_roi, in_roi  # noqa: F401
