# =============================================================================
# I/O Sub-Router — relay outputs and digital inputs
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
router = APIRouter(tags=["IO"])
svc = CameraService()


@router.get("/{camera_id}/io/outputs")
async def get_relay_outputs(
    camera_id: str,
    user: dict = Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
):
    """Get relay output definitions from camera and cache them."""
    camera = await svc.get_by_id(db, camera_id)
    if not camera or not camera.onvif_host:
        raise HTTPException(404, "Camera not found or no ONVIF configured")
    onvif_user, onvif_pass = onvif_credentials(camera)
    outputs = await onvif_service.get_relay_outputs(
        camera.onvif_host, camera.onvif_port, onvif_user, onvif_pass,
    )
    camera.relay_outputs = outputs
    await db.commit()
    return {"camera_id": camera_id, "relay_outputs": outputs}


@router.post("/{camera_id}/io/outputs/{relay_token}/trigger")
async def trigger_relay_output(
    camera_id: str,
    relay_token: str,
    request: Request,
    user: dict = Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger (or release) a relay output.
    Body: {"state": "active"} or {"state": "inactive"}
    """
    camera = await svc.get_by_id(db, camera_id)
    if not camera or not camera.onvif_host:
        raise HTTPException(404, "Camera not found or no ONVIF configured")
    body = await request.json()
    state = body.get("state", "active")
    if state not in ("active", "inactive"):
        raise HTTPException(400, "state must be 'active' or 'inactive'")
    onvif_user, onvif_pass = onvif_credentials(camera)
    ok = await onvif_service.set_relay_output_state(
        camera.onvif_host, camera.onvif_port, onvif_user, onvif_pass,
        relay_token=relay_token,
        logical_state=state,
    )
    if not ok:
        raise HTTPException(500, "Failed to trigger relay output")
    await write_audit(
        db, action="relay_output_trigger", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
        details={"relay_token": relay_token, "state": state},
    )
    await db.commit()
    return {"camera_id": camera_id, "relay_token": relay_token, "state": state}


@router.get("/{camera_id}/io/inputs")
async def get_digital_inputs(
    camera_id: str,
    user: dict = Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
):
    """Get digital input definitions from camera and cache them."""
    camera = await svc.get_by_id(db, camera_id)
    if not camera or not camera.onvif_host:
        raise HTTPException(404, "Camera not found or no ONVIF configured")
    onvif_user, onvif_pass = onvif_credentials(camera)
    inputs = await onvif_service.get_digital_inputs(
        camera.onvif_host, camera.onvif_port, onvif_user, onvif_pass,
    )
    camera.digital_inputs = inputs
    await db.commit()
    return {"camera_id": camera_id, "digital_inputs": inputs}
