# =============================================================================
# Recording Sub-Router — start/stop recording, buffer recording
# Mounted under: /cameras
# =============================================================================

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.cameras.service import CameraService
from app.core.dependencies import require_permission
from app.core.audit_logger import write_audit, client_ip

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Recording"])
svc = CameraService()


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

    await go2rtc_manager.add_stream(camera_id, camera.main_stream_url, dewarp_config=camera.dewarp_config)
    if camera.sub_stream_url:
        await go2rtc_manager.add_stream(f"{camera_id}_sub", camera.sub_stream_url, dewarp_config=camera.dewarp_config)

    await go2rtc_manager.wait_for_stream_ready(camera_id)

    rtsp_url = go2rtc_manager.get_rtsp_output_url(camera_id)

    from app.storage.service import StorageService
    storage_path = await StorageService.resolve_recording_path(db, camera)

    success, msg = await ffmpeg_manager.start_recording(
        camera_id=camera.id,
        rtsp_url=rtsp_url,
        storage_path=storage_path,
        recording_fps=camera.recording_fps,
        sub_stream_url=go2rtc_manager.get_rtsp_output_url(f"{camera_id}_sub") if camera.sub_stream_url else None,
        pos_overlay_config=camera.pos_overlay_config,
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

    return {"camera_id": camera_id, "recording": True}


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
    return {"camera_id": camera_id, "recording": False}


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

    await go2rtc_manager.add_stream(camera_id, camera.main_stream_url, dewarp_config=camera.dewarp_config)
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
