"""PPE Compliance config schema."""

from __future__ import annotations

from typing import List, Literal
from pydantic import BaseModel, Field


PPEItem = Literal["helmet", "vest", "mask", "gloves", "goggles", "boots"]


class PPEConfig(BaseModel):
    schema_version: int = 1
    enabled: bool = True

    # Items that MUST be present on a person inside the ROI
    required_items: List[PPEItem] = Field(default_factory=lambda: ["helmet", "vest"])

    # Confidence threshold for PPE classifier
    detection_confidence: float = Field(0.45, ge=0.05, le=0.95)

    # Violation grace — person must lack item for N consecutive frames
    # before raising a violation event (debounces flicker).
    violation_grace_frames: int = Field(15, ge=1, le=120)

    # ROI polygons (empty = whole frame). Coords normalized 0-1.
    rois: List[List[List[float]]] = Field(default_factory=list)

    # Snapshot every violation
    snapshot_violations: bool = True
