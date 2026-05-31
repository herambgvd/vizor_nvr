# =============================================================================
# PPE one-shot image + async video compliance detection (proxy → bridge HTTP).
#
#   Image (synchronous):
#     POST /api/ai/ppe/detect        (multipart UploadFile) → per-person compliance
#     POST /api/ai/ppe/detect-pose   (multipart UploadFile) → persons + keypoints
#   Video (asynchronous):
#     POST /api/ai/ppe/video-jobs            (UploadFile OR form `path`) → {job_id}
#     GET  /api/ai/ppe/video-jobs/{job_id}           → status
#     GET  /api/ai/ppe/video-jobs/{job_id}/results   → results
#
# The NVR backend stays gRPC-free and holds no PPE state: these endpoints proxy
# via httpx to the bridge HTTP API (BRIDGE_HTTP_URL), which holds the PPE gRPC
# client. Reads require an authenticated user; video submission requires
# "manage_system". Mirrors app/ai/frs/recognize_router.py.
#
# PPE events/reports use the GENERIC NVR event store: the bridge ingests live
# PPE events to /api/events/ingest, and the global Events page filters them by
# source_service='ppe'. The PPE workspace Events/Reports tabs query that same
# generic events endpoint — no PPE-specific query endpoint is added here.
# =============================================================================
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx
from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, UploadFile, status,
)

from app.core.dependencies import get_current_user, require_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai/ppe", tags=["PPE"])

BRIDGE_HTTP_URL = os.getenv("BRIDGE_HTTP_URL", "http://localhost:8099").rstrip("/")

# Proxy timeouts: image detection is fast; video upload may be large.
_IMAGE_TIMEOUT = httpx.Timeout(60.0)
_VIDEO_TIMEOUT = httpx.Timeout(300.0)
_STATUS_TIMEOUT = httpx.Timeout(30.0)


# =============================================================================
# Helpers
# =============================================================================

def _bridge_error(detail: str, exc: Optional[Exception] = None) -> HTTPException:
    if exc is not None:
        logger.warning("[ppe-detect] bridge call failed: %s (%s)", detail, exc)
    else:
        logger.warning("[ppe-detect] bridge call failed: %s", detail)
    return HTTPException(status.HTTP_502_BAD_GATEWAY, detail=detail)


def _passthrough(resp: httpx.Response):
    """Return the bridge JSON body, mapping non-2xx into a 502."""
    if resp.status_code >= 400:
        try:
            body = resp.json()
            detail = body.get("detail", body)
        except Exception:
            detail = resp.text or f"bridge returned {resp.status_code}"
        raise _bridge_error(f"bridge error: {detail}")
    try:
        return resp.json()
    except Exception as e:
        raise _bridge_error("bridge returned non-JSON response", e)


# =============================================================================
# Image (synchronous)
# =============================================================================

@router.post("/detect")
async def detect_ppe(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    """Stream an uploaded image to the bridge for one-shot PPE compliance."""
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty upload")
    files = {"file": (file.filename or "image.jpg", data,
                      file.content_type or "application/octet-stream")}
    try:
        async with httpx.AsyncClient(timeout=_IMAGE_TIMEOUT) as client:
            resp = await client.post(f"{BRIDGE_HTTP_URL}/ppe/detect", files=files)
    except httpx.HTTPError as e:
        raise _bridge_error("failed to reach bridge", e)
    return _passthrough(resp)


@router.post("/detect-pose")
async def detect_pose(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    """Stream an uploaded image to the bridge for pose detection (persons + keypoints)."""
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty upload")
    files = {"file": (file.filename or "image.jpg", data,
                      file.content_type or "application/octet-stream")}
    try:
        async with httpx.AsyncClient(timeout=_IMAGE_TIMEOUT) as client:
            resp = await client.post(f"{BRIDGE_HTTP_URL}/ppe/detect-pose", files=files)
    except httpx.HTTPError as e:
        raise _bridge_error("failed to reach bridge", e)
    return _passthrough(resp)


# =============================================================================
# Video (asynchronous)
# =============================================================================

@router.post("/video-jobs")
async def submit_video_job(
    file: Optional[UploadFile] = File(None),
    path: Optional[str] = Form(None),
    sample_fps: Optional[float] = Form(None),
    min_confidence: Optional[float] = Form(None),
    track: Optional[bool] = Form(None),
    user=Depends(require_permission("manage_system")),
):
    """Submit a video for async PPE compliance. Either upload a `file` or pass a
    server-side `path`. Forwards to the bridge and returns its {job_id}."""
    if file is None and not path:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "provide either a file upload or a path"
        )

    data = {}
    if path:
        data["path"] = path
    if sample_fps is not None:
        data["sample_fps"] = str(sample_fps)
    if min_confidence is not None:
        data["min_confidence"] = str(min_confidence)
    if track is not None:
        data["track"] = str(track).lower()

    files = None
    if file is not None:
        blob = await file.read()
        if not blob:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty upload")
        files = {"file": (file.filename or "video.mp4", blob,
                          file.content_type or "application/octet-stream")}

    try:
        async with httpx.AsyncClient(timeout=_VIDEO_TIMEOUT) as client:
            resp = await client.post(
                f"{BRIDGE_HTTP_URL}/ppe/video-jobs",
                data=data or None,
                files=files,
            )
    except httpx.HTTPError as e:
        raise _bridge_error("failed to reach bridge", e)
    return _passthrough(resp)


@router.get("/video-jobs/{job_id}")
async def get_video_job(
    job_id: str,
    user=Depends(get_current_user),
):
    """Poll the bridge for a PPE video job's status."""
    try:
        async with httpx.AsyncClient(timeout=_STATUS_TIMEOUT) as client:
            resp = await client.get(f"{BRIDGE_HTTP_URL}/ppe/video-jobs/{job_id}")
    except httpx.HTTPError as e:
        raise _bridge_error("failed to reach bridge", e)
    return _passthrough(resp)


@router.get("/video-jobs/{job_id}/results")
async def get_video_job_results(
    job_id: str,
    user=Depends(get_current_user),
):
    """Fetch the compliance events for a completed PPE video job."""
    try:
        async with httpx.AsyncClient(timeout=_STATUS_TIMEOUT) as client:
            resp = await client.get(
                f"{BRIDGE_HTTP_URL}/ppe/video-jobs/{job_id}/results"
            )
    except httpx.HTTPError as e:
        raise _bridge_error("failed to reach bridge", e)
    return _passthrough(resp)
