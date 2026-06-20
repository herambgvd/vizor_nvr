"""Scenario logic — turn detections into events.

This is where the scenario's RULE lives. For a detect->alert scenario (this
template) it's a confidence threshold. For detect->track->rule scenarios add an
SDK ByteTracker + rules (Zone / LineCrossCounter / DwellTracker). For
detect->embed->match add a QdrantStore lookup.
"""
from __future__ import annotations

from vizor_sdk import make_event

from config.settings import config
from detect import Detection


def evaluate(detections: list[Detection], camera_id: str) -> list[dict]:
    """Map detections to scenario events. Returns a list of event dicts
    (vizor_sdk.make_event shape) ready to persist or emit to the NVR.

    TEMPLATE: emit one event per detection above the confidence threshold.
    Replace with your scenario's real rule.
    """
    events: list[dict] = []
    for d in detections:
        if d.confidence < config.MIN_CONFIDENCE:
            continue
        events.append(
            make_event(
                scenario=config.SLUG,
                camera_id=camera_id,
                event_type=f"{config.SLUG}_detected",
                confidence=d.confidence,
                label=d.label or None,
                bbox={"x": d.bbox[0], "y": d.bbox[1],
                      "w": d.bbox[2] - d.bbox[0], "h": d.bbox[3] - d.bbox[1]},
                severity="warning",
                meta=d.meta,
            )
        )
    return events
