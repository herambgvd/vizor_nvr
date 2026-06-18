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


def on_recognition(person_id: str | None, camera_id: str | None, ts: datetime) -> None:
    """Drive transit state from a recognised-person sighting."""
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
            s.add(TransitSession(
                rule_id=rule.id, person_id=person_id, status="open",
                started_at=ts,
                attributes={"entry_camera": camera_id,
                            "deadline": (ts + timedelta(minutes=window)).isoformat()},
            ))
            s.commit()


def sweep_overdue(now: datetime | None = None) -> int:
    """Mark open sessions past their deadline as overdue. Returns count flipped."""
    now = now or utcnow()
    flipped = 0
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
                flipped += 1
        if flipped:
            s.commit()
    return flipped
