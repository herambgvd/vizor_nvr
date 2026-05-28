# =============================================================================
# Camera Router — CRUD, recording control, streams, groups, ONVIF, PTZ
# =============================================================================

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException, Query, Request, BackgroundTasks, status
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
        from urllib.parse import quote as _q
        cred = (
            f"{_q(username, safe='')}:{_q(password or '', safe='')}@"
            if username else ""
        )
        uris["main_stream_url"] = f"rtsp://{cred}{host}:554/stream1"

    return {
        **(info or {}),
        **uris,
        "ptz_capable": ptz,
        "ip": host,
        "port": port,
    }


@router.post("/onvif/channels")
async def onvif_channels(
    body: dict,
    user: dict = Depends(require_permission("manage_camera")),
):
    """Enumerate all ONVIF media profiles on a device grouped by channel.

    Use when a discovered device is an NVR/DVR exposing multiple cameras
    through a single ONVIF endpoint. Returns one entry per physical
    channel with main + sub stream URLs.

    Body: {"host", "port", "username", "password"}
    """
    host = body.get("host")
    port = int(body.get("port") or 80)
    username = body.get("username") or "admin"
    password = body.get("password") or "admin"
    if not host:
        raise HTTPException(400, "host required")
    return await onvif_service.enumerate_channels(host, port, username, password)


@router.post("/onvif/bulk-add", status_code=201)
async def onvif_bulk_add(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_permission("manage_camera")),
):
    """Create many cameras in one transaction.

    Used by the discovery dialog to onboard every selected channel of an
    NVR at once.

    Body:
      {
        "cameras": [
          {
            "name": "CH1",
            "onvif_host": "10.0.0.5", "onvif_port": 80,
            "onvif_username": "admin", "onvif_password": "...",
            "onvif_profile_token": "Profile_1_Main",
            "main_stream_url": "rtsp://...",
            "sub_stream_url": "rtsp://..." | null,
            "ptz_capable": false
          }, ...
        ]
      }

    Returns {"created": [<camera_response>, ...], "failed": [{"name":..., "error":...}, ...]}.
    """
    from app.cameras.models import CameraCreate

    cameras_data = body.get("cameras") or []
    if not isinstance(cameras_data, list):
        raise HTTPException(400, "'cameras' must be a list")

    created = []
    failed = []

    for entry in cameras_data:
        entry_name = entry.get("name", "<unnamed>")
        try:
            cam_create = CameraCreate(
                name=entry_name,
                main_stream_url=entry.get("main_stream_url") or "",
                sub_stream_url=entry.get("sub_stream_url"),
                onvif_host=entry.get("onvif_host"),
                onvif_port=int(entry.get("onvif_port") or 80),
                onvif_username=entry.get("onvif_username"),
                onvif_password=entry.get("onvif_password"),
                onvif_profile_token=entry.get("onvif_profile_token"),
                ptz_capable=bool(entry.get("ptz_capable", False)),
                location=entry.get("location"),
                description=entry.get("description"),
                is_enabled=bool(entry.get("is_enabled", True)),
                recording_mode=entry.get("recording_mode", "continuous"),
                onvif_events_enabled=bool(entry.get("onvif_events_enabled", False)),
            )
            # Validate main_stream_url
            if not cam_create.main_stream_url:
                raise ValueError("main_stream_url is required")

            camera = await svc.create(db, cam_create)
            # Also persist onvif_profile_token (not in Camera constructor yet via CameraCreate)
            if cam_create.onvif_profile_token and not camera.onvif_profile_token:
                camera.onvif_profile_token = cam_create.onvif_profile_token
                await db.flush()
            await db.commit()
            await db.refresh(camera, ["groups"])
            created.append(svc.to_response(camera))
        except Exception as exc:
            logger.warning("onvif_bulk_add: failed to create camera '%s': %s", entry_name, exc)
            try:
                await db.rollback()
            except Exception:
                pass
            failed.append({"name": entry_name, "error": str(exc)})

    return {"created": created, "failed": failed}


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
    # Ed25519 license enforcement (.lic file). Falls back to the operator
    # settings cap when no license is installed (dev/free tier).
    from app.license.service import get_license_service
    from app.settings.service import SettingsService

    current = await svc.count(db)
    lic = get_license_service()
    if lic.is_active():
        if lic.camera_limit() and current >= lic.camera_limit():
            raise HTTPException(
                402,
                f"License cap reached: {current}/{lic.camera_limit()} cameras",
            )
    else:
        settings_cap = await SettingsService.get_max_cameras(db)
        if current >= settings_cap:
            raise HTTPException(403, f"Operator cap: max {settings_cap} cameras")

    camera = await svc.create(db, data)

    # Auto-enable ONVIF event subscription when the camera reports an
    # ONVIF host. Operators can disable per-camera from settings if a
    # device floods the event log. Default-on is required so device-side
    # alarms (motion, tamper, line crossing) reach the Events page
    # without manual config.
    if camera.onvif_host and not camera.onvif_events_enabled:
        camera.onvif_events_enabled = True

    await write_audit(
        db, action="camera_create", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="camera", resource_id=camera.id,
        description=f"Camera created: {camera.name}",
    )
    await db.commit()

    # Test connection in background
    bg.add_task(_bg_test_connection, camera.id)

    # Kick off ONVIF event pull asynchronously (no-op if no host)
    if camera.onvif_host and camera.onvif_events_enabled:
        from app.cameras.onvif_event_service import onvif_event_service
        from app.core.crypto import decrypt_value
        try:
            await onvif_event_service.start_camera(
                camera_id=camera.id,
                host=camera.onvif_host,
                port=camera.onvif_port or 80,
                username=decrypt_value(camera.onvif_username) or "admin",
                password=decrypt_value(camera.onvif_password) if camera.onvif_password else "admin",
                topics=camera.onvif_event_topics or [],
            )
        except Exception as _e:
            logger.warning(f"ONVIF event pull start failed for {camera.id}: {_e}")

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
            await go2rtc_manager.add_stream(camera_id, camera.main_stream_url, dewarp_config=camera.dewarp_config)
        if camera.sub_stream_url:
            await go2rtc_manager.add_stream(f"{camera_id}_sub", camera.sub_stream_url, dewarp_config=camera.dewarp_config)

    await write_audit(
        db, action="camera_update", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
        details={"changes": changes},
    )
    await db.commit()
    return CameraResponse(**svc.to_response(camera))


