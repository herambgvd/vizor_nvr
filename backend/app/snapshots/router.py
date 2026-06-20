# =============================================================================
# Snapshots Router — per-camera scheduled snapshot config + gallery
# =============================================================================

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_admin_user
from app.database import get_db

logger = logging.getLogger(__name__)

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

# ---------------------------------------------------------------------------
# Annotation
# ---------------------------------------------------------------------------

class AnnotationOperation(BaseModel):
    type: str                            # blur | rect | text | arrow
    x: float = 0.0
    y: float = 0.0
    w: Optional[float] = None
    h: Optional[float] = None
    x1: Optional[float] = None
    y1: Optional[float] = None
    x2: Optional[float] = None
    y2: Optional[float] = None
    radius: Optional[int] = None
    color: Optional[str] = None
    width: Optional[int] = None
    text: Optional[str] = None
    size: Optional[int] = None


class AnnotateRequest(BaseModel):
    source_url: str = Field(..., description="URL or path of the source snapshot JPEG")
    operations: List[AnnotationOperation] = Field(default_factory=list)


async def _fetch_source_image(source_url: str) -> bytes:
    """Fetch the source image from a local path or HTTP URL."""
    import httpx
    from app.config import settings

    # Local snapshot path — strip leading /api or /snapshots prefix
    if source_url.startswith("/cameras/") or source_url.startswith("/api/cameras/"):
        # Strip /api prefix if present
        rel = source_url.removeprefix("/api")
        # Expected pattern: /cameras/{id}/snapshots/files/{date}/{filename}
        parts = Path(rel).parts
        if len(parts) >= 6:
            date_str = parts[4]
            filename = parts[5]
            cam_id = parts[2]
            from app.services.snapshot_service import snapshot_service
            p = snapshot_service.get_snapshot_path(cam_id, date_str, filename)
            if p and Path(p).exists():
                return Path(p).read_bytes()

    # Fall back to HTTP fetch (same host, or external URL)
    if source_url.startswith("http"):
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(source_url)
            resp.raise_for_status()
            return resp.content

    raise HTTPException(status_code=400, detail=f"Cannot resolve source_url: {source_url}")


@router.post("/{camera_id}/snapshots/annotate", response_class=Response)
async def annotate_snapshot(
    camera_id: str,
    body: AnnotateRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Apply blur/rect/text/arrow annotations and return the modified JPEG."""
    await _get_camera(db, camera_id)

    image_bytes = await _fetch_source_image(body.source_url)
    ops = [op.model_dump(exclude_none=True) for op in body.operations]

    from app.snapshots.annotator import apply_operations
    try:
        result = apply_operations(image_bytes, ops)
    except RuntimeError as e:
        logger.error(f"Snapshot annotation failed: {e}")
        raise HTTPException(status_code=500, detail="Could not generate the annotated snapshot.")

    return Response(content=result, media_type="image/jpeg")


@router.post("/{camera_id}/snapshots/annotate/save")
async def annotate_and_save_snapshot(
    camera_id: str,
    body: AnnotateRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Apply annotations, persist to disk, return saved snapshot URL."""
    await _get_camera(db, camera_id)

    image_bytes = await _fetch_source_image(body.source_url)
    ops = [op.model_dump(exclude_none=True) for op in body.operations]

    from app.snapshots.annotator import apply_operations
    try:
        result = apply_operations(image_bytes, ops)
    except RuntimeError as e:
        logger.error(f"Snapshot annotation failed: {e}")
        raise HTTPException(status_code=500, detail="Could not save the annotated snapshot.")

    # Persist alongside regular snapshots
    from app.services.snapshot_service import _snapshot_base_path
    import uuid as _uuid

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"annotated_{_uuid.uuid4().hex[:8]}.jpg"

    snap_dir = _snapshot_base_path() / camera_id / today
    snap_dir.mkdir(parents=True, exist_ok=True)
    dest = snap_dir / filename
    dest.write_bytes(result)

    url = f"/cameras/{camera_id}/snapshots/files/{today}/{filename}"
    return {"url": url, "saved": True}


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
