"""Plugin-owned read side: events, attendance, reports summary, live feed."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import and_, func, select

import config
from db import session
from deps import require_service_token
from db.models import FRSAttendance, FRSEvent, FRSFeedback, FRSPerson
from schemas import event_dict, iso, naive

router = APIRouter(tags=["reports"])


@router.post("/feedback")
def submit_feedback(body: dict = Body(...), _: None = Depends(require_service_token)) -> dict:
    """Operator marks a recognition correct/wrong (one verdict per event+operator)."""
    eid = body.get("event_id")
    if not eid:
        raise HTTPException(400, "event_id required")
    operator = str(body.get("operator") or "operator")
    with session() as s:
        fb = s.scalar(select(FRSFeedback).where(
            FRSFeedback.event_id == eid, FRSFeedback.operator == operator))
        if fb is None:
            fb = FRSFeedback(event_id=eid, operator=operator, is_correct=bool(body.get("is_correct")))
            s.add(fb)
        else:
            fb.is_correct = bool(body.get("is_correct"))
        fb.matched_person_id = body.get("matched_person_id")
        fb.actual_person_id = body.get("actual_person_id")
        fb.note = body.get("note")
        s.commit(); s.refresh(fb)
        return {"id": fb.id, "event_id": fb.event_id, "is_correct": fb.is_correct}


@router.get("/feedback")
def list_feedback(event_id: Optional[str] = None, is_correct: Optional[bool] = None,
                  limit: int = Query(100, ge=1, le=500), _: None = Depends(require_service_token)) -> dict:
    with session() as s:
        q = select(FRSFeedback)
        if event_id:
            q = q.where(FRSFeedback.event_id == event_id)
        if is_correct is not None:
            q = q.where(FRSFeedback.is_correct.is_(is_correct))
        rows = s.execute(q.order_by(FRSFeedback.created_at.desc()).limit(limit)).scalars().all()
        return {"items": [{"id": f.id, "event_id": f.event_id, "is_correct": f.is_correct,
                           "matched_person_id": f.matched_person_id, "actual_person_id": f.actual_person_id,
                           "note": f.note, "operator": f.operator, "created_at": iso(f.created_at)}
                          for f in rows]}


def _purge_snapshots(events) -> None:
    """Best-effort delete of an event's live snapshot files (full + face crop)."""
    import os
    for ev in events:
        for path in (ev.snapshot_path, (ev.attributes or {}).get("face_snapshot") if ev.attributes else None):
            if not path or "key=live:" not in str(path):
                continue
            key = str(path).split("key=live:", 1)[1]
            f = config.DATA_PATH / "snapshots" / f"{key}.jpg"
            try:
                if f.exists():
                    os.remove(f)
            except OSError:
                pass


@router.get("/events")
def list_events(camera_id: Optional[list[str]] = Query(None), person_id: Optional[str] = None,
                event_type: Optional[str] = None, since: Optional[datetime] = None,
                until: Optional[datetime] = None, limit: int = Query(50, ge=1, le=500),
                offset: int = Query(0, ge=0), _: None = Depends(require_service_token)) -> dict:
    with session() as s:
        conds = []
        if camera_id:
            conds.append(FRSEvent.camera_id.in_(camera_id))
        if person_id:
            conds.append(FRSEvent.person_id == person_id)
        if event_type:
            conds.append(FRSEvent.event_type == event_type)
        if since:
            conds.append(FRSEvent.triggered_at >= naive(since))
        if until:
            conds.append(FRSEvent.triggered_at <= naive(until))
        where = and_(*conds) if conds else None
        cq = select(func.count()).select_from(FRSEvent)
        rq = select(FRSEvent)
        if where is not None:
            cq = cq.where(where); rq = rq.where(where)
        total = int(s.scalar(cq) or 0)
        rows = s.execute(rq.order_by(FRSEvent.triggered_at.desc()).limit(limit).offset(offset)).scalars().all()
        return {"items": [event_dict(e) for e in rows], "total": total, "limit": limit, "offset": offset}


@router.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: str, _: None = Depends(require_service_token)):
    with session() as s:
        ev = s.get(FRSEvent, event_id)
        if not ev:
            raise HTTPException(404, "event not found")
        _purge_snapshots([ev])
        s.delete(ev); s.commit()
    return Response(status_code=204)


@router.post("/events/delete")
def bulk_delete_events(body: dict = Body(...), _: None = Depends(require_service_token)) -> dict:
    """Bulk delete by explicit ids, or by filter (camera/type/time range) when
    `all_matching` is set. Returns how many were removed."""
    ids = body.get("ids") or []
    with session() as s:
        if ids:
            rows = s.execute(select(FRSEvent).where(FRSEvent.id.in_(ids))).scalars().all()
        elif body.get("all_matching"):
            conds = []
            if body.get("camera_id"):
                conds.append(FRSEvent.camera_id == body["camera_id"])
            if body.get("event_type"):
                conds.append(FRSEvent.event_type == body["event_type"])
            if body.get("since"):
                conds.append(FRSEvent.triggered_at >= naive(datetime.fromisoformat(str(body["since"]).replace("Z", "+00:00"))))
            if body.get("until"):
                conds.append(FRSEvent.triggered_at <= naive(datetime.fromisoformat(str(body["until"]).replace("Z", "+00:00"))))
            q = select(FRSEvent)
            if conds:
                q = q.where(and_(*conds))
            rows = s.execute(q).scalars().all()
        else:
            raise HTTPException(400, "provide ids[] or all_matching=true")
        _purge_snapshots(rows)
        count = len(rows)
        for ev in rows:
            s.delete(ev)
        s.commit()
    return {"deleted": count}


