"""Reports summary: violations today, by-camera, by-type, compliance rate.
Service-token gated, camera-scoped."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select

from db import session
from db.models import PPEEvent
from deps import allowed_camera_ids, require_service_token
from routers._scope import apply_camera_scope
from schemas import naive

router = APIRouter(tags=["reports"])

_VIOLATION_TYPES = ("ppe_missing", "ppe_removed")


@router.get("/reports/summary")
def reports_summary(
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    _: None = Depends(require_service_token),
    allowed: Optional[list[str]] = Depends(allowed_camera_ids),
) -> dict:
    empty = {
        "total_events": 0, "violations": 0, "compliant": 0, "compliance_rate": None,
        "by_camera": [], "by_type": [], "by_hour": [],
    }
    with session() as s:
        conds = []
        if not apply_camera_scope(conds, PPEEvent.camera_id, None, allowed):
            return empty
        if since:
            conds.append(PPEEvent.triggered_at >= naive(since))
        if until:
            conds.append(PPEEvent.triggered_at <= naive(until))
        where = and_(*conds) if conds else None

        agg = select(
            func.count().label("total_events"),
            func.count().filter(PPEEvent.event_type.in_(_VIOLATION_TYPES)).label("violations"),
            func.count().filter(PPEEvent.event_type == "ppe_compliant").label("compliant"),
        )
        cam = (select(PPEEvent.camera_id, func.count().label("count"))
               .group_by(PPEEvent.camera_id).order_by(func.count().desc()))
        typ = (select(PPEEvent.event_type, func.count().label("count"))
               .group_by(PPEEvent.event_type).order_by(func.count().desc()))
        hour = (select(func.extract("hour", PPEEvent.triggered_at).label("hour"),
                       func.count().label("count"))
                .group_by(func.extract("hour", PPEEvent.triggered_at))
                .order_by(func.extract("hour", PPEEvent.triggered_at)))
        if where is not None:
            agg = agg.where(where)
            cam = cam.where(where)
            typ = typ.where(where)
            hour = hour.where(where)

        a = s.execute(agg).one()
        by_camera = [{"camera_id": c, "count": int(n)} for c, n in s.execute(cam).all()]
        by_type = [{"event_type": t, "count": int(n)} for t, n in s.execute(typ).all()]
        by_hour = [{"hour": int(h), "count": int(n)} for h, n in s.execute(hour).all()]

    violations = int(a.violations or 0)
    compliant = int(a.compliant or 0)
    denom = violations + compliant
    rate = round(compliant / denom, 4) if denom else None
    return {
        "total_events": int(a.total_events or 0),
        "violations": violations,
        "compliant": compliant,
        "compliance_rate": rate,
        "by_camera": by_camera,
        "by_type": by_type,
        "by_hour": by_hour,
    }
