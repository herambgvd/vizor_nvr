# =============================================================================
# Camera Router — CRUD, recording control, streams, groups, ONVIF, PTZ
# =============================================================================

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.cameras.models import (
    CameraCreate, CameraUpdate, CameraResponse,
    CameraGroupCreate, CameraGroupUpdate, CameraGroupResponse,
    StreamUrlsResponse, PTZMoveRequest, PTZPreset,
    ONVIFDiscoveryResult,
)
from app.cameras.service import CameraService
from app.cameras.onvif_service import onvif_service
from app.cameras.twoway_audio_service import twoway_audio_service
from app.core.dependencies import get_current_user, require_permission, get_admin_user
from app.core.crypto import decrypt_value
from app.core.permissions import get_accessible_camera_ids
from app.core.audit_logger import write_audit, client_ip

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cameras", tags=["Cameras"])
svc = CameraService()


# ══════════════════════════════════════════════════════════════════════
# Camera CRUD
# ══════════════════════════════════════════════════════════════════════

@router.get("", response_model=List[CameraResponse])
async def list_cameras(
    user: dict = Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    """List cameras the current user has access to."""
    camera_ids = await get_accessible_camera_ids(db, user)
    cameras = await svc.get_all(db, camera_ids)

    # Patch live recording status from FFmpeg manager
    from app.services.ffmpeg_manager import ffmpeg_manager
    return [
        CameraResponse(
            **{**svc.to_response(c), "is_recording": ffmpeg_manager.is_recording(c.id)}
        )
        for c in cameras
    ]


# ══════════════════════════════════════════════════════════════════════
# ONVIF Discovery  (must be registered BEFORE /{camera_id} routes)
# ══════════════════════════════════════════════════════════════════════

@router.post("/onvif/discover", response_model=List[ONVIFDiscoveryResult])
async def onvif_discover(
    subnet: str | None = None,
    timeout: int = 5,
    username: str | None = None,
    password: str | None = None,
    user: dict = Depends(require_permission("manage_camera")),
):
    """Scan LAN for ONVIF cameras.

    Tries WS-Discovery multicast first. Falls back to a TCP port-probe
    of common ONVIF service ports across every host in `subnet`. If
    `subnet` is omitted, auto-detects from the backend's default route
    (which inside Docker bridge mode is the bridge network — pass an
    explicit `subnet=192.168.1.0/24` to scan the host LAN instead).

    `username` + `password` are used to fetch device metadata after a
    host is detected. Without them many ONVIF devices return 401 and
    the result row stays unlabeled.
    """
    try:
        devices = await onvif_service.discover(
            timeout=timeout,
            subnet=subnet,
            username=username,
            password=password,
        )
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    return devices


@router.post("/onvif/probe")
async def onvif_probe(
    body: dict,
    user: dict = Depends(require_permission("manage_camera")),
):
    """
    Probe a specific IP for ONVIF info and stream URIs.
    Body: {"host": "192.168.1.100", "port": 80, "username": "admin", "password": "pass"}
    """
    host = body.get("host")
    port = body.get("port", 80)
    username = body.get("username", "admin")
    password = body.get("password", "admin")
    if not host:
        raise HTTPException(400, "host required")

    info = await onvif_service.get_device_info(host, port, username, password)
    uris = await onvif_service.get_stream_uris(host, port, username, password)
    ptz = await onvif_service.check_ptz_capable(host, port, username, password)

    # Build fallback RTSP URL if ONVIF stream URI query failed
    if not uris.get("main_stream_url"):
        cred = f"{username}:{password}@" if username else ""
        uris["main_stream_url"] = f"rtsp://{cred}{host}:554/stream1"

    return {
        **(info or {}),
        **uris,
        "ptz_capable": ptz,
        "ip": host,
        "port": port,
    }


@router.post("/onvif/snapshot")
async def onvif_snapshot(
    body: dict,
    user: dict = Depends(require_permission("manage_camera")),
):
    """Return a JPEG snapshot from a not-yet-onboarded ONVIF camera.

    Body: {"host", "port", "username", "password"}
    Used by the discovery dialog to render per-row thumbnails so the
    operator can visually confirm which device they're adding.
    """
    from fastapi.responses import Response

    host = body.get("host")
    port = int(body.get("port") or 80)
    username = body.get("username") or "admin"
    password = body.get("password") or "admin"
    if not host:
        raise HTTPException(400, "host required")

    jpeg = await onvif_service.fetch_snapshot(host, port, username, password)
    if not jpeg:
        raise HTTPException(404, "snapshot not available")
    return Response(content=jpeg, media_type="image/jpeg")


# ══════════════════════════════════════════════════════════════════════
# Camera Groups  (must be registered BEFORE /{camera_id} routes)
# ══════════════════════════════════════════════════════════════════════

@router.get("/groups", response_model=List[CameraGroupResponse])
async def list_groups(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    groups = await svc.get_all_groups(db)
    return [
        CameraGroupResponse(
            id=g.id, name=g.name, description=g.description, color=g.color,
            camera_ids=[c.id for c in g.cameras] if g.cameras else [],
            created_at=g.created_at,
        )
        for g in groups
    ]


@router.post("/groups", response_model=CameraGroupResponse, status_code=201)
async def create_group(
    data: CameraGroupCreate,
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    group = await svc.create_group(db, data)
    await write_audit(
        db, action="group_create", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="camera_group", resource_id=group.id,
    )
    await db.commit()
    return CameraGroupResponse(
        id=group.id, name=group.name, description=group.description, color=group.color,
        camera_ids=[c.id for c in group.cameras] if group.cameras else [],
        created_at=group.created_at,
    )


@router.put("/groups/{group_id}", response_model=CameraGroupResponse)
async def update_group(
    group_id: str,
    data: CameraGroupUpdate,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    group = await svc.update_group(db, group_id, data)
    if not group:
        raise HTTPException(404, "Group not found")
    return CameraGroupResponse(
        id=group.id, name=group.name, description=group.description, color=group.color,
        camera_ids=[c.id for c in group.cameras] if group.cameras else [],
        created_at=group.created_at,
    )


@router.delete("/groups/{group_id}", status_code=204)
async def delete_group(
    group_id: str,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    if not await svc.delete_group(db, group_id):
        raise HTTPException(404, "Group not found")


# ── User ↔ Group access (admin) ──────────────────────────────────

@router.post("/groups/{group_id}/users/{user_id}", status_code=204)
async def grant_user_to_group(
    group_id: str,
    user_id: str,
    request: Request,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    await svc.grant_user_group(db, user_id, group_id)
    await write_audit(
        db, action="access_grant", user_id=admin["id"], username=admin["username"],
        ip_address=client_ip(request), resource_type="camera_group", resource_id=group_id,
        details={"target_user_id": user_id},
    )
    await db.commit()


@router.delete("/groups/{group_id}/users/{user_id}", status_code=204)
async def revoke_user_from_group(
    group_id: str,
    user_id: str,
    request: Request,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    await svc.revoke_user_group(db, user_id, group_id)
    await write_audit(
        db, action="access_revoke", user_id=admin["id"], username=admin["username"],
        ip_address=client_ip(request), resource_type="camera_group", resource_id=group_id,
        details={"target_user_id": user_id},
    )
    await db.commit()


# ══════════════════════════════════════════════════════════════════════
# Camera CRUD — single camera  (/{camera_id} routes)
# ══════════════════════════════════════════════════════════════════════

@router.get("/{camera_id}", response_model=CameraResponse)
async def get_camera(
    camera_id: str,
    user: dict = Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    return CameraResponse(**svc.to_response(camera))


@router.post("", response_model=CameraResponse, status_code=201)
async def create_camera(
    data: CameraCreate,
    request: Request,
    bg: BackgroundTasks,
    user: dict = Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
):
    # License-file tier enforcement (Phase 7.2). Fall back to the legacy
    # settings.max_cameras cap if no license file is present.
    from app.core.licensing import enforce_camera_count
    from app.settings.service import SettingsService
    current = await svc.count(db)
    try:
        enforce_camera_count(current)
    except ValueError as e:
        raise HTTPException(403, str(e))
    settings_cap = await SettingsService.get_max_cameras(db)
    if current >= settings_cap:
        raise HTTPException(403, f"Operator cap: max {settings_cap} cameras")

    camera = await svc.create(db, data)

    await write_audit(
        db, action="camera_create", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="camera", resource_id=camera.id,
        description=f"Camera created: {camera.name}",
    )
    await db.commit()

    # Test connection in background
    bg.add_task(_bg_test_connection, camera.id)

    return CameraResponse(**svc.to_response(camera))


@router.put("/{camera_id}", response_model=CameraResponse)
async def update_camera(
    camera_id: str,
    data: CameraUpdate,
    request: Request,
    user: dict = Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
):
    camera = await svc.update(db, camera_id, data)
    if not camera:
        raise HTTPException(404, "Camera not found")

    # Re-register streams with go2rtc if stream URLs were changed
    changes = data.model_dump(exclude_unset=True)
    if any(k in changes for k in ("main_stream_url", "sub_stream_url", "username", "password", "ip_address", "port")):
        from app.services.go2rtc_manager import go2rtc_manager
        if camera.main_stream_url:
            await go2rtc_manager.add_stream(camera_id, camera.main_stream_url)
        if camera.sub_stream_url:
            await go2rtc_manager.add_stream(f"{camera_id}_sub", camera.sub_stream_url)

    await write_audit(
        db, action="camera_update", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
        details={"changes": changes},
    )
    await db.commit()
    return CameraResponse(**svc.to_response(camera))


@router.delete("/{camera_id}", status_code=204)
async def delete_camera(
    camera_id: str,
    request: Request,
    user: dict = Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
):
    # Stop recording first
    from app.services.ffmpeg_manager import ffmpeg_manager
    from app.services.go2rtc_manager import go2rtc_manager
    await ffmpeg_manager.stop_recording(camera_id)
    await go2rtc_manager.remove_stream(camera_id)
    await go2rtc_manager.remove_stream(f"{camera_id}_sub")

    if not await svc.delete(db, camera_id):
        raise HTTPException(404, "Camera not found")

    await write_audit(
        db, action="camera_delete", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
        severity="warning",
    )
    await db.commit()


# ══════════════════════════════════════════════════════════════════════
# Recording control
# ══════════════════════════════════════════════════════════════════════

@router.post("/{camera_id}/start-recording")
async def start_recording(
    camera_id: str,
    request: Request,
    user: dict = Depends(require_permission("control_recording")),
    db: AsyncSession = Depends(get_db),
):
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    if not camera.is_enabled:
        raise HTTPException(400, "Camera is disabled")

    from app.services.go2rtc_manager import go2rtc_manager
    from app.services.ffmpeg_manager import ffmpeg_manager

    # Register main stream with go2rtc and wait for it to be ready
    await go2rtc_manager.add_stream(camera_id, camera.main_stream_url)
    if camera.sub_stream_url:
        await go2rtc_manager.add_stream(f"{camera_id}_sub", camera.sub_stream_url)

    # Wait for go2rtc to pull the RTSP stream before FFmpeg connects
    await go2rtc_manager.wait_for_stream_ready(camera_id)

    rtsp_url = go2rtc_manager.get_rtsp_output_url(camera_id)

    # Resolve storage path
    from app.storage.service import StorageService
    storage_path = await StorageService.resolve_recording_path(db, camera)

    success, msg = await ffmpeg_manager.start_recording(
        camera_id=camera.id,
        rtsp_url=rtsp_url,
        storage_path=storage_path,
        recording_fps=camera.recording_fps,
        sub_stream_url=go2rtc_manager.get_rtsp_output_url(f"{camera_id}_sub") if camera.sub_stream_url else None,
        privacy_masks=camera.privacy_masks,
    )
    if not success:
        raise HTTPException(500, f"Failed to start recording: {msg}")

    camera.is_recording = True
    camera.status = "online"
    camera.last_online_at = datetime.utcnow()
    await db.commit()

    await write_audit(
        db, action="recording_start", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
    )
    await db.commit()
    return {"message": "Recording started", "path": msg}


@router.post("/{camera_id}/stop-recording")
async def stop_recording(
    camera_id: str,
    request: Request,
    user: dict = Depends(require_permission("control_recording")),
    db: AsyncSession = Depends(get_db),
):
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")

    from app.services.ffmpeg_manager import ffmpeg_manager
    await ffmpeg_manager.stop_recording(camera_id)
    camera.is_recording = False
    await db.commit()

    await write_audit(
        db, action="recording_stop", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
    )
    await db.commit()
    return {"message": "Recording stopped"}


# ══════════════════════════════════════════════════════════════════════
# Stream URLs
# ══════════════════════════════════════════════════════════════════════

@router.get("/{camera_id}/stream-urls", response_model=StreamUrlsResponse)
async def get_stream_urls(
    camera_id: str,
    user: dict = Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")

    from app.services.go2rtc_manager import go2rtc_manager

    # Register streams with go2rtc
    await go2rtc_manager.add_stream(camera_id, camera.main_stream_url)
    if camera.sub_stream_url:
        await go2rtc_manager.add_stream(f"{camera_id}_sub", camera.sub_stream_url)

    # For live viewing, prefer sub stream (lower bandwidth)
    live_id = f"{camera_id}_sub" if camera.sub_stream_url else camera_id

    return StreamUrlsResponse(
        camera_id=camera_id,
        live_stream_id=live_id,
        webrtc_url=go2rtc_manager.get_webrtc_url(live_id),
        mse_url=go2rtc_manager.get_mse_url(live_id),
        snapshot_url=go2rtc_manager.get_snapshot_url(live_id),
    )


@router.post("/{camera_id}/test-connection")
async def test_connection(
    camera_id: str,
    user: dict = Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
):
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")

    from app.services.ffmpeg_manager import ffmpeg_manager
    from app.services.go2rtc_manager import go2rtc_manager
    success, info = await ffmpeg_manager.test_rtsp_connection(camera.main_stream_url)

    if success:
        camera.status = "online"
        camera.last_online_at = datetime.utcnow()
        if info:
            camera.resolution = info.get("resolution")
            camera.fps = info.get("fps")
            camera.bitrate = info.get("bitrate")

        # Register streams with go2rtc so WebRTC/MSE work immediately
        await go2rtc_manager.add_stream(camera_id, camera.main_stream_url)
        if camera.sub_stream_url:
            await go2rtc_manager.add_stream(f"{camera_id}_sub", camera.sub_stream_url)

        await db.commit()
        return {"status": "online", "stream_info": info}
    else:
        camera.status = "offline"
        await db.commit()
        raise HTTPException(400, "Connection failed — verify RTSP URL and camera is reachable")


@router.post("/{camera_id}/snapshot")
async def capture_snapshot(
    camera_id: str,
    user: dict = Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")

    from app.services.ffmpeg_manager import ffmpeg_manager
    path = await ffmpeg_manager.capture_snapshot(camera.main_stream_url, camera_id)
    if path:
        camera.thumbnail_path = path
        await db.commit()
        return {"path": path}
    raise HTTPException(500, "Snapshot failed")


# ══════════════════════════════════════════════════════════════════════
# WebRTC signalling proxy
# ══════════════════════════════════════════════════════════════════════

@router.post("/{camera_id}/webrtc-signal")
async def webrtc_signal(
    camera_id: str,
    request: Request,
    user: dict = Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")

    from app.services.go2rtc_manager import go2rtc_manager
    await go2rtc_manager.add_stream(camera_id, camera.main_stream_url)
    if camera.sub_stream_url:
        await go2rtc_manager.add_stream(f"{camera_id}_sub", camera.sub_stream_url)

    body = await request.json()
    live_id = f"{camera_id}_sub" if camera.sub_stream_url else camera_id
    answer = await go2rtc_manager.webrtc_signal(live_id, body.get("sdp", ""))
    if answer is None:
        raise HTTPException(500, "WebRTC signalling failed")
    return {"sdp": answer}


# ══════════════════════════════════════════════════════════════════════
# PTZ Control
# ══════════════════════════════════════════════════════════════════════

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

    ok = await onvif_service.continuous_move(
        camera.onvif_host, camera.onvif_port,
        decrypt_value(camera.onvif_username) or "", decrypt_value(camera.onvif_password or ""),
        pan=body.pan, tilt=body.tilt, zoom=body.zoom, speed=body.speed,
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

    await onvif_service.stop(
        camera.onvif_host, camera.onvif_port,
        decrypt_value(camera.onvif_username) or "", decrypt_value(camera.onvif_password or ""),
    )
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
    presets = await onvif_service.get_presets(
        camera.onvif_host, camera.onvif_port,
        decrypt_value(camera.onvif_username) or "", decrypt_value(camera.onvif_password or ""),
    )
    # Also update DB cache
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
    ok = await onvif_service.goto_preset(
        camera.onvif_host, camera.onvif_port,
        decrypt_value(camera.onvif_username) or "", decrypt_value(camera.onvif_password or ""),
        preset_token,
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
    
    token = await onvif_service.set_preset(
        camera.onvif_host, camera.onvif_port,
        decrypt_value(camera.onvif_username) or "", decrypt_value(camera.onvif_password or ""),
        preset_name,
    )
    if not token:
        raise HTTPException(500, "Failed to save preset")
    
    # Refresh presets cache
    presets = await onvif_service.get_presets(
        camera.onvif_host, camera.onvif_port,
        decrypt_value(camera.onvif_username) or "", decrypt_value(camera.onvif_password or ""),
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

    ok = await onvif_service.delete_preset(
        camera.onvif_host, camera.onvif_port,
        decrypt_value(camera.onvif_username) or "", decrypt_value(camera.onvif_password or ""),
        preset_token,
    )
    if not ok:
        raise HTTPException(500, "Failed to delete preset")

    # Refresh presets cache in DB
    presets = await onvif_service.get_presets(
        camera.onvif_host, camera.onvif_port,
        decrypt_value(camera.onvif_username) or "", decrypt_value(camera.onvif_password or ""),
    )
    camera.ptz_presets = presets

    await write_audit(
        db, action="ptz_preset_delete", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
        details={"preset_token": preset_token},
    )
    await db.commit()


# ══════════════════════════════════════════════════════════════════════
# Event Buffer Recording
# ══════════════════════════════════════════════════════════════════════

@router.post("/{camera_id}/buffer-record")
async def start_buffer_recording(
    camera_id: str,
    request: Request,
    pre_seconds: int = 30,
    post_seconds: int = 30,
    trigger_type: str = "manual",
    user: dict = Depends(require_permission("control_recording")),
    db: AsyncSession = Depends(get_db),
):
    """
    Start a short event-triggered recording that captures footage before
    and after the trigger moment.
    """
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    if not camera.is_enabled:
        raise HTTPException(400, "Camera is disabled")

    from app.services.go2rtc_manager import go2rtc_manager
    from app.services.ffmpeg_manager import ffmpeg_manager
    from app.storage.service import StorageService

    await go2rtc_manager.add_stream(camera_id, camera.main_stream_url)
    rtsp_url = go2rtc_manager.get_rtsp_output_url(camera_id)
    storage_path = await StorageService.resolve_recording_path(db, camera)

    ok, msg = await ffmpeg_manager.start_buffer_recording(
        camera_id=camera.id,
        rtsp_url=rtsp_url,
        storage_path=storage_path,
        pre_seconds=pre_seconds,
        post_seconds=post_seconds,
        trigger_type=trigger_type,
        recording_fps=camera.recording_fps,
    )
    if not ok:
        raise HTTPException(500, f"Buffer recording failed: {msg}")

    await write_audit(
        db, action="buffer_recording", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
        details={"pre_seconds": pre_seconds, "post_seconds": post_seconds, "trigger": trigger_type},
    )
    await db.commit()

    return {"message": "Buffer recording started", "trigger_type": trigger_type}


# ══════════════════════════════════════════════════════════════════════
# Background helpers
# ══════════════════════════════════════════════════════════════════════

async def _bg_test_connection(camera_id: str):
    """Background task: test RTSP and capture first thumbnail."""
    from app.database import async_session_maker
    from app.services.ffmpeg_manager import ffmpeg_manager
    from app.services.go2rtc_manager import go2rtc_manager

    async with async_session_maker() as session:
        camera = await svc.get_by_id(session, camera_id)
        if not camera:
            return
        success, info = await ffmpeg_manager.test_rtsp_connection(camera.main_stream_url)
        if success:
            camera.status = "online"
            camera.last_online_at = datetime.utcnow()
            if info:
                camera.resolution = info.get("resolution")
                camera.fps = info.get("fps")
                camera.bitrate = info.get("bitrate")
            await go2rtc_manager.add_stream(camera_id, camera.main_stream_url)
            if camera.sub_stream_url:
                await go2rtc_manager.add_stream(f"{camera_id}_sub", camera.sub_stream_url)
            snap = await ffmpeg_manager.capture_snapshot(camera.main_stream_url, camera_id)
            if snap:
                camera.thumbnail_path = snap
        else:
            camera.status = "offline"
        await session.commit()


# ══════════════════════════════════════════════════════════════════════
# Privacy Masks
# ══════════════════════════════════════════════════════════════════════

@router.get("/{camera_id}/privacy-masks")
async def get_privacy_masks(
    camera_id: str,
    user: dict = Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    """Get privacy mask zones for a camera."""
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Camera not found")
    return {"camera_id": camera_id, "masks": camera.privacy_masks or []}


@router.put("/{camera_id}/privacy-masks")
async def update_privacy_masks(
    camera_id: str,
    request: Request,
    user: dict = Depends(require_permission("manage_cameras")),
    db: AsyncSession = Depends(get_db),
):
    """
    Update privacy mask zones.
    Body: {"masks": [{"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.2, "label": "Window"}]}
    Coordinates are normalised 0.0-1.0 relative to frame size.
    """
    body = await request.json()
    masks = body.get("masks", [])
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Camera not found")
    camera.privacy_masks = masks
    await db.commit()

    await write_audit(
        db, action="update_privacy_masks", user_id=user["id"],
        username=user["username"], ip_address=client_ip(request),
        resource_type="camera", resource_id=camera_id,
        details={"mask_count": len(masks)},
    )
    await db.commit()

    return {"camera_id": camera_id, "masks": masks}


# ══════════════════════════════════════════════════════════════════════
# Motion Detection Config
# ══════════════════════════════════════════════════════════════════════

@router.get("/{camera_id}/motion-config")
async def get_motion_config(
    camera_id: str,
    user: dict = Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    """Get motion detection configuration for a camera."""
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Camera not found")
    return {"camera_id": camera_id, "config": camera.motion_config or {}}


@router.put("/{camera_id}/motion-config")
async def update_motion_config(
    camera_id: str,
    request: Request,
    user: dict = Depends(require_permission("manage_cameras")),
    db: AsyncSession = Depends(get_db),
):
    """
    Update motion detection configuration.
    Body: {"config": {"enabled": true, "sensitivity": 5, "zones": [...], "debounce_seconds": 5}}
    """
    body = await request.json()
    config = body.get("config", {})
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Camera not found")
    camera.motion_config = config
    await db.commit()

    # Restart motion detection if enabled
    from app.services.motion_service import motion_detector
    from app.services.go2rtc_manager import go2rtc_manager

    if config.get("enabled"):
        detect_url = camera.detect_stream_url or camera.sub_stream_url or camera.main_stream_url
        await go2rtc_manager.add_stream(f"{camera.id}_detect", detect_url)
        rtsp_url = go2rtc_manager.get_rtsp_output_url(f"{camera.id}_detect")
        await motion_detector.start_detection(camera.id, rtsp_url, config)
    else:
        await motion_detector.stop_detection(camera.id)

    await write_audit(
        db, action="update_motion_config", user_id=user["id"],
        username=user["username"], ip_address=client_ip(request),
        resource_type="camera", resource_id=camera_id,
        details={"enabled": config.get("enabled", False), "sensitivity": config.get("sensitivity")},
    )
    await db.commit()

    return {"camera_id": camera_id, "config": config}


@router.get("/{camera_id}/motion-status")
async def motion_detection_status(
    camera_id: str,
    user: dict = Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    """Check if motion detection is active for a camera."""
    from app.services.motion_service import motion_detector
    return {
        "camera_id": camera_id,
        "detecting": motion_detector.is_detecting(camera_id),
    }


# ══════════════════════════════════════════════════════════════════════
# ONVIF Event Subscription Control
# ══════════════════════════════════════════════════════════════════════

@router.get("/{camera_id}/onvif-events")
async def get_onvif_event_config(
    camera_id: str,
    user: dict = Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    """Get ONVIF event subscription status and config for a camera."""
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    from app.cameras.onvif_event_service import onvif_event_service
    return {
        "camera_id": camera_id,
        "onvif_events_enabled": camera.onvif_events_enabled,
        "onvif_event_topics": camera.onvif_event_topics or [],
        "pull_active": onvif_event_service.is_active(camera_id),
    }


@router.put("/{camera_id}/onvif-events")
async def update_onvif_event_config(
    camera_id: str,
    request: Request,
    user: dict = Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
):
    """
    Enable/disable ONVIF event subscription and set topic filter.
    Body: {"enabled": true, "topics": ["tns1:VideoSource/MotionAlarm", ...]}
    Empty topics list = subscribe to all available topics.
    """
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    if not camera.onvif_host:
        raise HTTPException(400, "Camera has no ONVIF host configured")

    body = await request.json()
    enabled = body.get("enabled", camera.onvif_events_enabled)
    topics = body.get("topics", camera.onvif_event_topics or [])

    camera.onvif_events_enabled = enabled
    camera.onvif_event_topics = topics
    await db.commit()

    from app.cameras.onvif_event_service import onvif_event_service
    from app.core.crypto import decrypt_value

    if enabled and camera.onvif_host:
        await onvif_event_service.start_camera(
            camera_id=camera_id,
            host=camera.onvif_host,
            port=camera.onvif_port,
            username=decrypt_value(camera.onvif_username) or "admin",
            password=decrypt_value(camera.onvif_password) if camera.onvif_password else "admin",
            topics=topics,
        )
    else:
        await onvif_event_service.stop_camera(camera_id)

    await write_audit(
        db, action="onvif_events_config", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
        details={"enabled": enabled, "topics": topics},
    )
    await db.commit()
    return {"camera_id": camera_id, "enabled": enabled, "topics": topics}


# ══════════════════════════════════════════════════════════════════════
# ONVIF Capabilities
# ══════════════════════════════════════════════════════════════════════

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
    caps = await onvif_service.get_capabilities(
        camera.onvif_host, camera.onvif_port,
        decrypt_value(camera.onvif_username) or "admin",
        decrypt_value(camera.onvif_password or ""),
    )
    return {"camera_id": camera_id, "capabilities": caps}


# ══════════════════════════════════════════════════════════════════════
# ONVIF System Operations
# ══════════════════════════════════════════════════════════════════════

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
    info = await onvif_service.get_device_system_info(
        camera.onvif_host, camera.onvif_port,
        decrypt_value(camera.onvif_username) or "admin",
        decrypt_value(camera.onvif_password or ""),
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
    time_info = await onvif_service.get_camera_time(
        camera.onvif_host, camera.onvif_port,
        decrypt_value(camera.onvif_username) or "admin",
        decrypt_value(camera.onvif_password or ""),
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
    ok = await onvif_service.sync_camera_time(
        camera.onvif_host, camera.onvif_port,
        decrypt_value(camera.onvif_username) or "admin",
        decrypt_value(camera.onvif_password or ""),
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
        msg = await onvif_service.reboot_camera(
            camera.onvif_host, camera.onvif_port,
            decrypt_value(camera.onvif_username) or "admin",
            decrypt_value(camera.onvif_password or ""),
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


# ══════════════════════════════════════════════════════════════════════
# ONVIF Imaging Service
# ══════════════════════════════════════════════════════════════════════

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
    settings_data = await onvif_service.get_imaging_settings(
        camera.onvif_host, camera.onvif_port,
        decrypt_value(camera.onvif_username) or "admin",
        decrypt_value(camera.onvif_password or ""),
    )
    options = await onvif_service.get_imaging_options(
        camera.onvif_host, camera.onvif_port,
        decrypt_value(camera.onvif_username) or "admin",
        decrypt_value(camera.onvif_password or ""),
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
    ok = await onvif_service.set_imaging_settings(
        camera.onvif_host, camera.onvif_port,
        decrypt_value(camera.onvif_username) or "admin",
        decrypt_value(camera.onvif_password or ""),
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
    ok = await onvif_service.move_focus(
        camera.onvif_host, camera.onvif_port,
        decrypt_value(camera.onvif_username) or "admin",
        decrypt_value(camera.onvif_password or ""),
        mode="Auto",
    )
    return {"camera_id": camera_id, "autofocus_triggered": ok}


# ══════════════════════════════════════════════════════════════════════
# ONVIF Digital I/O (Relay Outputs + Digital Inputs)
# ══════════════════════════════════════════════════════════════════════

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
    outputs = await onvif_service.get_relay_outputs(
        camera.onvif_host, camera.onvif_port,
        decrypt_value(camera.onvif_username) or "admin",
        decrypt_value(camera.onvif_password or ""),
    )
    # Cache in DB
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
    ok = await onvif_service.set_relay_output_state(
        camera.onvif_host, camera.onvif_port,
        decrypt_value(camera.onvif_username) or "admin",
        decrypt_value(camera.onvif_password or ""),
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
    inputs = await onvif_service.get_digital_inputs(
        camera.onvif_host, camera.onvif_port,
        decrypt_value(camera.onvif_username) or "admin",
        decrypt_value(camera.onvif_password or ""),
    )
    # Cache in DB
    camera.digital_inputs = inputs
    await db.commit()
    return {"camera_id": camera_id, "digital_inputs": inputs}


# ══════════════════════════════════════════════════════════════════════
# Camera Snapshots
# ══════════════════════════════════════════════════════════════════════

@router.get("/{camera_id}/snapshots")
async def list_snapshots(
    camera_id: str,
    limit: int = 50,
    trigger: Optional[str] = None,
    user: dict = Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    """List snapshot history for a camera."""
    from app.cameras.models import CameraSnapshot
    from sqlalchemy import select as sa_select, desc
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    q = sa_select(CameraSnapshot).where(CameraSnapshot.camera_id == camera_id)
    if trigger:
        q = q.where(CameraSnapshot.trigger == trigger)
    q = q.order_by(desc(CameraSnapshot.captured_at)).limit(limit)
    result = await db.execute(q)
    snaps = result.scalars().all()
    return {
        "camera_id": camera_id,
        "snapshots": [
            {
                "id": s.id, "file_path": s.file_path, "file_size": s.file_size,
                "trigger": s.trigger, "event_id": s.event_id,
                "captured_at": s.captured_at.isoformat() if s.captured_at else None,
            }
            for s in snaps
        ],
    }


@router.get("/{camera_id}/snapshots/latest")
async def get_latest_snapshot(
    camera_id: str,
    user: dict = Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    """Get the most recent snapshot for a camera."""
    from app.cameras.models import CameraSnapshot
    from sqlalchemy import select as sa_select, desc
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    result = await db.execute(
        sa_select(CameraSnapshot)
        .where(CameraSnapshot.camera_id == camera_id)
        .order_by(desc(CameraSnapshot.captured_at))
        .limit(1)
    )
    snap = result.scalar_one_or_none()
    if not snap:
        raise HTTPException(404, "No snapshots found for this camera")
    return {
        "id": snap.id, "camera_id": camera_id, "file_path": snap.file_path,
        "file_size": snap.file_size, "trigger": snap.trigger,
        "captured_at": snap.captured_at.isoformat() if snap.captured_at else None,
    }


# ══════════════════════════════════════════════════════════════════════
# Two-Way Audio (Intercom)
# ══════════════════════════════════════════════════════════════════════

@router.post("/{camera_id}/audio/start")
async def start_twoway_audio(
    camera_id: str,
    user: dict = Depends(require_permission("control_recording")),
    db: AsyncSession = Depends(get_db),
):
    """Start a two-way audio (speak-back) session to the camera."""
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")

    # Try ONVIF AudioOutput URL first, fallback to RTSP backchannel heuristic
    backchannel_url = None
    if camera.onvif_host:
        try:
            backchannel = await onvif_service.get_audio_output_uri(
                camera.onvif_host, camera.onvif_port,
                decrypt_value(camera.onvif_username) or "admin",
                decrypt_value(camera.onvif_password or ""),
            )
            if backchannel:
                backchannel_url = backchannel
        except Exception:
            pass

    if not backchannel_url and camera.main_stream_url:
        # Heuristic: some cameras expose backchannel on same host with /backchannel path
        from urllib.parse import urlparse
        parsed = urlparse(camera.main_stream_url)
        backchannel_url = f"rtsp://{parsed.hostname}:554/backchannel"

    if not backchannel_url:
        raise HTTPException(400, "Camera does not support two-way audio")

    ok = await twoway_audio_service.start_session(camera_id, backchannel_url)
    if not ok:
        raise HTTPException(500, "Failed to start two-way audio session")
    return {"camera_id": camera_id, "status": "speaking", "backchannel_url": backchannel_url}


@router.post("/{camera_id}/audio/stop")
async def stop_twoway_audio(
    camera_id: str,
    user: dict = Depends(require_permission("control_recording")),
):
    """Stop the two-way audio session."""
    await twoway_audio_service.stop_session(camera_id)
    return {"camera_id": camera_id, "status": "stopped"}


@router.get("/{camera_id}/audio/status")
async def get_twoway_audio_status(
    camera_id: str,
    user: dict = Depends(require_permission("view_live")),
):
    """Check if two-way audio is active for a camera."""
    return {"camera_id": camera_id, "active": twoway_audio_service.is_active(camera_id)}
