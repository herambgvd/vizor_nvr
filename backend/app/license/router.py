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
from app.license.service import LicenseError, friendly_reason, get_license_service

router = APIRouter(prefix="/api/license", tags=["License"])


async def _counts(db: AsyncSession) -> int:
    from app.cameras.models import Camera

    cam_total = (await db.execute(select(func.count(Camera.id)))).scalar() or 0
    return int(cam_total)


@router.get("")
async def get_license(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = get_license_service()
    cam = await _counts(db)
    return svc.snapshot(cam)


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
        # Translate the internal reason code to clean operator text — never
        # surface raw crypto/parse internals to the console.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, friendly_reason(str(e))
        )
    try:
        from app.config import settings
        if settings.ENABLE_AI_MODULES:
            from app.ai.core.service import ai_service
            await ai_service.sync_licensing(db)
    except Exception:
        pass
    cam = await _counts(db)
    return svc.snapshot(cam)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_license(
    user=Depends(require_permission("manage_system")),
    db: AsyncSession = Depends(get_db),
):
    from app.license.service import LICENSE_FILE

    try:
        LICENSE_FILE.unlink(missing_ok=True)
    except Exception:
        import logging

        logging.getLogger(__name__).exception("license unlink failed")
        raise HTTPException(500, "Couldn't remove the license. Please try again.")
    svc = get_license_service()
    await svc.load_persisted()
    try:
        from app.config import settings
        if settings.ENABLE_AI_MODULES:
            from app.ai.core.service import ai_service
            await ai_service.sync_licensing(db)
    except Exception:
        pass
    return None
