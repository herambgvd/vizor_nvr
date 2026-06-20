# =============================================================================
# PTZ Sub-Router — PTZ control, presets, and PTZ tour
# Mounted under: /cameras  (prefix comes from parent router include)
# =============================================================================

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.cameras.models import PTZMoveRequest, PTZPreset
from app.cameras.service import CameraService
from app.cameras.onvif_service import onvif_service
from app.core.dependencies import require_permission, get_admin_user
from app.cameras.onvif_creds import onvif_credentials
from app.core.audit_logger import write_audit, client_ip

logger = logging.getLogger(__name__)
router = APIRouter(tags=["PTZ"])
svc = CameraService()


@router.post("/{camera_id}/ptz/move")
async def ptz_move(
    camera_id: str,
    body: PTZMoveRequest,
    user: dict = Depends(require_permission("control_ptz")),
    db: AsyncSession = Depends(get_db),
):
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    if not camera.ptz_capable or not camera.onvif_host:
        raise HTTPException(400, "Camera does not support PTZ")

    onvif_user, onvif_pass = onvif_credentials(camera, default_user="")
    ok = await onvif_service.continuous_move(
        camera.onvif_host, camera.onvif_port,
        onvif_user, onvif_pass,
        pan=body.pan, tilt=body.tilt, zoom=body.zoom, speed=body.speed,
        profile_token=camera.onvif_profile_token or None,
    )
    if not ok:
        raise HTTPException(500, "PTZ move failed")
    return {"status": "moving"}


@router.post("/{camera_id}/ptz/stop")
async def ptz_stop(
    camera_id: str,
    user: dict = Depends(require_permission("control_ptz")),
    db: AsyncSession = Depends(get_db),
):
    camera = await svc.get_by_id(db, camera_id)
    if not camera or not camera.onvif_host:
        raise HTTPException(404, "Camera not found or no ONVIF configured")

    onvif_user, onvif_pass = onvif_credentials(camera, default_user="")
    ok = await onvif_service.stop(
        camera.onvif_host, camera.onvif_port,
        onvif_user, onvif_pass,
        profile_token=camera.onvif_profile_token or None,
    )
    if not ok:
        raise HTTPException(500, "PTZ stop failed")
    return {"status": "stopped"}


@router.get("/{camera_id}/ptz/presets", response_model=List[PTZPreset])
async def ptz_presets(
    camera_id: str,
    user: dict = Depends(require_permission("control_ptz")),
    db: AsyncSession = Depends(get_db),
):
    camera = await svc.get_by_id(db, camera_id)
    if not camera or not camera.onvif_host:
        raise HTTPException(404)
    onvif_user, onvif_pass = onvif_credentials(camera, default_user="")
    presets = await onvif_service.get_presets(
        camera.onvif_host, camera.onvif_port,
        onvif_user, onvif_pass,
        profile_token=camera.onvif_profile_token or None,
    )
    camera.ptz_presets = presets
    await db.commit()
    return presets


@router.post("/{camera_id}/ptz/goto-preset")
async def ptz_goto_preset(
    camera_id: str,
    body: dict,
    request: Request,
    user: dict = Depends(require_permission("control_ptz")),
    db: AsyncSession = Depends(get_db),
):
    camera = await svc.get_by_id(db, camera_id)
    if not camera or not camera.onvif_host:
        raise HTTPException(404)
    preset_token = body.get("preset_token")
    if not preset_token:
        raise HTTPException(400, "preset_token required")
    onvif_user, onvif_pass = onvif_credentials(camera, default_user="")
    ok = await onvif_service.goto_preset(
        camera.onvif_host, camera.onvif_port,
        onvif_user, onvif_pass,
        preset_token,
        profile_token=camera.onvif_profile_token or None,
    )
    if not ok:
        raise HTTPException(500, "Failed to goto preset")
    await write_audit(
        db, action="ptz_preset_goto", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
        details={"preset_token": preset_token},
    )
    await db.commit()
    return {"status": "ok"}


