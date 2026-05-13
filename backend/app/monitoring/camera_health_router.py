# =============================================================================
# Camera Health Router — per-camera stream health metrics
# =============================================================================

import logging
from typing import List, Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import get_current_user, require_permission
from app.cameras.models import CameraHealthSnapshot, CameraHealthSnapshotResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/monitoring/health", tags=["Camera Health"])


@router.get("/cameras/{camera_id}", response_model=List[CameraHealthSnapshotResponse])
async def get_camera_health(
    camera_id: str,
    hours: int = 24,
    user: dict = Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    """Get health snapshots for a camera over the last N hours."""
    since = datetime.utcnow() - timedelta(hours=hours)
    result = await db.execute(
        select(CameraHealthSnapshot)
        .where(
            CameraHealthSnapshot.camera_id == camera_id,
            CameraHealthSnapshot.captured_at >= since,
        )
        .order_by(CameraHealthSnapshot.captured_at.desc())
    )
    return list(result.scalars().all())


@router.get("/cameras/{camera_id}/latest", response_model=Optional[CameraHealthSnapshotResponse])
async def get_latest_health(
    camera_id: str,
    user: dict = Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    """Get the most recent health snapshot for a camera."""
    result = await db.execute(
        select(CameraHealthSnapshot)
        .where(CameraHealthSnapshot.camera_id == camera_id)
        .order_by(CameraHealthSnapshot.captured_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


@router.get("/summary")
async def get_health_summary(
    user: dict = Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    """Get aggregate health stats for all cameras."""
    from app.cameras.models import Camera

    total = await db.execute(select(func.count()).select_from(Camera))
    online = await db.execute(
        select(func.count()).select_from(Camera).where(Camera.status == "online")
    )

    # Cameras with health issues in last hour
    since = datetime.utcnow() - timedelta(hours=1)
    recent_offline = await db.execute(
        select(func.count(func.distinct(CameraHealthSnapshot.camera_id)))
        .where(
            CameraHealthSnapshot.captured_at >= since,
            CameraHealthSnapshot.status != "online",
        )
    )

    return {
        "total_cameras": total.scalar(),
        "online_cameras": online.scalar(),
        "recent_issues": recent_offline.scalar(),
        "timestamp": datetime.utcnow().isoformat(),
    }
