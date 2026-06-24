# =============================================================================
# License API
#
#   GET    /api/license            — current status (limits, usage, expiry)
#   GET    /api/license/fingerprint — machine fingerprint (admin only)
#   POST   /api/license/request    — license-request blob for one scenario (admin)
#   POST   /api/license/activate   — upload + verify + persist .lic
#   DELETE /api/license            — clear installed license (admin only)
# =============================================================================

from __future__ import annotations

import base64
import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_permission
from app.database import get_db
from app.license.service import LicenseError, friendly_reason, get_license_service

router = APIRouter(prefix="/api/license", tags=["License"])

# Schema version of the request blob — lets the vendor signer reject blobs from
# an incompatible NVR. Bump if the request shape changes.
LICENSE_REQUEST_VERSION = 1


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


class LicenseRequestIn(BaseModel):
    scenario: str  # scenario slug to request entitlement for (e.g. "frs", "ppe")


@router.post("/request")
async def request_license(
    body: LicenseRequestIn,
    user=Depends(require_permission("manage_system")),
    db: AsyncSession = Depends(get_db),
):
    """Build a portable license-REQUEST blob for one scenario. The operator copies
    it and sends it to the vendor, who feeds it to scripts/sign_license.py to mint a
    fingerprint-bound .lic for that scenario. No secrets in the blob — just this
    machine's fingerprint + the requested scenario, so it's safe to email.

    The request is NOT a license; it grants nothing until the signed .lic is
    activated. Decoupling request (here) from signing (vendor, offline) keeps the
    install air-gapped: no client-to-vendor network call is needed."""
    slug = (body.scenario or "").strip().lower()
    if not slug:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "scenario is required")

    # Resolve the scenario so the blob (and the operator email) carries a human
    # name + license_feature, and so we reject a request for an unknown plugin.
    name = slug
    feature = slug
    try:
        from app.ai.models import AIScenario

        row = (
            await db.execute(select(AIScenario).where(AIScenario.slug == slug))
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Unknown scenario '{slug}'."
            )
        name = row.name or slug
        feature = row.license_feature or slug
    except HTTPException:
        raise
    except Exception:
        # AI module may be disabled — fall back to the raw slug rather than 500.
        pass

    svc = get_license_service()
    payload = {
        "v": LICENSE_REQUEST_VERSION,
        "kind": "license_request",
        "fingerprint": svc.fingerprint,
        "scenario": slug,
        "license_feature": feature,
        "name": name,
    }
    blob = base64.b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).decode()
    return {
        "request": blob,
        "fingerprint": svc.fingerprint,
        "scenario": slug,
        "name": name,
        "license_feature": feature,
    }


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
