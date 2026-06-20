"""Plate reads read-side: paginated GET /plates + GET /plates/{id} + delete.

Service-token gated, camera-scoped via the proxy's allowed-camera header. Unified
{items,total,limit,offset} envelope. These rows ARE the ANPR events (event_type
plate_read / whitelist_hit / blacklist_hit)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import and_, func, select

from db import session
from db.models import ANPRPlateRead
from deps import allowed_camera_ids, require_service_token
from routers._scope import apply_camera_scope
from schemas import naive, read_dict

router = APIRouter(tags=["plates"])


@router.get("/plates")
def list_plates(
    camera_id: Optional[list[str]] = Query(None),
    plate: Optional[str] = None,
    event_type: Optional[str] = None,
    list_hit: Optional[str] = None,
    vehicle_type: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: None = Depends(require_service_token),
    allowed: Optional[list[str]] = Depends(allowed_camera_ids),
) -> dict:
    with session() as s:
        conds = []
        if not apply_camera_scope(conds, ANPRPlateRead.camera_id, camera_id, allowed):
            return {"items": [], "total": 0, "limit": limit, "offset": offset}
        if plate:
            conds.append(ANPRPlateRead.plate.ilike(f"%{plate.strip().upper()}%"))
        if event_type:
            conds.append(ANPRPlateRead.event_type == event_type)
        if list_hit:
            conds.append(ANPRPlateRead.list_hit == list_hit)
        if vehicle_type:
            conds.append(ANPRPlateRead.vehicle_type == vehicle_type)
        if since:
            conds.append(ANPRPlateRead.triggered_at >= naive(since))
        if until:
            conds.append(ANPRPlateRead.triggered_at <= naive(until))
        where = and_(*conds) if conds else None
        cq = select(func.count()).select_from(ANPRPlateRead)
        rq = select(ANPRPlateRead)
        if where is not None:
            cq = cq.where(where)
            rq = rq.where(where)
        total = int(s.scalar(cq) or 0)
        rows = s.execute(
            rq.order_by(ANPRPlateRead.triggered_at.desc()).limit(limit).offset(offset)
        ).scalars().all()
        return {"items": [read_dict(e) for e in rows], "total": total,
                "limit": limit, "offset": offset}


@router.get("/plates/{read_id}")
def get_plate(
    read_id: str,
    _: None = Depends(require_service_token),
    allowed: Optional[list[str]] = Depends(allowed_camera_ids),
) -> dict:
    with session() as s:
        ev = s.get(ANPRPlateRead, read_id)
        if not ev:
            raise HTTPException(404, "plate read not found")
        if allowed is not None and ev.camera_id not in set(allowed):
            raise HTTPException(404, "plate read not found")  # don't leak existence
        return read_dict(ev)


@router.delete("/plates/{read_id}", status_code=204)
def delete_plate(read_id: str, _: None = Depends(require_service_token)):
    with session() as s:
        ev = s.get(ANPRPlateRead, read_id)
        if not ev:
            raise HTTPException(404, "plate read not found")
        s.delete(ev)
        s.commit()
    return Response(status_code=204)


@router.post("/plates/delete")
def bulk_delete_plates(body: dict = Body(...), _: None = Depends(require_service_token)) -> dict:
    """Bulk delete by explicit ids, or by filter when `all_matching` is set."""
    ids = body.get("ids") or []
    with session() as s:
        if ids:
            rows = s.execute(select(ANPRPlateRead).where(ANPRPlateRead.id.in_(ids))).scalars().all()
        elif body.get("all_matching"):
            conds = []
            if body.get("camera_id"):
                conds.append(ANPRPlateRead.camera_id == body["camera_id"])
            if body.get("event_type"):
                conds.append(ANPRPlateRead.event_type == body["event_type"])
            if body.get("since"):
                conds.append(ANPRPlateRead.triggered_at >= naive(
                    datetime.fromisoformat(str(body["since"]).replace("Z", "+00:00"))))
            if body.get("until"):
                conds.append(ANPRPlateRead.triggered_at <= naive(
                    datetime.fromisoformat(str(body["until"]).replace("Z", "+00:00"))))
            q = select(ANPRPlateRead)
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
