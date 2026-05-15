"""
People Counting routes — zone CRUD + counts aggregation + live snapshot.

Routes prefixed at /api/ai/people. Mounted in app/main.py alongside the
other AI routers.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import require_permission
from app.ai.models import PeopleCountZone, PeopleCount


router = APIRouter(prefix="/api/ai/people", tags=["AI · People Counting"])

# Separate small router for ai-wide control (no /people prefix).
control_router = APIRouter(prefix="/api/ai", tags=["AI Control"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ZoneGeometry(BaseModel):
    """Normalized 0-1 geometry. Lines = 2 points. Polygons = >=3 points."""

    kind: Literal["line", "polygon"]
    points: List[List[float]]

    @field_validator("points")
    @classmethod
    def _check_points(cls, v, info):
        kind = info.data.get("kind")
        if kind == "line" and len(v) != 2:
            raise ValueError("line geometry requires exactly 2 points")
        if kind == "polygon" and len(v) < 3:
            raise ValueError("polygon geometry requires at least 3 points")
        for p in v:
            if len(p) != 2:
                raise ValueError("point must be [x, y]")
            x, y = p
            if not (0 <= x <= 1 and 0 <= y <= 1):
                raise ValueError("coordinates must be normalized 0..1")
        return v


SEVERITY_VALUES = ("info", "warning", "critical")


class ZoneCreate(BaseModel):
    scenario: Literal["in_out", "crowd"]
    name: str = Field(..., min_length=1, max_length=100)
    geometry: ZoneGeometry
    threshold: Optional[int] = Field(None, ge=1, le=10000)
    direction_a_label: str = Field("in", max_length=20)
    direction_b_label: str = Field("out", max_length=20)
    severity: Literal["info", "warning", "critical"] = "info"
    enabled: bool = True


class ZoneUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    geometry: Optional[ZoneGeometry] = None
    threshold: Optional[int] = Field(None, ge=1, le=10000)
    direction_a_label: Optional[str] = Field(None, max_length=20)
    direction_b_label: Optional[str] = Field(None, max_length=20)
    severity: Optional[Literal["info", "warning", "critical"]] = None
    enabled: Optional[bool] = None


class ZoneOut(BaseModel):
    id: str
    camera_id: str
    scenario: str
    name: str
    geometry: dict
    threshold: Optional[int]
    direction_a_label: str
    direction_b_label: str
    severity: str = "info"
    enabled: bool

    class Config:
        from_attributes = True


class CountBucket(BaseModel):
    bucket_ts: datetime
    zone_id: str
    camera_id: str
    in_count: int
    out_count: int
    occupancy: int
    crowd_alerts: int


# ---------------------------------------------------------------------------
# Zone CRUD
# ---------------------------------------------------------------------------


@router.get("/cameras/{camera_id}/zones", response_model=List[ZoneOut])
async def list_zones(
    camera_id: str,
    user=Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    """All zones configured on a camera (both in_out + crowd)."""
    result = await db.execute(
        select(PeopleCountZone)
        .where(PeopleCountZone.camera_id == camera_id)
        .order_by(PeopleCountZone.created_at)
    )
    return list(result.scalars().all())


@router.post(
    "/cameras/{camera_id}/zones",
    response_model=ZoneOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_zone(
    camera_id: str,
    payload: ZoneCreate,
    user=Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
):
    """Create a counting zone on a camera."""
    zone = PeopleCountZone(
        id=str(_uuid.uuid4()),
        camera_id=camera_id,
        scenario=payload.scenario,
        name=payload.name,
        geometry=payload.geometry.model_dump(),
        threshold=payload.threshold,
        direction_a_label=payload.direction_a_label,
        direction_b_label=payload.direction_b_label,
        severity=payload.severity,
        enabled=payload.enabled,
    )
    db.add(zone)
    await db.commit()
    await db.refresh(zone)

    await _publish_reload()
    return zone


@router.patch("/zones/{zone_id}", response_model=ZoneOut)
async def update_zone(
    zone_id: str,
    payload: ZoneUpdate,
    user=Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PeopleCountZone).where(PeopleCountZone.id == zone_id)
    )
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Zone not found")

    data = payload.model_dump(exclude_unset=True)
    if "geometry" in data and data["geometry"]:
        data["geometry"] = data["geometry"]  # already dict from model_dump

    for k, v in data.items():
        setattr(zone, k, v)
    zone.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(zone)
    await _publish_reload()
    return zone


@router.delete("/zones/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_zone(
    zone_id: str,
    user=Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PeopleCountZone).where(PeopleCountZone.id == zone_id)
    )
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Zone not found")
    await db.delete(zone)
    await db.commit()
    await _publish_reload()


# ---------------------------------------------------------------------------
# Counts aggregation
# ---------------------------------------------------------------------------


@router.get("/counts", response_model=List[CountBucket])
async def get_counts(
    camera_id: Optional[str] = Query(None),
    zone_id: Optional[str] = Query(None),
    granularity: Literal["minute", "hour", "day"] = "hour",
    since: Optional[datetime] = Query(None),
    until: Optional[datetime] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    user=Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregated counts.

    Storage is per-minute. We bucket up to hour/day on read via PG
    `date_trunc`.
    """
    if not since:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
    if not until:
        until = datetime.now(timezone.utc)

    if granularity == "minute":
        ts_expr = PeopleCount.bucket_ts
    else:
        ts_expr = func.date_trunc(granularity, PeopleCount.bucket_ts)

    stmt = (
        select(
            ts_expr.label("bucket_ts"),
            PeopleCount.zone_id,
            PeopleCount.camera_id,
            func.sum(PeopleCount.in_count).label("in_count"),
            func.sum(PeopleCount.out_count).label("out_count"),
            func.max(PeopleCount.occupancy).label("occupancy"),
            func.sum(PeopleCount.crowd_alerts).label("crowd_alerts"),
        )
        .where(PeopleCount.bucket_ts >= since, PeopleCount.bucket_ts <= until)
        .group_by(ts_expr, PeopleCount.zone_id, PeopleCount.camera_id)
        .order_by(ts_expr.desc())
        .limit(limit)
    )
    if camera_id:
        stmt = stmt.where(PeopleCount.camera_id == camera_id)
    if zone_id:
        stmt = stmt.where(PeopleCount.zone_id == zone_id)

    result = await db.execute(stmt)
    rows = result.all()
    return [
        CountBucket(
            bucket_ts=r.bucket_ts,
            zone_id=r.zone_id,
            camera_id=r.camera_id,
            in_count=int(r.in_count or 0),
            out_count=int(r.out_count or 0),
            occupancy=int(r.occupancy or 0),
            crowd_alerts=int(r.crowd_alerts or 0),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Active config bootstrap for DeepStream workers
# ---------------------------------------------------------------------------


class ActiveCamera(BaseModel):
    id: str
    name: str
    main_stream_url: str
    sub_stream_url: Optional[str] = None
    resolution: Optional[str] = None


class ActiveBundle(BaseModel):
    scenario: str
    cameras: List[ActiveCamera]
    zones: List[ZoneOut]


async def _publish_reload(channel: str = "ai:control:reload") -> None:
    """Best-effort Redis pubsub signal so DeepStream workers reload
    config without restart. No-op if Redis disabled."""
    from app.config import settings as _s
    if not _s.REDIS_URL:
        return
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(_s.REDIS_URL, decode_responses=True)
        await r.publish(channel, "reload")
        await r.aclose()
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug("publish_reload failed: %s", e)


@control_router.get("/cameras/active", response_model=ActiveBundle)
async def active_cameras(
    scenario: str = Query("people_counting"),
    user=Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    """DeepStream worker bootstrap. Returns cameras with the scenario
    enabled + all their zones."""
    from app.cameras.models import Camera
    from app.ai.models import CameraAIConfig, AIScenario

    sc = (await db.execute(
        select(AIScenario).where(AIScenario.slug == scenario)
    )).scalar_one_or_none()
    if not sc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown scenario '{scenario}'")

    # License gate — DS workers poll this; an unlicensed scenario returns
    # an empty camera list so the worker stays idle (zero side-effects).
    from app.license.service import get_license_service
    lic = get_license_service()
    if lic.is_active() and not lic.is_scenario_licensed(scenario):
        return ActiveBundle(scenario=scenario, cameras=[], zones=[])

    cam_q = (
        select(Camera)
        .join(CameraAIConfig, CameraAIConfig.camera_id == Camera.id)
        .where(
            CameraAIConfig.scenario_id == sc.id,
            CameraAIConfig.enabled.is_(True),
            Camera.is_enabled.is_(True),
        )
    )
    cameras = (await db.execute(cam_q)).scalars().unique().all()
    cam_ids = [c.id for c in cameras]

    zones: List[PeopleCountZone] = []
    if cam_ids:
        z_res = await db.execute(
            select(PeopleCountZone)
            .where(PeopleCountZone.camera_id.in_(cam_ids))
            .where(PeopleCountZone.enabled.is_(True))
        )
        zones = list(z_res.scalars().all())

    return ActiveBundle(
        scenario=scenario,
        cameras=[
            ActiveCamera(
                id=c.id,
                name=c.name,
                main_stream_url=c.main_stream_url,
                sub_stream_url=c.sub_stream_url,
                resolution=c.resolution,
            )
            for c in cameras
        ],
        zones=zones,
    )


@control_router.post("/control/reload", status_code=200)
async def trigger_reload(
    user=Depends(require_permission("manage_camera")),
):
    """Operator-triggered reload signal. DeepStream workers re-pull
    /cameras/active and update analytics state without restarting."""
    await _publish_reload()
    return {"status": "ok"}


class LiveSnapshot(BaseModel):
    zone_id: str
    camera_id: str
    name: str
    scenario: str
    threshold: Optional[int]
    in_today: int
    out_today: int
    occupancy: int
    alerts_today: int


@router.get("/live", response_model=List[LiveSnapshot])
async def live_snapshot(
    user=Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    """Compact per-zone snapshot for the live dashboard."""
    # bucket_ts column is tz-naive UTC — keep this naive too.
    today_start = datetime.utcnow().replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    stmt = (
        select(
            PeopleCountZone.id,
            PeopleCountZone.camera_id,
            PeopleCountZone.name,
            PeopleCountZone.scenario,
            PeopleCountZone.threshold,
            func.coalesce(func.sum(PeopleCount.in_count), 0).label("in_today"),
            func.coalesce(func.sum(PeopleCount.out_count), 0).label("out_today"),
            func.coalesce(func.max(PeopleCount.occupancy), 0).label("occupancy"),
            func.coalesce(func.sum(PeopleCount.crowd_alerts), 0).label("alerts_today"),
        )
        .select_from(PeopleCountZone)
        .outerjoin(
            PeopleCount,
            (PeopleCount.zone_id == PeopleCountZone.id)
            & (PeopleCount.bucket_ts >= today_start),
        )
        .where(PeopleCountZone.enabled.is_(True))
        .group_by(
            PeopleCountZone.id,
            PeopleCountZone.camera_id,
            PeopleCountZone.name,
            PeopleCountZone.scenario,
            PeopleCountZone.threshold,
        )
    )
    result = await db.execute(stmt)
    return [
        LiveSnapshot(
            zone_id=r.id,
            camera_id=r.camera_id,
            name=r.name,
            scenario=r.scenario,
            threshold=r.threshold,
            in_today=int(r.in_today),
            out_today=int(r.out_today),
            occupancy=int(r.occupancy),
            alerts_today=int(r.alerts_today),
        )
        for r in result.all()
    ]
