"""PPE event recording — the single insert path for every PPE event, whether it
comes from a live camera worker or another producer.

`record_event()` inserts the PPEEvent and notifies the in-process event bus so a
realtime dashboard (SSE) can push it. The shape mirrors the FRS recorder so the
NVR proxy + events module render PPE uniformly.
"""
from __future__ import annotations

import queue
import threading
from typing import Optional

from db import session
from schemas import naive, utcnow


# ── realtime bus (for a future public SSE dashboard) ─────────────────────────
# Each subscriber gets a bounded queue; a slow/dead client drops events rather
# than back-pressuring the recorder.
_subscribers: set[queue.Queue] = set()
_sub_lock = threading.Lock()


def _iso_utc(dt) -> str | None:
    """ISO-8601 string that always carries a UTC marker. PPE stores naive-UTC, so
    a tz-naive datetime gets a 'Z' appended; an already tz-aware one keeps its
    own offset."""
    if dt is None or not hasattr(dt, "isoformat"):
        return None
    s = dt.isoformat()
    return s if (dt.tzinfo is not None) else s + "Z"


def subscribe() -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=100)
    with _sub_lock:
        _subscribers.add(q)
    return q


def unsubscribe(q: queue.Queue) -> None:
    with _sub_lock:
        _subscribers.discard(q)


def _publish(payload: dict) -> None:
    with _sub_lock:
        subs = list(_subscribers)
    for q in subs:
        try:
            q.put_nowait(payload)
        except queue.Full:
            pass  # slow client — drop rather than block the recorder


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
    _publish({
        "event_id": new_id,
        "event_type": event_type,
        "camera_id": camera_id,
        "worker_track_id": worker_track_id,
        "ppe_item": ppe_item,
        "missing_items": missing_items,
        "confidence": confidence,
        "triggered_at": _iso_utc(ts or utcnow()),
    })
    return new_id
