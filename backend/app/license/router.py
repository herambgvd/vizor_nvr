# =============================================================================
# License API
#
#   GET    /api/license            — current status (limits, usage, expiry)
#   GET    /api/license/fingerprint — machine fingerprint (admin only)
#   POST   /api/license/activate   — upload + verify + persist .lic
#   DELETE /api/license            — clear installed license (admin only)
# =============================================================================

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_permission
from app.database import get_db
from app.license.service import LicenseError, get_license_service

router = APIRouter(prefix="/api/license", tags=["License"])


async def _counts(db: AsyncSession) -> tuple[int, int]:
    from app.cameras.models import Camera
    from app.ai.models import CameraAIConfig

    cam_total = (await db.execute(select(func.count(Camera.id)))).scalar() or 0
    ai_cam_total = (
        await db.execute(
            select(func.count(func.distinct(CameraAIConfig.camera_id))).where(
                CameraAIConfig.enabled.is_(True),
            )
        )
    ).scalar() or 0
    return int(cam_total), int(ai_cam_total)


@router.get("")
async def get_license(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = get_license_service()
    cam, ai_cam = await _counts(db)
    return svc.snapshot(cam, ai_cam)


@router.get("/fingerprint")
async def get_fingerprint(user=Depends(require_permission("manage_system"))):
    svc = get_license_service()
    return {"fingerprint": svc.fingerprint}


@router.post("/activate")
async def activate_license(
    file: UploadFile = File(...),
    user=Depends(require_permission("manage_system")),
    db: AsyncSession = Depends(get_db),
):
    svc = get_license_service()
    try:
        raw = (await file.read()).decode("utf-8", errors="ignore").strip()
        await svc.activate(raw)
    except LicenseError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    cam, ai_cam = await _counts(db)
    return svc.snapshot(cam, ai_cam)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_license(user=Depends(require_permission("manage_system"))):
    from app.license.service import LICENSE_FILE

    try:
        LICENSE_FILE.unlink(missing_ok=True)
    except Exception as e:
        raise HTTPException(500, f"unlink_failed:{e}")
    svc = get_license_service()
    await svc.load_persisted()
    return None
