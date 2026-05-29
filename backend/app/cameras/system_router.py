# =============================================================================
# System Sub-Router — ONVIF system info, time, reboot, factory-default, firmware
# Mounted under: /cameras
# =============================================================================

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.cameras.service import CameraService
from app.cameras.onvif_service import onvif_service
from app.core.dependencies import require_permission, get_admin_user
from app.cameras.onvif_creds import onvif_credentials
from app.core.audit_logger import write_audit, client_ip

logger = logging.getLogger(__name__)
router = APIRouter(tags=["System"])
svc = CameraService()


@router.get("/{camera_id}/onvif-capabilities")
async def get_onvif_capabilities(
    camera_id: str,
    user: dict = Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
):
    """Query which ONVIF services/profiles this camera supports."""
    camera = await svc.get_by_id(db, camera_id)
    if not camera or not camera.onvif_host:
        raise HTTPException(404, "Camera not found or no ONVIF configured")
    onvif_user, onvif_pass = onvif_credentials(camera)
    caps = await onvif_service.get_capabilities(
        camera.onvif_host, camera.onvif_port, onvif_user, onvif_pass,
    )
    return {"camera_id": camera_id, "capabilities": caps}


@router.get("/{camera_id}/system-info")
async def get_system_info(
    camera_id: str,
    user: dict = Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
):
    """Get full device info (firmware, serial number, hardware ID)."""
    camera = await svc.get_by_id(db, camera_id)
    if not camera or not camera.onvif_host:
        raise HTTPException(404, "Camera not found or no ONVIF configured")
    onvif_user, onvif_pass = onvif_credentials(camera)
    info = await onvif_service.get_device_system_info(
        camera.onvif_host, camera.onvif_port, onvif_user, onvif_pass,
    )
    return {"camera_id": camera_id, **info}


@router.get("/{camera_id}/system-time")
async def get_camera_time(
    camera_id: str,
    user: dict = Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
):
    """Read current date/time from the camera."""
    camera = await svc.get_by_id(db, camera_id)
    if not camera or not camera.onvif_host:
        raise HTTPException(404, "Camera not found or no ONVIF configured")
    onvif_user, onvif_pass = onvif_credentials(camera)
    time_info = await onvif_service.get_camera_time(
        camera.onvif_host, camera.onvif_port, onvif_user, onvif_pass,
    )
    return {"camera_id": camera_id, **time_info}


@router.post("/{camera_id}/system-time/sync")
async def sync_camera_time(
    camera_id: str,
    request: Request,
    user: dict = Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
):
    """Sync camera clock to NVR system time (UTC)."""
    camera = await svc.get_by_id(db, camera_id)
    if not camera or not camera.onvif_host:
        raise HTTPException(404, "Camera not found or no ONVIF configured")
    onvif_user, onvif_pass = onvif_credentials(camera)
    ok = await onvif_service.sync_camera_time(
        camera.onvif_host, camera.onvif_port, onvif_user, onvif_pass,
    )
    if not ok:
        raise HTTPException(500, "Time sync failed")
    await write_audit(
        db, action="camera_time_sync", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
    )
    await db.commit()
    return {"camera_id": camera_id, "synced": True}