@router.post("/{camera_id}/ptz/presets", response_model=PTZPreset)
async def ptz_save_preset(
    camera_id: str,
    body: dict,
    request: Request,
    user: dict = Depends(require_permission("control_ptz")),
    db: AsyncSession = Depends(get_db),
):
    """Save current PTZ position as a new preset."""
    camera = await svc.get_by_id(db, camera_id)
    if not camera or not camera.onvif_host:
        raise HTTPException(404, "Camera not found or no ONVIF configured")

    preset_name = body.get("name")
    if not preset_name:
        raise HTTPException(400, "name required")

    onvif_user, onvif_pass = onvif_credentials(camera, default_user="")
    token = await onvif_service.set_preset(
        camera.onvif_host, camera.onvif_port,
        onvif_user, onvif_pass,
        preset_name,
        profile_token=camera.onvif_profile_token or None,
    )
    if not token:
        raise HTTPException(500, "Failed to save preset")

    presets = await onvif_service.get_presets(
        camera.onvif_host, camera.onvif_port,
        onvif_user, onvif_pass,
        profile_token=camera.onvif_profile_token or None,
    )
    camera.ptz_presets = presets

    await write_audit(
        db, action="ptz_preset_save", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
        details={"preset_name": preset_name, "preset_token": token},
    )
    await db.commit()
    return {"token": token, "name": preset_name}


@router.delete("/{camera_id}/ptz/presets/{preset_token}", status_code=204)
async def ptz_delete_preset(
    camera_id: str,
    preset_token: str,
    request: Request,
    user: dict = Depends(require_permission("control_ptz")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a PTZ preset by its token."""
    camera = await svc.get_by_id(db, camera_id)
    if not camera or not camera.onvif_host:
        raise HTTPException(404, "Camera not found or no ONVIF configured")

    onvif_user, onvif_pass = onvif_credentials(camera, default_user="")
    ok = await onvif_service.delete_preset(
        camera.onvif_host, camera.onvif_port,
        onvif_user, onvif_pass,
        preset_token,
        profile_token=camera.onvif_profile_token or None,
    )
    if not ok:
        raise HTTPException(500, "Failed to delete preset")

    presets = await onvif_service.get_presets(
        camera.onvif_host, camera.onvif_port,
        onvif_user, onvif_pass,
        profile_token=camera.onvif_profile_token or None,
    )
    camera.ptz_presets = presets

    await write_audit(
        db, action="ptz_preset_delete", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
        details={"preset_token": preset_token},
    )
    await db.commit()


# ── PTZ Tour ────────────────────────────────────────────────────────────────

@router.get("/{camera_id}/ptz/tour")
async def get_ptz_tour(
    camera_id: str,
    user: dict = Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
):
    """Return current PTZ tour config and running state."""
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    from app.services.ptz_tour_service import ptz_tour_service
    running = camera_id in ptz_tour_service._tours and not ptz_tour_service._tours[camera_id].done()
    return {
        "camera_id": camera_id,
        "ptz_tour_enabled": getattr(camera, "ptz_tour_enabled", False) or False,
        "ptz_tour_config": getattr(camera, "ptz_tour_config", None) or {},
        "running": running,
    }


@router.put("/{camera_id}/ptz/tour")
async def upsert_ptz_tour(
    camera_id: str,
    body: dict,
    request: Request,
    user: dict = Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
):
    """Upsert PTZ tour config. Body: {presets:[{token, dwell_seconds}], loop:bool}"""
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    presets = body.get("presets", [])
    loop = bool(body.get("loop", True))
    camera.ptz_tour_config = {"presets": presets, "loop": loop}
    await write_audit(
        db, action="ptz_tour_config", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
    )
    await db.commit()
    return {"camera_id": camera_id, "ptz_tour_config": camera.ptz_tour_config}


@router.post("/{camera_id}/ptz/tour/start")
async def start_ptz_tour(
    camera_id: str,
    request: Request,
    user: dict = Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
):
    """Enable PTZ tour for this camera (service polls every 5 s)."""
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    if not camera.ptz_capable or not camera.onvif_host:
        raise HTTPException(400, "Camera does not support PTZ or ONVIF not configured")
    config = getattr(camera, "ptz_tour_config", None) or {}
    if not config.get("presets"):
        raise HTTPException(400, "No tour presets configured — PUT /ptz/tour first")
    camera.ptz_tour_enabled = True
    await write_audit(
        db, action="ptz_tour_start", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
    )
    await db.commit()
    return {"camera_id": camera_id, "ptz_tour_enabled": True}


@router.post("/{camera_id}/ptz/tour/stop")
async def stop_ptz_tour(
    camera_id: str,
    request: Request,
    user: dict = Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
):
    """Disable PTZ tour for this camera."""
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    camera.ptz_tour_enabled = False
    await write_audit(
        db, action="ptz_tour_stop", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
    )
    await db.commit()
    return {"camera_id": camera_id, "ptz_tour_enabled": False}
