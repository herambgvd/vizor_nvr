# =============================================================================
# Imaging Sub-Router — ONVIF imaging settings and focus
# Mounted under: /cameras
# =============================================================================

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.cameras.service import CameraService
from app.cameras.onvif_service import onvif_service
from app.core.dependencies import require_permission
from app.cameras.onvif_creds import onvif_credentials
from app.core.audit_logger import write_audit, client_ip

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Imaging"])
svc = CameraService()


@router.get("/{camera_id}/imaging")
async def get_imaging(
    camera_id: str,
    user: dict = Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
):
    """Get current imaging settings (brightness, contrast, WDR, day/night mode)."""
    camera = await svc.get_by_id(db, camera_id)
    if not camera or not camera.onvif_host:
        raise HTTPException(404, "Camera not found or no ONVIF configured")
    onvif_user, onvif_pass = onvif_credentials(camera)
    settings_data = await onvif_service.get_imaging_settings(
        camera.onvif_host, camera.onvif_port, onvif_user, onvif_pass,
    )
    options = await onvif_service.get_imaging_options(
        camera.onvif_host, camera.onvif_port, onvif_user, onvif_pass,
    )
    return {"camera_id": camera_id, "settings": settings_data, "options": options}


@router.put("/{camera_id}/imaging")
async def update_imaging(
    camera_id: str,
    request: Request,
    user: dict = Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
):
    """
    Update imaging settings.
    Body: {"brightness": 50, "contrast": 50, "ir_cut_filter": "AUTO", "wide_dynamic_range": {"mode": "ON", "level": 50}}
    """
    camera = await svc.get_by_id(db, camera_id)
    if not camera or not camera.onvif_host:
        raise HTTPException(404, "Camera not found or no ONVIF configured")
    body = await request.json()
    onvif_user, onvif_pass = onvif_credentials(camera)
    ok = await onvif_service.set_imaging_settings(
        camera.onvif_host, camera.onvif_port, onvif_user, onvif_pass,
        settings_patch=body,
    )
    if not ok:
        raise HTTPException(500, "Failed to apply imaging settings")
    await write_audit(
        db, action="imaging_update", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
        details=body,
    )
    await db.commit()
    return {"camera_id": camera_id, "applied": body}


@router.post("/{camera_id}/imaging/focus")
async def trigger_autofocus(
    camera_id: str,
    user: dict = Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
):
    """Trigger autofocus on the camera."""
    camera = await svc.get_by_id(db, camera_id)
    if not camera or not camera.onvif_host:
        raise HTTPException(404, "Camera not found or no ONVIF configured")
    onvif_user, onvif_pass = onvif_credentials(camera)
    ok = await onvif_service.move_focus(
        camera.onvif_host, camera.onvif_port, onvif_user, onvif_pass,
        mode="Auto",
    )
    return {"camera_id": camera_id, "autofocus_triggered": ok}