@router.post("/{camera_id}/reboot")
async def reboot_camera(
    camera_id: str,
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Reboot the camera via ONVIF SystemReboot (admin only)."""
    camera = await svc.get_by_id(db, camera_id)
    if not camera or not camera.onvif_host:
        raise HTTPException(404, "Camera not found or no ONVIF configured")
    try:
        onvif_user, onvif_pass = onvif_credentials(camera)
        msg = await onvif_service.reboot_camera(
            camera.onvif_host, camera.onvif_port, onvif_user, onvif_pass,
        )
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    await write_audit(
        db, action="camera_reboot", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
        severity="warning",
    )
    await db.commit()
    return {"camera_id": camera_id, "message": msg}


@router.post("/{camera_id}/factory-default")
async def factory_default_camera(
    camera_id: str,
    body: dict,
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Reset camera via ONVIF SetSystemFactoryDefault (admin only).

    Body: {"hard": false}  — Soft preserves IP config, Hard resets everything.
    """
    camera = await svc.get_by_id(db, camera_id)
    if not camera or not camera.onvif_host:
        raise HTTPException(404, "Camera not found or no ONVIF configured")
    hard = bool(body.get("hard", False))
    try:
        onvif_user, onvif_pass = onvif_credentials(camera)
        msg = await onvif_service.factory_default(
            camera.onvif_host, camera.onvif_port, onvif_user, onvif_pass,
            hard=hard,
        )
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    await write_audit(
        db, action="camera_factory_default",
        user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
        severity="warning",
        description=f"hard={hard}",
    )
    await db.commit()
    return {"camera_id": camera_id, "message": msg, "hard": hard}


@router.get("/{camera_id}/firmware/info")
async def get_firmware_info(
    camera_id: str,
    user: dict = Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
):
    """Return device info including current firmware version."""
    camera = await svc.get_by_id(db, camera_id)
    if not camera or not camera.onvif_host:
        raise HTTPException(404, "Camera not found or ONVIF not configured")
    onvif_user, onvif_pass = onvif_credentials(camera)
    info = await onvif_service.get_device_system_info(
        camera.onvif_host, camera.onvif_port, onvif_user, onvif_pass,
    )
    return {"camera_id": camera_id, **info}


@router.post("/{camera_id}/firmware/upload", status_code=202)
async def upload_firmware(
    camera_id: str,
    request: Request,
    dry_run: bool = Query(False, description="Build SOAP envelope but do not send. Returns envelope description for inspection."),
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload firmware to the camera via ONVIF UpgradeSystemFirmware.
    Accepts multipart/form-data with a 'firmware' file field.
    Returns 202 — camera will reboot during upgrade.
    """
    import tempfile
    import os as _os

    camera = await svc.get_by_id(db, camera_id)
    if not camera or not camera.onvif_host:
        raise HTTPException(404, "Camera not found or ONVIF not configured")

    form = await request.form()
    fw_file = form.get("firmware")
    if not fw_file:
        raise HTTPException(400, "firmware file required")

    firmware_bytes = await fw_file.read()
    if not firmware_bytes:
        raise HTTPException(400, "Empty firmware file")

    onvif_user, onvif_pass = onvif_credentials(camera)

    if dry_run:
        envelope_desc = {
            "soap_action": "http://www.onvif.org/ver10/device/wsdl/UpgradeSystemFirmware",
            "target_host": camera.onvif_host,
            "target_port": camera.onvif_port,
            "onvif_user": onvif_user,
            "firmware_size_bytes": len(firmware_bytes),
            "firmware_sha256": __import__("hashlib").sha256(firmware_bytes).hexdigest(),
            "method": "UpgradeSystemFirmware (primary) / SystemFirmwareUpgrade (fallback)",
            "note": "dry_run=true — SOAP call was NOT sent. No camera change occurred.",
        }
        await write_audit(
            db, action="firmware_upload_dry_run", user_id=user["id"], username=user["username"],
            ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
            severity="info",
            details={"bytes": len(firmware_bytes), "dry_run": True},
        )
        await db.commit()
        return {"dry_run": True, "camera_id": camera_id, "envelope": envelope_desc}

    result = await onvif_service.upgrade_firmware(
        camera.onvif_host, camera.onvif_port,
        onvif_user, onvif_pass,
        firmware_bytes=firmware_bytes,
    )

    await write_audit(
        db, action="firmware_upload", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
        severity="warning",
        details={"bytes": len(firmware_bytes), "result": result},
    )
    await db.commit()
    return {"camera_id": camera_id, "started": result.get("started", False), "message": result.get("message", "")}
