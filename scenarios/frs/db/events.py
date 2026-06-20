"""FRS event recording — the single insert path for every FRS event, whether it
comes from a live camera worker or a third-party ingest.

`record_event()` inserts the FRSEvent (+ daily attendance upsert for recognised
persons) exactly as the live worker always did, and notifies the in-process event
bus so the public realtime dashboard (SSE) can push it. Transit / Tour /
Investigate read frs_events, so anything recorded here flows into them with no
extra wiring.
"""
from __future__ import annotations

import queue
import threading
from typing import Any, Optional

from db import session
from schemas import naive, utcnow


# ── realtime bus (for the public SSE dashboard) ──────────────────────────────
# Each subscriber gets a bounded queue; a slow/dead client drops events rather
# than back-pressuring the recorder.
_subscribers: set[queue.Queue] = set()
_sub_lock = threading.Lock()


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


# ── the single event insert path ─────────────────────────────────────────────
def record_event(
    camera_id: Optional[str],
    person_id: Optional[str],
    person_name: Optional[str],
    confidence: Optional[float],
    snapshot_path: Optional[str],
    event_type: str,
    ts,
    bbox: Optional[dict] = None,
    attributes: Optional[dict] = None,
) -> str:
    """Insert an FRS event; for recognised persons also upsert daily attendance.
    Returns the new event id. Notifies the realtime bus."""
    from db.models import FRSAttendance, FRSEvent  # local import (avoid cycle)
    from sqlalchemy import select

    with session() as s:
        ev = FRSEvent(
            camera_id=camera_id, event_type=event_type, severity="info",
            title=person_name or ("Face detected" if event_type == "face_detected" else "Unknown face"),
            detection_type="face", person_id=person_id,
            confidence=round(float(confidence), 4) if confidence is not None else None,
            bbox=bbox, attributes=attributes,
            snapshot_path=snapshot_path, triggered_at=naive(ts) or ts,
        )
        s.add(ev)
        if person_id:
            face_snap = (attributes or {}).get("face_snapshot") or snapshot_path
            day_key = (ts or utcnow()).date().isoformat()
            existing = s.scalar(select(FRSAttendance).where(
                FRSAttendance.person_id == person_id, FRSAttendance.day_key == day_key))
            if existing:
                existing.check_out_at = naive(ts)
                existing.check_out_snapshot = face_snap
            else:
                s.add(FRSAttendance(person_id=person_id, camera_id=camera_id, day_key=day_key,
                                    check_in_at=naive(ts), check_in_snapshot=face_snap,
                                    sighting_type="seen", event_id=ev.id))
        s.commit()
        new_id = ev.id

    # Notify the realtime dashboard (aggregate-safe: name only, no snapshot bytes).
    _publish({
        "event_id": new_id,
        "event_type": event_type,
        "camera_id": camera_id,
        "person_name": person_name,
        "confidence": confidence,
        "triggered_at": (ts or utcnow()).isoformat() if hasattr((ts or utcnow()), "isoformat") else None,
    })
    return new_id
