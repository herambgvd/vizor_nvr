"""Standard scenario event schema — one shape every plugin emits, so the NVR
alarm dock + events module render any scenario uniformly.

A scenario produces an event when something fires: a face matched, a line was
crossed, a gun appeared, dwell-time exceeded. The fields below are the common
denominator; scenario-specific data goes in `meta`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

try:
    from pydantic import BaseModel, Field
    _HAS_PYDANTIC = True
except Exception:  # noqa: BLE001
    _HAS_PYDANTIC = False


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


if _HAS_PYDANTIC:

    class BBox(BaseModel):
        x: float
        y: float
        w: float
        h: float

    class ScenarioEvent(BaseModel):
        """Uniform event envelope across all scenarios."""

        scenario: str                       # slug, e.g. "frs", "anpr", "loitering"
        camera_id: str
        event_type: str                     # scenario verb: face_match, line_cross, gun_detected…
        confidence: float = 0.0
        triggered_at: datetime = Field(default_factory=utcnow)
        bbox: Optional[BBox] = None
        snapshot_key: Optional[str] = None  # plugin-stored snapshot reference
        label: Optional[str] = None         # human label: person name, plate text, "PPE: no helmet"
        severity: str = "info"              # info | warning | critical
        meta: dict[str, Any] = Field(default_factory=dict)  # scenario-specific extras

    def make_event(scenario: str, camera_id: str, event_type: str, **kw) -> dict:
        """Build a validated event dict ready to persist or POST."""
        return ScenarioEvent(
            scenario=scenario, camera_id=camera_id, event_type=event_type, **kw
        ).model_dump(mode="json")

else:  # pydantic absent (non-app contexts) — plain-dict fallback

    def make_event(scenario: str, camera_id: str, event_type: str, **kw) -> dict:
        ev = {
            "scenario": scenario,
            "camera_id": camera_id,
            "event_type": event_type,
            "confidence": kw.pop("confidence", 0.0),
            "triggered_at": kw.pop("triggered_at", utcnow()).isoformat()
            if hasattr(kw.get("triggered_at", utcnow()), "isoformat")
            else utcnow().isoformat(),
            "severity": kw.pop("severity", "info"),
            "meta": kw.pop("meta", {}),
        }
        ev.update(kw)
        return ev
