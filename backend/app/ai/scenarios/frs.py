"""Face Recognition System config schema."""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class FRSROI(BaseModel):
    """Polygon ROI inside which faces are detected. Coords normalized."""
    points: List[List[float]] = Field(..., min_length=3)


class FRSConfig(BaseModel):
    schema_version: int = 1

    enabled: bool = True

    # ROI — empty list = whole frame
    rois: List[FRSROI] = Field(default_factory=list)

    # Match threshold (cosine similarity 0-1) for recognition
    similarity_threshold: float = Field(0.55, ge=0.30, le=0.99)

    # Quality gates applied before embedding
    min_face_px: int = Field(80, ge=40, le=400)
    max_pose_deg: float = Field(30.0, ge=10.0, le=60.0)
    min_sharpness: float = Field(80.0, ge=10.0, le=500.0)
    liveness_required: bool = True

    # Groups whose detections should fire alerts (e.g. watchlist)
    alert_group_ids: List[str] = Field(default_factory=list)

    # Attendance tracking — register entries/exits
    attendance_enabled: bool = False
    # Camera role for attendance: entry/exit/both. Operator picks per cam.
    attendance_role: str = Field("both", pattern="^(entry|exit|both)$")

    # Crop padding ratio for emitted snapshots
    snapshot_pad: float = Field(0.25, ge=0.0, le=1.0)
