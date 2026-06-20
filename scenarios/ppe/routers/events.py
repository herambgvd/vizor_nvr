"""Plugin-owned read side: paginated PPE events + delete. Service-token gated,
camera-scoped via the proxy's allowed-camera header. Unified {items,total,limit,
offset} envelope."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import and_, func, select

from db import session
from db.models import PPEEvent
from deps import allowed_camera_ids, require_service_token
from routers._scope import apply_camera_scope
from schemas import event_dict, naive

router = APIRouter(tags=["events"])


@router.get("/events")
def list_events(
    camera_id: Optional[list[str]] = Query(None),
    event_type: Optional[str] = None,
    worker_track_id: Optional[int] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: None = Depends(require_service_token),
    allowed: Optional[list[str]] = Depends(allowed_camera_ids),
) -> dict:
    with session() as s:
        conds = []
        if not apply_camera_scope(conds, PPEEvent.camera_id, camera_id, allowed):
            return {"items": [], "total": 0, "limit": limit, "offset": offset}
        if event_type:
            conds.append(PPEEvent.event_type == event_type)
        if worker_track_id is not None:
            conds.append(PPEEvent.worker_track_id == worker_track_id)
        if since:
            conds.append(PPEEvent.triggered_at >= naive(since))
        if until:
            conds.append(PPEEvent.triggered_at <= naive(until))
        where = and_(*conds) if conds else None
        cq = select(func.count()).select_from(PPEEvent)
        rq = select(PPEEvent)
        if where is not None:
            cq = cq.where(where)
            rq = rq.where(where)
        total = int(s.scalar(cq) or 0)
        rows = s.execute(
            rq.order_by(PPEEvent.triggered_at.desc()).limit(limit).offset(offset)
        ).scalars().all()
        return {"items": [event_dict(e) for e in rows], "total": total,
                "limit": limit, "offset": offset}


@router.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: str, _: None = Depends(require_service_token)):
    with session() as s:
        ev = s.get(PPEEvent, event_id)
        if not ev:
            raise HTTPException(404, "event not found")
        s.delete(ev)
        s.commit()
    return Response(status_code=204)


@router.post("/events/delete")
def bulk_delete_events(body: dict = Body(...), _: None = Depends(require_service_token)) -> dict:
    """Bulk delete by explicit ids, or by filter (camera/type/time) when
    `all_matching` is set. Returns how many were removed."""
    ids = body.get("ids") or []
    with session() as s:
        if ids:
            rows = s.execute(select(PPEEvent).where(PPEEvent.id.in_(ids))).scalars().all()
        elif body.get("all_matching"):
            conds = []
            if body.get("camera_id"):
                conds.append(PPEEvent.camera_id == body["camera_id"])
            if body.get("event_type"):
                conds.append(PPEEvent.event_type == body["event_type"])
            if body.get("since"):
                conds.append(PPEEvent.triggered_at >= naive(
                    datetime.fromisoformat(str(body["since"]).replace("Z", "+00:00"))))
            if body.get("until"):
                conds.append(PPEEvent.triggered_at <= naive(
                    datetime.fromisoformat(str(body["until"]).replace("Z", "+00:00"))))
            q = select(PPEEvent)
            if conds:
                q = q.where(and_(*conds))
            rows = s.execute(q).scalars().all()
        else:
            raise HTTPException(400, "provide ids[] or all_matching=true")
        count = len(rows)
        for ev in rows:
            s.delete(ev)
        s.commit()
    return {"deleted": count}
