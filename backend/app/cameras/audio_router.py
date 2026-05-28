# =============================================================================
# Audio Sub-Router — two-way audio (intercom) and WebRTC backchannel
# Mounted under: /cameras
# =============================================================================

import logging

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.cameras.service import CameraService
from app.cameras.onvif_service import onvif_service
from app.cameras.twoway_audio_service import twoway_audio_service
from app.core.dependencies import require_permission, get_admin_user
from app.core.crypto import decrypt_value

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Audio"])
svc = CameraService()


# ── Simple two-way audio (FFmpeg backchannel) ────────────────────────────────

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


# ── Backchannel (WebRTC-friendly aliases) ────────────────────────────────────

@router.post("/{camera_id}/audio/backchannel/start")
async def start_backchannel(
    camera_id: str,
    request: Request,
    user: dict = Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    """
    Register a two-way audio backchannel session for this camera.

    Uses a per-camera capability cache (backchannel_capable column):
    - NULL  = untested → attempt, then persist result
    - True  = supported → skip re-registration, reuse
    - False = not supported → immediately 503

    Reset the cache with POST /cameras/{id}/audio/backchannel/recheck.
    """
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")

    if getattr(camera, "backchannel_capable", None) is False:
        raise HTTPException(503, "Two-way audio not supported by this camera (cached result). "
                                 "Use /audio/backchannel/recheck to re-probe.")

    capable = getattr(camera, "backchannel_capable", None)
    backchannel_url = None

    if capable is True:
        if camera.onvif_host:
            try:
                backchannel_url = await onvif_service.get_audio_output_uri(
                    camera.onvif_host, camera.onvif_port,
                    decrypt_value(camera.onvif_username) or "admin",
                    decrypt_value(camera.onvif_password or ""),
                )
            except Exception:
                pass
        if not backchannel_url and camera.main_stream_url:
            from urllib.parse import urlparse
            parsed = urlparse(camera.main_stream_url)
            backchannel_url = f"rtsp://{parsed.hostname}:554/backchannel"
    else:
        if camera.onvif_host:
            try:
                backchannel_url = await onvif_service.get_audio_output_uri(
                    camera.onvif_host, camera.onvif_port,
                    decrypt_value(camera.onvif_username) or "admin",
                    decrypt_value(camera.onvif_password or ""),
                )
            except Exception:
                pass

        if not backchannel_url and camera.main_stream_url:
            from urllib.parse import urlparse
            parsed = urlparse(camera.main_stream_url)
            backchannel_url = f"rtsp://{parsed.hostname}:554/backchannel"

        capable = backchannel_url is not None
        camera.backchannel_capable = capable
        await db.commit()

    if not backchannel_url:
        raise HTTPException(503, "Two-way audio not configured on this camera")

    ok = await twoway_audio_service.start_session(camera_id, backchannel_url)
    if not ok:
        raise HTTPException(500, "Failed to start two-way audio session")

    logger.info(
        f"[audio-path] camera={camera_id} path=ffmpeg_pcm "
        f"capable={capable}"
    )
    return {
        "camera_id": camera_id,
        "status": "active",
        "backchannel_url": backchannel_url,
        "backchannel_capable_cached": camera.backchannel_capable,
        "note": "FFmpeg PCM→RTSP fallback active. For WebRTC, use /audio/backchannel/webrtc-signal instead.",
    }


@router.post("/{camera_id}/audio/backchannel/stop")
async def stop_backchannel(
    camera_id: str,
    user: dict = Depends(require_permission("view_live")),
):
    """Stop two-way audio backchannel session."""
    await twoway_audio_service.stop_session(camera_id)
    return {"camera_id": camera_id, "status": "stopped"}


@router.post("/{camera_id}/audio/backchannel/recheck")
async def recheck_backchannel(
    camera_id: str,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Reset the backchannel capability cache to NULL so the next Talk press
    re-tests whether the camera supports two-way audio.
    """
    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    camera.backchannel_capable = None
    await db.commit()
    return {
        "camera_id": camera_id,
        "backchannel_capable": None,
        "message": "Backchannel capability cache reset. Next Talk press will re-probe.",
    }


class BackchannelWebrtcSignalRequest(BaseModel):
    sdp: str


@router.post("/{camera_id}/audio/backchannel/webrtc-signal")
async def backchannel_webrtc_signal(
    camera_id: str,
    body: BackchannelWebrtcSignalRequest,
    user: dict = Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    """
    WebRTC publish signaling endpoint for two-way audio.

    The browser creates an RTCPeerConnection, adds mic audio tracks, creates
    an SDP offer, and POSTs it here.  This endpoint:

    1. Looks up the camera's source URL.
    2. Re-registers the go2rtc stream with ``?backchannel=1`` so go2rtc opens
       a backchannel toward the camera when the WebRTC push session connects.
    3. Forwards the SDP offer to go2rtc ``POST /api/webrtc?src=<id>&mode=push``
       and returns the SDP answer to the browser.

    Returns 503 if the camera has no usable source URL (backchannel
    unsupported), 502 if go2rtc signaling fails.
    """
    from app.services.go2rtc_manager import go2rtc_manager

    camera = await svc.get_by_id(db, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")

    if getattr(camera, "backchannel_capable", None) is False:
        raise HTTPException(503, "Two-way audio not supported by this camera (cached). "
                                 "Use /audio/backchannel/recheck to re-probe.")

    source_url = camera.main_stream_url
    if not source_url:
        raise HTTPException(503, "Camera does not support two-way audio")

    stream_id = camera_id

    if getattr(camera, "backchannel_capable", None) is not True:
        ok = await go2rtc_manager.add_stream_with_backchannel(stream_id, source_url)
        if not ok:
            logger.warning(f"go2rtc backchannel re-register failed for {camera_id}; proceeding anyway")
    else:
        logger.debug(f"backchannel_webrtc_signal: skipping re-registration for {camera_id} (cached capable=True)")

    answer_sdp = await go2rtc_manager.webrtc_signal_publish(stream_id, body.sdp)
    if not answer_sdp:
        if getattr(camera, "backchannel_capable", None) is None:
            camera.backchannel_capable = False
            await db.commit()
        raise HTTPException(502, "go2rtc WebRTC publish signaling failed — camera may not support two-way audio")

    if getattr(camera, "backchannel_capable", None) is None:
        camera.backchannel_capable = True
        await db.commit()

    logger.info(
        f"[audio-path] camera={camera_id} path=webrtc_publish "
        f"backchannel_capable={getattr(camera, 'backchannel_capable', None)} "
        f"stream_id={stream_id}"
    )
    return {"sdp": answer_sdp, "audio_path": "webrtc"}
