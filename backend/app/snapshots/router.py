# =============================================================================
# Snapshots Router — per-camera scheduled snapshot config + gallery
# =============================================================================

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_admin_user
from app.database import get_db

router = APIRouter(prefix="/cameras", tags=["Snapshots"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class SnapshotConfig(BaseModel):
    enabled: bool = False
    interval_seconds: int = Field(default=60, ge=0)
    retention_days: Optional[int] = Field(default=None, ge=1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_camera(db: AsyncSession, camera_id: str):
    from app.cameras.models import Camera
    from sqlalchemy import select
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    cam = result.scalar_one_or_none()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    return cam


# ---------------------------------------------------------------------------
# Scheduled snapshot config
# ---------------------------------------------------------------------------

@router.get("/{camera_id}/snapshots/scheduled")
async def get_scheduled_config(
    camera_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Return scheduled snapshot configuration for a camera."""
    cam = await _get_camera(db, camera_id)
    cfg = cam.snapshot_config or {}
    return SnapshotConfig(
        enabled=cfg.get("enabled", False),
        interval_seconds=cfg.get("interval_seconds", 60),
        retention_days=cfg.get("retention_days"),
    )


@router.put("/{camera_id}/snapshots/scheduled")
async def update_scheduled_config(
    camera_id: str,
    body: SnapshotConfig,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_admin_user),
):
    """Update scheduled snapshot configuration for a camera (admin only)."""
    cam = await _get_camera(db, camera_id)
    cam.snapshot_config = body.model_dump()
    await db.commit()
    return body


# ---------------------------------------------------------------------------
# Gallery listing
# ---------------------------------------------------------------------------

@router.get("/{camera_id}/snapshots/gallery")
async def list_snapshots(
    camera_id: str,
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """List filesystem snapshots within a date range. Returns [{timestamp, url}]."""
    await _get_camera(db, camera_id)

    from_dt: Optional[datetime] = None
    to_dt: Optional[datetime] = None

    if from_:
        try:
            from_dt = datetime.fromisoformat(from_.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, "Invalid 'from' datetime")
    if to:
        try:
            to_dt = datetime.fromisoformat(to.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, "Invalid 'to' datetime")

    from app.services.snapshot_service import snapshot_service
    entries = snapshot_service.list_snapshots(
        camera_id=camera_id,
        from_dt=from_dt,
        to_dt=to_dt,
        limit=limit,
    )
    # Strip internal 'path' key before returning
    return [{"timestamp": e["timestamp"], "url": e["url"]} for e in entries]


# ---------------------------------------------------------------------------
# File streaming
# ---------------------------------------------------------------------------

@router.get("/{camera_id}/snapshots/files/{date}/{filename}")
async def get_snapshot_file(
    camera_id: str,
    date: str,
    filename: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Stream a JPEG snapshot file. Returns 404 if not found."""
    await _get_camera(db, camera_id)

    from app.services.snapshot_service import snapshot_service
    path = snapshot_service.get_snapshot_path(camera_id, date, filename)
    if path is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    return FileResponse(
        path=str(path),
        media_type="image/jpeg",
        filename=filename,
    )
