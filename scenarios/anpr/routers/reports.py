"""Reports summary: reads today, by-camera, by-vehicle-type, blacklist hits,
by-hour. Service-token gated, camera-scoped."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import and_, func, select

from db import session
from db.models import ANPRPlateRead
from deps import allowed_camera_ids, require_service_token
from routers._scope import apply_camera_scope
from schemas import naive

router = APIRouter(tags=["reports"])


@router.get("/reports/summary")
def reports_summary(
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    _: None = Depends(require_service_token),
    allowed: Optional[list[str]] = Depends(allowed_camera_ids),
) -> dict:
    empty = {
        "total_reads": 0, "blacklist_hits": 0, "whitelist_hits": 0,
        "by_camera": [], "by_vehicle_type": [], "by_hour": [],
    }
    with session() as s:
        conds = []
        if not apply_camera_scope(conds, ANPRPlateRead.camera_id, None, allowed):
            return empty
        if since:
            conds.append(ANPRPlateRead.triggered_at >= naive(since))
        if until:
            conds.append(ANPRPlateRead.triggered_at <= naive(until))
        where = and_(*conds) if conds else None

        agg = select(
            func.count().label("total_reads"),
            func.count().filter(ANPRPlateRead.list_hit == "blacklist").label("blacklist_hits"),
            func.count().filter(ANPRPlateRead.list_hit == "whitelist").label("whitelist_hits"),
        )
        cam = (select(ANPRPlateRead.camera_id, func.count().label("count"))
               .group_by(ANPRPlateRead.camera_id).order_by(func.count().desc()))
        veh = (select(ANPRPlateRead.vehicle_type, func.count().label("count"))
               .group_by(ANPRPlateRead.vehicle_type).order_by(func.count().desc()))
        hour = (select(func.extract("hour", ANPRPlateRead.triggered_at).label("hour"),
                       func.count().label("count"))
                .group_by(func.extract("hour", ANPRPlateRead.triggered_at))
                .order_by(func.extract("hour", ANPRPlateRead.triggered_at)))
        if where is not None:
            agg = agg.where(where)
            cam = cam.where(where)
            veh = veh.where(where)
            hour = hour.where(where)

        a = s.execute(agg).one()
        by_camera = [{"camera_id": c, "count": int(n)} for c, n in s.execute(cam).all()]
        by_vehicle = [{"vehicle_type": (t or "unknown"), "count": int(n)}
                      for t, n in s.execute(veh).all()]
        by_hour = [{"hour": int(h), "count": int(n)} for h, n in s.execute(hour).all()]

    return {
        "total_reads": int(a.total_reads or 0),
        "blacklist_hits": int(a.blacklist_hits or 0),
        "whitelist_hits": int(a.whitelist_hits or 0),
        "by_camera": by_camera,
        "by_vehicle_type": by_vehicle,
        "by_hour": by_hour,
    }
