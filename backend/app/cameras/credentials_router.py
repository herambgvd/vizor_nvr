# =============================================================================
# Credentials Sub-Router — ONVIF credential rotation
# Mounted under: /cameras
# =============================================================================

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.cameras.service import CameraService
from app.cameras.onvif_service import onvif_service
from app.core.dependencies import get_admin_user
from app.core.crypto import decrypt_value
from app.core.audit_logger import write_audit, client_ip

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Credentials"])
svc = CameraService()


@router.post("/{camera_id}/credentials/rotate")
async def rotate_credentials(
    camera_id: str,
    body: dict,
    request: Request,
    dry_run: bool = Query(False, description="Return the SetUser SOAP envelope description without sending."),
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Rotate ONVIF user password. Body: {"new_password": "..."}
    Updates camera DB row and re-registers go2rtc stream with new credentials.
    """
    new_pass = (body.get("new_password") or "").strip()
    if len(new_pass) < 8:
        raise HTTPException(400, "new_password must be at least 8 characters")

    camera = await svc.get_by_id(db, camera_id)
    if not camera or not camera.onvif_host:
        raise HTTPException(404, "Camera not found or ONVIF not configured")

    current_user = decrypt_value(camera.onvif_username) if camera.onvif_username else "admin"
    current_pass = decrypt_value(camera.onvif_password) if camera.onvif_password else ""

    # RECOVERY PROCEDURE (partial-success failure scenario):
    # If set_user_password succeeds on the camera but the DB commit below fails,
    # the camera now uses new_pass but the NVR still stores the old encrypted
    # password. The operator would be locked out of the camera via the NVR until
    # the stored credential is corrected. Recovery steps:
    #   1. Re-run POST /cameras/{id}/credentials/rotate with the SAME new_password
    #      once connectivity is restored — set_user_password is idempotent and the
    #      camera will accept the already-current password, letting the DB catch up.
    #      OR manually correct the stored value:
    #      UPDATE cameras SET onvif_password = '<encrypt(new_pass)>' WHERE id = '<camera_id>';
    #   2. POST /cameras/{id}/audio/backchannel/recheck to clear the capability cache.
    #   3. GET /cameras/{id}/onvif/probe to verify connectivity with the new credential.

    if dry_run:
        envelope_desc = {
            "soap_action": "http://www.onvif.org/ver10/device/wsdl/SetUser",
            "target_host": camera.onvif_host,
            "target_port": camera.onvif_port,
            "onvif_user": current_user,
            "method": "DeviceManagement SetUser",
            "user_token": f"user:{current_user}",
            "new_password_length": len(new_pass),
            "user_level": "Administrator",
            "note": "dry_run=true — SOAP call was NOT sent. No camera change occurred.",
            "recovery_hint": (
                "If the live rotate succeeds on the camera but the NVR DB commit fails, "
                "use the recovery steps documented in credentials_router.rotate_credentials."
            ),
        }
        await write_audit(
            db, action="credentials_rotate_dry_run", user_id=user["id"], username=user["username"],
            ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
            severity="info",
            details={"dry_run": True, "new_password_length": len(new_pass)},
        )
        await db.commit()
        return {"dry_run": True, "camera_id": camera_id, "envelope": envelope_desc}

    ok = await onvif_service.set_user_password(
        camera.onvif_host, camera.onvif_port,
        current_user, current_pass, new_pass,
    )
    if not ok:
        raise HTTPException(500, "Failed to rotate camera password via ONVIF")

    from app.core.crypto import encrypt_value
    camera.onvif_password = encrypt_value(new_pass)

    if camera.main_stream_url:
        from app.services.go2rtc_manager import go2rtc_manager
        from urllib.parse import urlparse, quote as _q

        def _inject_creds(url: str, username: str, password: str) -> str:
            if "://" not in url:
                return url
            parsed = urlparse(url)
            netloc = f"{_q(username, safe='')}:{_q(password, safe='')}@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return parsed._replace(netloc=netloc).geturl()

        new_main = _inject_creds(camera.main_stream_url, current_user, new_pass)
        camera.main_stream_url = new_main
        await go2rtc_manager.add_stream(camera_id, new_main, dewarp_config=camera.dewarp_config)
        if camera.sub_stream_url:
            new_sub = _inject_creds(camera.sub_stream_url, current_user, new_pass)
            camera.sub_stream_url = new_sub
            await go2rtc_manager.add_stream(f"{camera_id}_sub", new_sub, dewarp_config=camera.dewarp_config)

    await write_audit(
        db, action="credentials_rotate", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
        severity="warning",
    )
    await db.commit()
    return {"camera_id": camera_id, "rotated": True, "username": current_user}