@router.get("/health/latest")
async def get_latest_health(
    user: dict = Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    """Return latest health snapshot per camera as a map {id: {...}}.
    Used by the Cameras table Health column."""
    from app.cameras.models import CameraHealthSnapshot
    from sqlalchemy import select as sa_select, func as sa_func

    # Latest captured_at per camera via window expression — but a simpler
    # approach: subquery for max captured_at per camera, then join.
    subq = (
        sa_select(
            CameraHealthSnapshot.camera_id,
            sa_func.max(CameraHealthSnapshot.captured_at).label("max_ts"),
        )
        .group_by(CameraHealthSnapshot.camera_id)
        .subquery()
    )
    stmt = sa_select(CameraHealthSnapshot).join(
        subq,
        (CameraHealthSnapshot.camera_id == subq.c.camera_id)
        & (CameraHealthSnapshot.captured_at == subq.c.max_ts),
    )
    result = await db.execute(stmt)
    snaps = result.scalars().all()
    return {
        s.camera_id: {
            "bitrate_kbps": s.bitrate_kbps,
            "fps_actual": s.fps_actual,
            "packet_loss_percent": s.packet_loss_percent,
            "status": s.status,
            "captured_at": s.captured_at.isoformat() if s.captured_at else None,
        }
        for s in snaps
    }


@router.post("/bulk/start", status_code=200)
async def bulk_start_recording(
    request: Request,
    user: dict = Depends(require_permission("control_recording")),
    db: AsyncSession = Depends(get_db),
):
    """Bulk-start recording. Body: {"camera_ids": [...]}."""
    body = await request.json()
    ids = body.get("camera_ids") or []
    if not isinstance(ids, list) or not ids:
        raise HTTPException(400, "camera_ids must be a non-empty list")

    from sqlalchemy import select as sa_select
    from app.cameras.models import Camera
    started = []
    failed = []
    for cid in ids:
        try:
            cam = (await db.execute(sa_select(Camera).where(Camera.id == cid))).scalar_one_or_none()
            if not cam:
                failed.append(cid)
                continue
            cam.is_recording = True
            cam.retry_count = 0
            await _start_camera_recording_helper(db, cam)
            started.append(cid)
        except Exception as e:
            logger.warning(f"bulk_start {cid} failed: {e}")
            failed.append(cid)
    await db.commit()
    return {"started": started, "failed": failed}


@router.post("/bulk/stop", status_code=200)
async def bulk_stop_recording(
    request: Request,
    user: dict = Depends(require_permission("control_recording")),
    db: AsyncSession = Depends(get_db),
):
    """Bulk-stop recording. Body: {"camera_ids": [...]}."""
    from app.services.ffmpeg_manager import ffmpeg_manager
    from sqlalchemy import select as sa_select
    from app.cameras.models import Camera
    body = await request.json()
    ids = body.get("camera_ids") or []
    if not isinstance(ids, list) or not ids:
        raise HTTPException(400, "camera_ids must be a non-empty list")

    stopped = []
    for cid in ids:
        try:
            await ffmpeg_manager.stop_recording(cid)
            cam = (await db.execute(sa_select(Camera).where(Camera.id == cid))).scalar_one_or_none()
            if cam:
                cam.is_recording = False
                stopped.append(cid)
        except Exception as e:
            logger.warning(f"bulk_stop {cid} failed: {e}")
    await db.commit()
    return {"stopped": stopped}


@router.post("/bulk/test", status_code=200)
async def bulk_test_connection(
    request: Request,
    user: dict = Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    """Bulk RTSP reachability test. Body: {"camera_ids": [...]}."""
    from app.services.ffmpeg_manager import ffmpeg_manager
    from sqlalchemy import select as sa_select
    from app.cameras.models import Camera
    import asyncio
    body = await request.json()
    ids = body.get("camera_ids") or []
    if not isinstance(ids, list) or not ids:
        raise HTTPException(400, "camera_ids must be a non-empty list")

    results = {}

    async def probe(cid: str):
        cam = (await db.execute(sa_select(Camera).where(Camera.id == cid))).scalar_one_or_none()
        if not cam:
            results[cid] = {"ok": False, "error": "not_found"}
            return
        ok, info = await ffmpeg_manager.test_rtsp_connection(cam.main_stream_url)
        results[cid] = {"ok": ok, "info": info}
        if ok:
            cam.status = "online"
            cam.last_online_at = datetime.utcnow()
        else:
            cam.status = "offline"

    await asyncio.gather(*[probe(cid) for cid in ids])
    await db.commit()
    return {"results": results}


@router.post("/bulk/enable", status_code=200)
async def bulk_set_enabled(
    request: Request,
    user: dict = Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
):
    """Bulk enable/disable cameras. Body: {"camera_ids": [...], "enabled": bool}."""
    from sqlalchemy import select as sa_select
    from app.cameras.models import Camera
    body = await request.json()
    ids = body.get("camera_ids") or []
    enabled = bool(body.get("enabled", True))
    if not isinstance(ids, list) or not ids:
        raise HTTPException(400, "camera_ids must be a non-empty list")

    updated = []
    for cid in ids:
        cam = (await db.execute(sa_select(Camera).where(Camera.id == cid))).scalar_one_or_none()
        if cam:
            cam.is_enabled = enabled
            updated.append(cid)
    await db.commit()
    return {"updated": updated, "enabled": enabled}


@router.post("/bulk", status_code=200)
async def bulk_camera_action(
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Unified bulk action endpoint.

    Body::

        {
            "action": "delete|enable|disable|move_to_group|set_retention",
            "camera_ids": ["<id>", ...],   // max 200
            "params": {
                // move_to_group: {"group_id": "<id>"}
                // set_retention: {"retention_days": <int|null>}
            }
        }

    Returns::

        {"succeeded": [<id>, ...], "failed": [{"id": ..., "error": ...}, ...]}
    """
    from sqlalchemy import select as sa_select
    from app.cameras.models import Camera, camera_group_members

    body = await request.json()
    action = body.get("action")
    camera_ids = body.get("camera_ids") or []
    params = body.get("params") or {}

    VALID_ACTIONS = {"delete", "enable", "disable", "move_to_group", "set_retention"}
    if action not in VALID_ACTIONS:
        raise HTTPException(400, f"action must be one of {sorted(VALID_ACTIONS)}")

    if not isinstance(camera_ids, list):
        raise HTTPException(400, "camera_ids must be a list")

    if len(camera_ids) > 200:
        raise HTTPException(400, "camera_ids may not exceed 200 per request")

    # Empty list is a valid no-op
    if not camera_ids:
        return {"succeeded": [], "failed": []}

    succeeded = []
    failed = []

    if action == "delete":
        from app.services.ffmpeg_manager import ffmpeg_manager
        from app.services.go2rtc_manager import go2rtc_manager
        from app.cameras.onvif_event_service import onvif_event_service

        for cid in camera_ids:
            try:
                await ffmpeg_manager.stop_recording(cid)
                await go2rtc_manager.remove_stream(cid)
                await go2rtc_manager.remove_stream(f"{cid}_sub")
                await onvif_event_service.stop_camera(cid)
            except Exception:
                pass

            if await svc.delete(db, cid):
                _purge_camera_files(cid)
                succeeded.append(cid)
            else:
                failed.append({"id": cid, "error": "not_found"})

        if succeeded:
            await write_audit(
                db, action="camera_bulk_delete", user_id=user["id"],
                username=user["username"], ip_address=client_ip(request),
                resource_type="camera", resource_id=",".join(succeeded),
                severity="warning",
                details={"deleted_count": len(succeeded), "failed": len(failed)},
            )

    elif action in ("enable", "disable"):
        enabled_val = action == "enable"
        for cid in camera_ids:
            cam = (
                await db.execute(sa_select(Camera).where(Camera.id == cid))
            ).scalar_one_or_none()
            if cam:
                cam.is_enabled = enabled_val
                succeeded.append(cid)
            else:
                failed.append({"id": cid, "error": "not_found"})

    elif action == "move_to_group":
        group_id = params.get("group_id")
        if not group_id:
            raise HTTPException(400, "params.group_id required for move_to_group")

        from app.cameras.models import CameraGroup
        group = (
            await db.execute(sa_select(CameraGroup).where(CameraGroup.id == group_id))
        ).scalar_one_or_none()
        if not group:
            raise HTTPException(404, f"Group {group_id} not found")

        for cid in camera_ids:
            cam = (
                await db.execute(
                    sa_select(Camera).where(Camera.id == cid)
                )
            ).scalar_one_or_none()
            if not cam:
                failed.append({"id": cid, "error": "not_found"})
                continue
            try:
                # Load groups relationship, add this group if not present
                await db.refresh(cam, ["groups"])
                group_ids_now = [g.id for g in cam.groups]
                if group_id not in group_ids_now:
                    cam.groups.append(group)
                succeeded.append(cid)
            except Exception as exc:
                failed.append({"id": cid, "error": str(exc)})

    elif action == "set_retention":
        retention_days = params.get("retention_days")  # None clears the override
        if retention_days is not None and not isinstance(retention_days, int):
            raise HTTPException(400, "params.retention_days must be an integer or null")
        for cid in camera_ids:
            cam = (
                await db.execute(sa_select(Camera).where(Camera.id == cid))
            ).scalar_one_or_none()
            if cam:
                cam.retention_days = retention_days
                succeeded.append(cid)
            else:
                failed.append({"id": cid, "error": "not_found"})

    await db.commit()
    return {"succeeded": succeeded, "failed": failed}


@router.post("/reorder", status_code=200)
async def reorder_cameras(
    request: Request,
    user: dict = Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
):
    """Persist a new display order. Body: {"camera_ids": [ordered ids]}."""
    from sqlalchemy import select as sa_select
    from app.cameras.models import Camera
    body = await request.json()
    ids = body.get("camera_ids") or []
    if not isinstance(ids, list) or not ids:
        raise HTTPException(400, "camera_ids must be a non-empty list")

    for idx, cid in enumerate(ids):
        cam = (await db.execute(sa_select(Camera).where(Camera.id == cid))).scalar_one_or_none()
        if cam:
            cam.display_order = idx
    await db.commit()
    return {"reordered": len(ids)}


async def _start_camera_recording_helper(db, camera):
    """Shared start-recording helper for single + bulk routes."""
    from app.services.ffmpeg_manager import ffmpeg_manager
    from app.services.go2rtc_manager import go2rtc_manager
    from app.storage.service import StorageService

    await go2rtc_manager.add_stream(camera.id, camera.main_stream_url, dewarp_config=camera.dewarp_config)
    if camera.sub_stream_url:
        await go2rtc_manager.add_stream(f"{camera.id}_sub", camera.sub_stream_url, dewarp_config=camera.dewarp_config)
    await go2rtc_manager.wait_for_stream_ready(camera.id)

    rtsp_url = go2rtc_manager.get_rtsp_output_url(camera.id)
    sub_rtsp_url = (
        go2rtc_manager.get_rtsp_output_url(f"{camera.id}_sub")
        if camera.sub_stream_url
        else None
    )
    storage_path = await StorageService.resolve_recording_path(db, camera)

    success, _ = await ffmpeg_manager.start_recording(
        camera.id, rtsp_url, storage_path, camera.recording_fps,
        sub_stream_url=sub_rtsp_url,
        privacy_masks=camera.privacy_masks,
        pos_overlay_config=camera.pos_overlay_config,
    )
    if success:
        camera.status = "online"
        camera.last_online_at = datetime.utcnow()
    else:
        camera.status = "error"


@router.post("/bulk-delete", status_code=200)
async def bulk_delete_cameras(
    request: Request,
    user: dict = Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
):
    """Bulk-delete cameras by id list. Body: {"camera_ids": [...]}.
    Stops recording + go2rtc streams + ONVIF event pull for each."""
    from app.services.ffmpeg_manager import ffmpeg_manager
    from app.services.go2rtc_manager import go2rtc_manager
    from app.cameras.onvif_event_service import onvif_event_service

    body = await request.json()
    ids = body.get("camera_ids") or []
    if not isinstance(ids, list) or not ids:
        raise HTTPException(400, "camera_ids must be a non-empty list")

    deleted = []
    not_found = []
    for cid in ids:
        try:
            await ffmpeg_manager.stop_recording(cid)
            await go2rtc_manager.remove_stream(cid)
            await go2rtc_manager.remove_stream(f"{cid}_sub")
            await onvif_event_service.stop_camera(cid)
        except Exception:
            pass

        if await svc.delete(db, cid):
            deleted.append(cid)
            _purge_camera_files(cid)
        else:
            not_found.append(cid)

    if deleted:
        await write_audit(
            db, action="camera_bulk_delete", user_id=user["id"],
            username=user["username"], ip_address=client_ip(request),
            resource_type="camera", resource_id=",".join(deleted),
            severity="warning",
            details={"deleted_count": len(deleted), "not_found": not_found},
        )
    await db.commit()
    return {"deleted": len(deleted), "not_found": not_found}


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
    from app.cameras.onvif_event_service import onvif_event_service
    await ffmpeg_manager.stop_recording(camera_id)
    await go2rtc_manager.remove_stream(camera_id)
    await go2rtc_manager.remove_stream(f"{camera_id}_sub")
    await onvif_event_service.stop_camera(camera_id)

    if not await svc.delete(db, camera_id):
        raise HTTPException(404, "Camera not found")

    # Wipe on-disk recording + thumbnail files for this camera. DB
    # cascade already removed recording rows via FK ondelete=CASCADE.
    _purge_camera_files(camera_id)

    await write_audit(
        db, action="camera_delete", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
        severity="warning",
    )
    await db.commit()


def _purge_camera_files(camera_id: str) -> None:
    """Remove recording + thumbnail directories for a deleted camera.
    Best-effort: logs and swallows errors so DB delete still succeeds."""
    import shutil
    from app.config import settings as _s
    for base in (
        _s.STORAGE_PATH,
        _s.THUMBNAIL_PATH,
        _s.HLS_PATH,
    ):
        target = Path(base) / camera_id
        if target.exists() and target.is_dir():
            try:
                shutil.rmtree(target)
                logger.info(f"Purged {target}")
            except Exception as e:
                logger.warning(f"Purge failed for {target}: {e}")

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
    await go2rtc_manager.add_stream(camera_id, camera.main_stream_url, dewarp_config=camera.dewarp_config)
    if camera.sub_stream_url:
        await go2rtc_manager.add_stream(f"{camera_id}_sub", camera.sub_stream_url, dewarp_config=camera.dewarp_config)

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
    await go2rtc_manager.add_stream(camera_id, camera.main_stream_url, dewarp_config=camera.dewarp_config)
    if camera.sub_stream_url:
        await go2rtc_manager.add_stream(f"{camera_id}_sub", camera.sub_stream_url, dewarp_config=camera.dewarp_config)

    body = await request.json()
    live_id = f"{camera_id}_sub" if camera.sub_stream_url else camera_id
    answer = await go2rtc_manager.webrtc_signal(live_id, body.get("sdp", ""))
    if answer is None:
        raise HTTPException(500, "WebRTC signalling failed")
    return {"sdp": answer}

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
            await go2rtc_manager.add_stream(camera_id, camera.main_stream_url, dewarp_config=camera.dewarp_config)
            if camera.sub_stream_url:
                await go2rtc_manager.add_stream(f"{camera_id}_sub", camera.sub_stream_url, dewarp_config=camera.dewarp_config)
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
        await go2rtc_manager.add_stream(f"{camera.id}_detect", detect_url, dewarp_config=camera.dewarp_config)
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


@router.get("/{camera_id}/thumbnail")
async def get_camera_thumbnail(
    camera_id: str,
    user: dict = Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    """Serve latest snapshot JPEG. Falls back to a fresh ffmpeg snapshot
    if no prior snapshot is on disk. Persists the fresh capture so the
    Cameras table doesn't hit ffmpeg on every page render."""
    from app.cameras.models import Camera, CameraSnapshot
    from fastapi.responses import FileResponse
    from sqlalchemy import select as sa_select, desc
    import os as _os
    import uuid as _uuid

    # 1. Try the latest stored snapshot
    result = await db.execute(
        sa_select(CameraSnapshot)
        .where(CameraSnapshot.camera_id == camera_id)
        .order_by(desc(CameraSnapshot.captured_at))
        .limit(1)
    )
    snap = result.scalar_one_or_none()
    if snap and snap.file_path and _os.path.exists(snap.file_path):
        return FileResponse(snap.file_path, media_type="image/jpeg")

    # 2. Fallback — capture on-demand via ffmpeg. Used when periodic
    #    snapshots haven't kicked in (camera not yet recording).
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    if camera.status != "online":
        raise HTTPException(404, "Camera offline")

    from app.services.ffmpeg_manager import ffmpeg_manager
    path = await ffmpeg_manager.capture_snapshot(camera.main_stream_url, camera_id)
    if not path or not _os.path.exists(path):
        raise HTTPException(404, "Snapshot capture failed")

    # Persist so subsequent calls + Events page hero reuse the file.
    # Snapshot tab is gone — keep at most one row per camera so disk
    # doesn't grow unbounded from the table thumbnail refresh.
    file_size = None
    try:
        file_size = _os.path.getsize(path)
    except Exception:
        pass

    # Drop prior snapshots for this camera (rows + files)
    prior = await db.execute(
        sa_select(CameraSnapshot).where(CameraSnapshot.camera_id == camera_id)
    )
    for old in prior.scalars().all():
        if old.file_path and _os.path.exists(old.file_path) and old.file_path != path:
            try:
                _os.remove(old.file_path)
            except Exception:
                pass
        await db.delete(old)

    new_snap = CameraSnapshot(
        id=str(_uuid.uuid4()),
        camera_id=camera_id,
        file_path=path,
        file_size=file_size,
        trigger="thumbnail_ondemand",
    )
    db.add(new_snap)
    await db.commit()

    return FileResponse(path, media_type="image/jpeg")


@router.get("/snapshot-file/{snapshot_id}")
async def get_snapshot_image(
    snapshot_id: str,
    user: dict = Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    """Serve a snapshot JPEG by id. Used by the Events page hero tile."""
    from app.cameras.models import CameraSnapshot
    from fastapi.responses import FileResponse
    import os as _os
    result = await db.execute(
        __import__("sqlalchemy").select(CameraSnapshot).where(CameraSnapshot.id == snapshot_id)
    )
    snap = result.scalar_one_or_none()
    if not snap or not snap.file_path or not _os.path.exists(snap.file_path):
        raise HTTPException(404, "Snapshot not found")
    return FileResponse(snap.file_path, media_type="image/jpeg")


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
# ANR (Automatic Network Replenishment)
# ══════════════════════════════════════════════════════════════════════

class ANRTriggerRequest(BaseModel):
    gap_start: Optional[datetime] = None
    gap_end: Optional[datetime] = None


@router.get("/{camera_id}/anr/status")
async def get_anr_status(
    camera_id: str,
    user: dict = Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    """Get the latest ANR job status for a camera."""
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")

    from app.services.anr_service import anr_service
    status = await anr_service.get_job_status(camera_id)
    return {
        "camera_id": camera_id,
        "anr_enabled": camera.anr_enabled,
        "anr_status": camera.anr_status,
        "anr_last_run_at": camera.anr_last_run_at.isoformat() if camera.anr_last_run_at else None,
        "job": status,
    }


@router.post("/{camera_id}/anr/trigger")
async def trigger_anr(
    camera_id: str,
    body: ANRTriggerRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_permission("manage_cameras")),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger ANR backfill for a camera.

    If gap_start/gap_end are omitted, the service auto-detects the gap.
    """
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")

    if not camera.anr_enabled:
        raise HTTPException(400, "ANR is not enabled for this camera. Enable it first via camera settings.")

    from app.services.anr_service import anr_service

    # If explicit gap provided, create job directly; otherwise auto-detect
    if body.gap_start and body.gap_end:
        from app.cameras.models import AnrJob
        from sqlalchemy import select

        # Check for active job
        existing = await db.execute(
            select(AnrJob).where(
                AnrJob.camera_id == camera_id,
                AnrJob.status.in_(["pending", "searching", "downloading"]),
            )
        )
        if existing.scalars().first():
            raise HTTPException(409, "ANR job already active for this camera")

        job = AnrJob(
            camera_id=camera_id,
            gap_start=body.gap_start,
            gap_end=body.gap_end,
            status="pending",
        )
        db.add(job)
        camera.anr_status = "pending"
        camera.anr_last_run_at = datetime.utcnow()
        await db.commit()

        background_tasks.add_task(anr_service._backfill_camera, camera_id, job.id)
        return {"message": "ANR backfill triggered", "job_id": job.id}
    else:
        # Auto-detect gap
        background_tasks.add_task(anr_service.on_camera_recovered, camera_id)
        return {"message": "ANR backfill triggered (auto-detect gap)"}


@router.get("/{camera_id}/anr/jobs")
async def list_anr_jobs(
    camera_id: str,
    limit: int = 20,
    user: dict = Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    """List ANR jobs for a camera, newest first."""
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")

    from sqlalchemy import select
    from app.cameras.models import AnrJob

    result = await db.execute(
        select(AnrJob)
        .where(AnrJob.camera_id == camera_id)
        .order_by(AnrJob.created_at.desc())
        .limit(limit)
    )
    jobs = result.scalars().all()
    return [
        {
            "id": j.id,
            "status": j.status,
            "gap_start": j.gap_start.isoformat() if j.gap_start else None,
            "gap_end": j.gap_end.isoformat() if j.gap_end else None,
            "segments_found": j.segments_found,
            "segments_downloaded": j.segments_downloaded,
            "segments_failed": j.segments_failed,
            "error_message": j.error_message,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "completed_at": j.completed_at.isoformat() if j.completed_at else None,
        }
        for j in jobs
    ]

# ══════════════════════════════════════════════════════════════════════
# Sub-routers (split from monolith for maintainability)
# ══════════════════════════════════════════════════════════════════════
from app.cameras.recording_router import router as recording_router
from app.cameras.ptz_router import router as ptz_router
from app.cameras.imaging_router import router as imaging_router
from app.cameras.io_router import router as io_router
from app.cameras.system_router import router as system_router
from app.cameras.credentials_router import router as credentials_router
from app.cameras.audio_router import router as audio_router

router.include_router(recording_router)
router.include_router(ptz_router)
router.include_router(imaging_router)
router.include_router(io_router)
router.include_router(system_router)
router.include_router(credentials_router)
router.include_router(audio_router)