@router.get("/attendance")
def list_attendance(person_id: Optional[str] = None, camera_id: Optional[str] = None,
                    since: Optional[datetime] = None, until: Optional[datetime] = None,
                    limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
                    _: None = Depends(require_service_token)) -> dict:
    with session() as s:
        conds = []
        if person_id:
            conds.append(FRSAttendance.person_id == person_id)
        if camera_id:
            conds.append(FRSAttendance.camera_id == camera_id)
        if since:
            conds.append(FRSAttendance.check_in_at >= naive(since))
        if until:
            conds.append(FRSAttendance.check_in_at <= naive(until))
        where = and_(*conds) if conds else None
        cq = select(func.count()).select_from(FRSAttendance)
        if where is not None:
            cq = cq.where(where)
        total = int(s.scalar(cq) or 0)
        stmt = (select(FRSAttendance, FRSPerson.full_name)
                .outerjoin(FRSPerson, FRSPerson.id == FRSAttendance.person_id)
                .order_by(FRSAttendance.day_key.desc(), FRSAttendance.check_in_at.desc())
                .limit(limit).offset(offset))
        if where is not None:
            stmt = stmt.where(where)
        rows = [{
            "id": a.id, "person_id": a.person_id, "person_name": name, "camera_id": a.camera_id,
            "day_key": a.day_key, "check_in_at": iso(a.check_in_at), "check_out_at": iso(a.check_out_at),
            "check_in_snapshot": a.check_in_snapshot, "check_out_snapshot": a.check_out_snapshot,
            "sighting_type": a.sighting_type, "event_id": a.event_id,
        } for a, name in s.execute(stmt).all()]
        return {"items": rows, "total": total, "limit": limit, "offset": offset}


@router.get("/attendance/report")
def attendance_report(day_from: str = Query(...), day_to: str = Query(...),
                      _: None = Depends(require_service_token)) -> dict:
    if day_from > day_to:
        raise HTTPException(400, "day_from must not be after day_to")
    with session() as s:
        stmt = (select(
            FRSAttendance.person_id, FRSPerson.full_name,
            func.count(func.distinct(FRSAttendance.day_key)).label("days_present"),
            func.min(FRSAttendance.check_in_at).label("first_seen"),
            func.max(func.coalesce(FRSAttendance.check_out_at, FRSAttendance.check_in_at)).label("last_seen"),
        ).outerjoin(FRSPerson, FRSPerson.id == FRSAttendance.person_id)
         .where(and_(FRSAttendance.day_key >= day_from, FRSAttendance.day_key <= day_to))
         .group_by(FRSAttendance.person_id, FRSPerson.full_name)
         .order_by(func.count(func.distinct(FRSAttendance.day_key)).desc()))
        rows = [{
            "person_id": pid, "person_name": name, "days_present": int(dp or 0),
            "first_seen": iso(fs), "last_seen": iso(ls),
        } for pid, name, dp, fs, ls in s.execute(stmt).all()]
    return {"items": rows, "day_from": day_from, "day_to": day_to}


@router.get("/reports/summary")
def reports_summary(since: Optional[datetime] = None, until: Optional[datetime] = None,
                    _: None = Depends(require_service_token)) -> dict:
    with session() as s:
        conds = []
        if since:
            conds.append(FRSEvent.triggered_at >= naive(since))
        if until:
            conds.append(FRSEvent.triggered_at <= naive(until))
        where = and_(*conds) if conds else None
        agg = select(
            func.count().label("total_events"),
            func.count(func.distinct(FRSEvent.person_id)).label("unique_persons"),
            func.count().filter(FRSEvent.event_type == "face_unknown").label("unknown_count"),
            func.count().filter(FRSEvent.event_type == "spoof_detected").label("spoof_count"),
        )
        cam = select(FRSEvent.camera_id, func.count().label("count")).group_by(FRSEvent.camera_id).order_by(func.count().desc())
        hour = (select(func.extract("hour", FRSEvent.triggered_at).label("hour"), func.count().label("count"))
                .group_by(func.extract("hour", FRSEvent.triggered_at))
                .order_by(func.extract("hour", FRSEvent.triggered_at)))
        if where is not None:
            agg = agg.where(where); cam = cam.where(where); hour = hour.where(where)
        a = s.execute(agg).one()
        by_camera = [{"camera_id": c, "count": int(n)} for c, n in s.execute(cam).all()]
        by_hour = [{"hour": int(h), "count": int(n)} for h, n in s.execute(hour).all()]
    return {"total_events": int(a.total_events or 0), "unique_persons": int(a.unique_persons or 0),
            "unknown_count": int(a.unknown_count or 0), "spoof_count": int(a.spoof_count or 0),
            "by_camera": by_camera, "by_hour": by_hour}


@router.get("/live")
def live(camera_id: Optional[list[str]] = Query(None), limit: int = Query(50, ge=1, le=200),
         _: None = Depends(require_service_token)) -> dict:
    with session() as s:
        q = select(FRSEvent)
        if camera_id:
            q = q.where(FRSEvent.camera_id.in_(camera_id))
        rows = s.execute(q.order_by(FRSEvent.triggered_at.desc()).limit(limit)).scalars().all()
        return {"items": [event_dict(e) for e in rows]}
