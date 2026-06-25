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


def _iso_utc(dt) -> str | None:
    """ISO-8601 string that always carries a UTC marker. FRS stores naive-UTC, so
    a tz-naive datetime gets a 'Z' appended; an already tz-aware one is emitted
    with its own offset (no double-stamp)."""
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
    direction: Optional[str] = None,   # "entry" | "exit" | "both"/None (per-camera)
) -> str:
    """Insert an FRS event; for recognised persons also upsert daily attendance.
    Returns the new event id. Notifies the realtime bus."""
    from db.models import FRSAttendance, FRSEvent, FRSGroup, FRSPerson  # local (avoid cycle)
    from sqlalchemy import select

    attributes = dict(attributes or {})
    authorized: Optional[bool] = None
    auth_reason: Optional[str] = None
    group_name: Optional[str] = None

    with session() as s:
        # Authorization for a recognised person: must be within its validity window.
        # Surfaced in the event attributes so the UI can announce authorized /
        # not-authorized / unregistered.
        if person_id and event_type == "face_recognized":
            p = s.get(FRSPerson, person_id)
            if p is not None:
                if p.group_id:
                    g = s.get(FRSGroup, p.group_id)
                    group_name = g.name if g else None
                today = (ts or utcnow()).date()
                if p.validity_start and today < p.validity_start:
                    authorized, auth_reason = False, "validity not started"
                elif p.validity_end and today > p.validity_end:
                    authorized, auth_reason = False, "validity expired"
                else:
                    authorized, auth_reason = True, None
            else:
                authorized, auth_reason = False, "person not found"
        elif event_type in ("face_unknown", "face_detected"):
            authorized = False
            auth_reason = "unregistered"
        attributes.update({
            "authorized": authorized, "auth_reason": auth_reason,
            "group_name": group_name,
        })

        # transit_overdue is an alert, not a face sighting — surface it loudly with
        # its own title + severity so the operator notices.
        _is_overdue = event_type == "transit_overdue"
        _title = (attributes or {}).get("title") if _is_overdue else (
            person_name or ("Face detected" if event_type == "face_detected" else "Unknown face"))
        ev = FRSEvent(
            camera_id=camera_id, event_type=event_type,
            severity="warning" if _is_overdue else "info",
            title=_title or "Transit overdue",
            detection_type="transit" if _is_overdue else "face", person_id=person_id,
            confidence=round(float(confidence), 4) if confidence is not None else None,
            bbox=bbox, attributes=attributes,
            snapshot_path=snapshot_path, triggered_at=naive(ts) or ts,
        )
        s.add(ev)
        # Attendance is driven by actual face SIGHTINGS only. Synthetic alerts like
        # transit_overdue carry a person_id for context but are not a sighting — they
        # must not punch the clock.
        _SIGHTING_TYPES = {"face_recognized", "face_unknown", "face_detected"}
        if person_id and event_type in _SIGHTING_TYPES:
            face_snap = (attributes or {}).get("face_snapshot") or snapshot_path
            day_key = (ts or utcnow()).date().isoformat()
            existing = s.scalar(select(FRSAttendance).where(
                FRSAttendance.person_id == person_id, FRSAttendance.day_key == day_key))
            when = naive(ts)
            dir_ = (direction or "").lower()
            if existing:
                # Entry camera: only fills check-in (keeps the first/earliest). Exit
                # camera: updates check-out (keeps the latest exit). Both/unset: the
                # legacy first-seen / last-seen behaviour.
                if dir_ == "entry":
                    if existing.check_in_at is None or (when and when < existing.check_in_at):
                        existing.check_in_at = when
                        existing.check_in_snapshot = face_snap
                elif dir_ == "exit":
                    existing.check_out_at = when
                    existing.check_out_snapshot = face_snap
                else:
                    existing.check_out_at = when
                    existing.check_out_snapshot = face_snap
            else:
                # First sighting of the day. On an exit camera record it as a check-out
                # (no entry seen yet); otherwise it's the check-in.
                if dir_ == "exit":
                    s.add(FRSAttendance(person_id=person_id, camera_id=camera_id, day_key=day_key,
                                        check_out_at=when, check_out_snapshot=face_snap,
                                        sighting_type="seen", event_id=ev.id))
                else:
                    s.add(FRSAttendance(person_id=person_id, camera_id=camera_id, day_key=day_key,
                                        check_in_at=when, check_in_snapshot=face_snap,
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
        "authorized": authorized,
        "auth_reason": auth_reason,
        "group_name": group_name,
        "triggered_at": _iso_utc(ts or utcnow()),
    })
    return new_id
