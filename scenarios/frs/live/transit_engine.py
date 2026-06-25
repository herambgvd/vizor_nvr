"""Transit auto-engine.

Turns recognition events into entry→exit sessions. A rule's config carries
{entry_camera, exit_cameras[], window_minutes}. When a recognised person is seen
on a rule's entry camera an `open` session is started with a deadline; seeing
them on an exit camera before the deadline `closes` it; a periodic sweep marks
past-deadline sessions `overdue`.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, select

from db import session as db_session
from schemas import utcnow
from db.models import TransitRule, TransitSession


def _rules_for_entry(s, camera_id: str):
    rules = s.execute(select(TransitRule).where(TransitRule.enabled.is_(True))).scalars().all()
    return [r for r in rules if (r.config or {}).get("entry_camera") == camera_id]


def _rules_for_exit(s, camera_id: str):
    rules = s.execute(select(TransitRule).where(TransitRule.enabled.is_(True))).scalars().all()
    return [r for r in rules if camera_id in ((r.config or {}).get("exit_cameras") or [])]


def on_recognition(person_id: str | None, camera_id: str | None, ts: datetime,
                   person_name: str | None = None, snapshot_key: str | None = None) -> None:
    """Drive transit state from a recognised-person sighting. `person_name` is
    stored on the session so the UI shows the name; `snapshot_key` is stored as the
    entry/exit thumbnail so the session detail modal can show who/where."""
    if not person_id or not camera_id:
        return
    with db_session() as s:
        # Exit first: close any open session this sighting satisfies.
        for rule in _rules_for_exit(s, camera_id):
            open_sess = s.scalar(select(TransitSession).where(and_(
                TransitSession.rule_id == rule.id,
                TransitSession.person_id == person_id,
                TransitSession.status == "open",
            )).order_by(TransitSession.started_at.desc()))
            if open_sess:
                open_sess.status = "closed"
                open_sess.ended_at = ts
                attrs = dict(open_sess.attributes or {})
                attrs["exit_camera"] = camera_id
                attrs["exit_ts"] = ts.isoformat()
                attrs["duration_seconds"] = int(
                    (ts - open_sess.started_at).total_seconds()) if open_sess.started_at else None
                if snapshot_key:
                    attrs["exit_snapshot"] = snapshot_key
                open_sess.attributes = attrs
                s.commit()
                return  # one sighting closes at most one session

        # Entry: open a new session if none currently open for this rule+person.
        for rule in _rules_for_entry(s, camera_id):
            window = int((rule.config or {}).get("window_minutes") or 15)
            existing = s.scalar(select(TransitSession).where(and_(
                TransitSession.rule_id == rule.id,
                TransitSession.person_id == person_id,
                TransitSession.status == "open",
            )))
            if existing:
                continue
            attrs = {"entry_camera": camera_id,
                     "entry_ts": ts.isoformat(),
                     "deadline": (ts + timedelta(minutes=window)).isoformat()}
            if person_name:
                attrs["person_name"] = person_name
            if snapshot_key:
                attrs["entry_snapshot"] = snapshot_key
            s.add(TransitSession(
                rule_id=rule.id, person_id=person_id, status="open",
                started_at=ts, attributes=attrs,
            ))
            s.commit()


def sweep_overdue(now: datetime | None = None) -> int:
    """Mark open sessions past their deadline as overdue + emit a `transit_overdue`
    event per flip so the operator actually sees the alert (it shows in the Events
    list + live SSE, not just a status change buried in the Transit tab). Returns
    the count flipped."""
    now = now or utcnow()
    flipped: list[dict] = []
    with db_session() as s:
        opens = s.execute(select(TransitSession).where(TransitSession.status == "open")).scalars().all()
        for sess in opens:
            dl = (sess.attributes or {}).get("deadline")
            if not dl:
                continue
            try:
                deadline = datetime.fromisoformat(str(dl).replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                continue
            if now > deadline:
                sess.status = "overdue"
                attrs = dict(sess.attributes or {})
                # Carry session context onto the event so the operator sees who,
                # which rule, how long open, and where they entered.
                flipped.append({
                    "session_id": sess.id,
                    "rule_id": sess.rule_id,
                    "person_id": sess.person_id,
                    "person_name": attrs.get("person_name"),
                    "entry_camera": attrs.get("entry_camera"),
                    "entry_snapshot": attrs.get("entry_snapshot"),
                    "entry_ts": attrs.get("entry_ts"),
                    "deadline": dl,
                    "overdue_seconds": int((now - deadline).total_seconds()),
                })
        if flipped:
            s.commit()

    # Emit events AFTER the commit so a failed insert never blocks the status flip.
    for f in flipped:
        try:
            _emit_overdue_event(f, now)
        except Exception:  # noqa: BLE001 — alerting must never break the sweep
            pass
    return len(flipped)


def _emit_overdue_event(f: dict, now: datetime) -> None:
    """Write a `transit_overdue` FRS event for one flipped session so it surfaces in
    the Events list + live feed like any other recognition alert."""
    from db.events import record_event
    from db import session as _evt_session  # ensure record_event's session is ready

    # Resolve rule name + the person's display name. The session stores the name at
    # entry time, but older sessions (opened before that was added) only have a
    # person_id — fall back to the gallery so the event shows "Heramb Mishra", not
    # "Person 642d74c2".
    rule_name = None
    person_name = f.get("person_name")
    try:
        with db_session() as s:
            r = s.get(TransitRule, f["rule_id"])
            rule_name = r.name if r else None
            if not person_name and f.get("person_id"):
                from db.models import FRSPerson
                p = s.get(FRSPerson, f["person_id"])
                person_name = p.full_name if p else None
    except Exception:  # noqa: BLE001
        pass

    name = person_name or (f"Person {str(f.get('person_id'))[:8]}"
                           if f.get("person_id") else "Unknown")
    record_event(
        camera_id=f.get("entry_camera"),
        person_id=f.get("person_id"),
        person_name=person_name,
        confidence=None,
        snapshot_path=f.get("entry_snapshot"),
        event_type="transit_overdue",
        ts=now,
        attributes={
            # Stash the resolved name in attributes too — the Events UI reads
            # attributes.person_name for the PERSON column (the FRSEvent row has no
            # name field), so without this it would show "Person <id>".
            "person_name": person_name,
            "rule_id": f.get("rule_id"),
            "rule_name": rule_name,
            "session_id": f.get("session_id"),
            "entry_camera": f.get("entry_camera"),
            "entry_ts": f.get("entry_ts"),
            "deadline": f.get("deadline"),
            "overdue_seconds": f.get("overdue_seconds"),
            "title": f"Transit overdue — {name}"
                     + (f" ({rule_name})" if rule_name else ""),
        },
    )
