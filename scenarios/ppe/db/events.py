"""PPE event recording — the single insert path for every PPE event, whether it
comes from a live camera worker or another producer.

`record_event()` inserts the PPEEvent and notifies the in-process event bus so a
realtime dashboard (SSE) can push it. The shape mirrors the FRS recorder so the
NVR proxy + events module render PPE uniformly.
"""
from __future__ import annotations

import queue
from typing import Optional

from vizor_sdk import EventBus, NvrClient

import config
from db import session
from schemas import naive, utcnow


# ── realtime bus (for the public SSE dashboard) ──────────────────────────────
# Shared SDK in-process pub/sub. The public router subscribes to this same bus;
# record_event publishes a small aggregate-safe dict on every insert.
bus = EventBus()

# Camera id -> name resolver (TTL-cached) so live-feed rows show names, not UUIDs.
_nvr = NvrClient(config.VIZOR_BASE_URL, config.VIZOR_API_KEY, config.SCENARIO_SLUG)
_ITEM_LABELS = {"helmet": "Helmet", "vest": "Vest", "hardhat": "Helmet",
                "safety_vest": "Vest"}


def _item_label(it) -> str:
    if not it:
        return "PPE"
    return _ITEM_LABELS.get(str(it).lower(), str(it).replace("_", " ").title())


def _camera_name(camera_id) -> Optional[str]:
    if not camera_id:
        return None
    try:
        return _nvr.camera_names(config.VIZOR_SERVICE_TOKEN).get(str(camera_id)) or str(camera_id)[:8]
    except Exception:  # noqa: BLE001
        return str(camera_id)[:8]


def _iso_utc(dt) -> str | None:
    """ISO-8601 string that always carries a UTC marker. PPE stores naive-UTC, so
    a tz-naive datetime gets a 'Z' appended; an already tz-aware one keeps its
    own offset."""
    if dt is None or not hasattr(dt, "isoformat"):
        return None
    s = dt.isoformat()
    return s if (dt.tzinfo is not None) else s + "Z"


def subscribe() -> queue.Queue:
    return bus.subscribe()


def unsubscribe(q: queue.Queue) -> None:
    bus.unsubscribe(q)


def _publish(payload: dict) -> None:
    bus.publish(payload)


_TITLES = {
    "ppe_missing": "PPE missing",
    "ppe_removed": "PPE removed",
    "ppe_compliant": "PPE compliant",
}
_SEVERITY = {
    "ppe_missing": "warning",
    "ppe_removed": "critical",
    "ppe_compliant": "info",
}


# ── the single event insert path ─────────────────────────────────────────────
def record_event(
    camera_id: Optional[str],
    event_type: str,
    worker_track_id: Optional[int],
    ppe_item: Optional[str],
    missing_items: Optional[list],
    present_items: Optional[list],
    confidence: Optional[float],
    snapshot_path: Optional[str],
    ts,
    bbox: Optional[dict] = None,
) -> str:
    """Insert a PPE event and notify the realtime bus. Returns the new event id."""
    from db.models import PPEEvent  # local import (avoid cycle)

    title = _TITLES.get(event_type, event_type)
    if ppe_item:
        title = f"{title}: {ppe_item}"
    with session() as s:
        ev = PPEEvent(
            camera_id=camera_id,
            event_type=event_type,
            severity=_SEVERITY.get(event_type, "warning"),
            title=title,
            worker_track_id=int(worker_track_id) if worker_track_id is not None else None,
            ppe_item=ppe_item,
            missing_items=list(missing_items) if missing_items else None,
            present_items=list(present_items) if present_items else None,
            confidence=round(float(confidence), 4) if confidence is not None else None,
            bbox=bbox,
            snapshot_path=snapshot_path,
            triggered_at=naive(ts) or ts,
        )
        s.add(ev)
        s.commit()
        new_id = ev.id

    # Notify the realtime dashboard (aggregate-safe: no snapshot bytes).
    # Friendly label for the feed: the missing items, or "Compliant" for a positive.
    if event_type == "ppe_compliant":
        label = "Compliant"
    elif missing_items:
        label = ", ".join(_item_label(m) for m in missing_items)
    else:
        label = _item_label(ppe_item) if ppe_item else "PPE Missing"
    _publish({
        "event_id": new_id,
        "event_type": event_type,
        "camera_id": camera_id,
        "camera_name": _camera_name(camera_id),
        "label": label,
        "worker_track_id": worker_track_id,
        "ppe_item": ppe_item,
        "missing_items": missing_items,
        "confidence": confidence,
        "triggered_at": _iso_utc(ts or utcnow()),
    })
    return new_id
