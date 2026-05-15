"""People Counting + Crowd config schema."""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class PeopleCountingConfig(BaseModel):
    """Per-camera People Counting & Occupancy config.

    Zones live in `people_count_zones` table — this struct only carries
    camera-level toggles + detection thresholds. Zone CRUD goes through
    the dedicated zones router.
    """

    schema_version: int = 1

    # Master enable for this camera
    enabled: bool = True

    # Detection thresholds (passed to DeepStream nvinfer)
    detection_confidence: float = Field(0.35, ge=0.05, le=0.95)

    # Tracker dwell — frames a track must persist before counted
    min_track_frames: int = Field(4, ge=1, le=30)

    # Counting modes
    line_crossing_enabled: bool = True
    crowd_counting_enabled: bool = True

    # Optional rate limit on counts emit (per minute aggregation always
    # happens server-side regardless)
    emit_rate_hz: float = Field(1.0, ge=0.1, le=10.0)

    @field_validator("detection_confidence")
    @classmethod
    def round_conf(cls, v: float) -> float:
        return round(v, 2)
