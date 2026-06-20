"""ANPR read recording — the single insert path for every plate read, whether it
comes from a live camera worker or another producer.

`record_event()` inserts the ANPRPlateRead and notifies the in-process event bus
so a realtime dashboard (SSE) can push it. The shape mirrors the PPE/FRS recorder
so the NVR proxy + events module render ANPR uniformly.
"""
from __future__ import annotations

import queue
import threading
from typing import Optional

from db import session
from schemas import naive, utcnow


# ── realtime bus (for a future public SSE dashboard) ─────────────────────────
_subscribers: set[queue.Queue] = set()
_sub_lock = threading.Lock()


def _iso_utc(dt) -> str | None:
    """ISO-8601 string that always carries a UTC marker. ANPR stores naive-UTC, so
    a tz-naive datetime gets a 'Z' appended; an already tz-aware one keeps its own
    offset."""
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


# event_type ∈ {plate_read, whitelist_hit, blacklist_hit}. A blacklist hit is a
# high-severity event; whitelist a positive/info one.
_TITLES = {
    "plate_read": "Plate read",
    "whitelist_hit": "Whitelist match",
    "blacklist_hit": "Blacklist match",
}
_SEVERITY = {
    "plate_read": "info",
    "whitelist_hit": "info",
    "blacklist_hit": "critical",
}


# ── the single event insert path ─────────────────────────────────────────────
def record_event(
    camera_id: Optional[str],
    plate: str,
    confidence: Optional[float],
    *,
    event_type: str = "plate_read",
    vehicle_type: Optional[str] = None,
    direction: Optional[str] = None,
    speed_kmh: Optional[float] = None,
    list_hit: Optional[str] = None,
    list_label: Optional[str] = None,
    track_id: Optional[int] = None,
    n_frames: Optional[int] = None,
    bbox: Optional[dict] = None,
    snapshot_path: Optional[str] = None,
    ts=None,
) -> str:
    """Insert an ANPR plate read and notify the realtime bus. Returns the new id."""
    from db.models import ANPRPlateRead  # local import (avoid cycle)

    title = _TITLES.get(event_type, event_type)
    title = f"{title}: {plate}"
    with session() as s:
        ev = ANPRPlateRead(
            camera_id=camera_id,
            event_type=event_type,
            severity=_SEVERITY.get(event_type, "info"),
            title=title,
            plate=plate,
            confidence=round(float(confidence), 4) if confidence is not None else None,
            vehicle_type=vehicle_type,
            direction=direction,
            speed_kmh=round(float(speed_kmh), 1) if speed_kmh is not None else None,
            list_hit=list_hit,
            list_label=list_label,
            track_id=int(track_id) if track_id is not None else None,
            n_frames=int(n_frames) if n_frames is not None else None,
            bbox=bbox,
            snapshot_path=snapshot_path,
            triggered_at=naive(ts) or utcnow(),
        )
        s.add(ev)
        s.commit()
        new_id = ev.id

    # Notify the realtime dashboard (aggregate-safe: no snapshot bytes).
    _publish({
        "event_id": new_id,
        "event_type": event_type,
        "camera_id": camera_id,
        "plate": plate,
        "vehicle_type": vehicle_type,
        "direction": direction,
        "speed_kmh": speed_kmh,
        "list_hit": list_hit,
        "confidence": confidence,
        "triggered_at": _iso_utc(ts or utcnow()),
    })
    return new_id
