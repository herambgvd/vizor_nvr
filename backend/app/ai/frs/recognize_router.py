# =============================================================================
# FRS one-shot image + async video recognition (proxy → bridge HTTP).
#
#   Image (synchronous):
#     POST /api/ai/frs/recognize-image   (multipart UploadFile) → matches
#     POST /api/ai/frs/detect-faces      (multipart UploadFile) → faces
#   Video (asynchronous):
#     POST /api/ai/frs/video-jobs            (UploadFile OR form `path`) → {job_id}
#     GET  /api/ai/frs/video-jobs/{job_id}           → status
#     GET  /api/ai/frs/video-jobs/{job_id}/results   → results
#
# The NVR backend stays gRPC-free: these endpoints proxy via httpx to the
# bridge HTTP API (BRIDGE_HTTP_URL), which holds the FRS gRPC client.
# Reads require an authenticated user; video submission requires "manage_system".
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

router = APIRouter(prefix="/api/ai/frs", tags=["FRS Recognize"])

BRIDGE_HTTP_URL = os.getenv("BRIDGE_HTTP_URL", "http://localhost:8099").rstrip("/")

# Proxy timeouts: image recognition is fast; video upload may be large.
_IMAGE_TIMEOUT = httpx.Timeout(60.0)
_VIDEO_TIMEOUT = httpx.Timeout(300.0)
_STATUS_TIMEOUT = httpx.Timeout(30.0)


# =============================================================================
# Helpers
# =============================================================================

def _bridge_error(detail: str, exc: Optional[Exception] = None) -> HTTPException:
    if exc is not None:
        logger.warning("[frs-recognize] bridge call failed: %s (%s)", detail, exc)
    else:
        logger.warning("[frs-recognize] bridge call failed: %s", detail)
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

@router.post("/recognize-image")
async def recognize_image(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    """Stream an uploaded image to the bridge for one-shot face recognition."""
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty upload")
    files = {"file": (file.filename or "image.jpg", data,
                      file.content_type or "application/octet-stream")}
    try:
        async with httpx.AsyncClient(timeout=_IMAGE_TIMEOUT) as client:
            resp = await client.post(
                f"{BRIDGE_HTTP_URL}/recognize-image", files=files
            )
    except httpx.HTTPError as e:
        raise _bridge_error("failed to reach bridge", e)
    return _passthrough(resp)


@router.post("/detect-faces")
async def detect_faces(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    """Stream an uploaded image to the bridge for face detection (no recognition)."""
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty upload")
    files = {"file": (file.filename or "image.jpg", data,
                      file.content_type or "application/octet-stream")}
    try:
        async with httpx.AsyncClient(timeout=_IMAGE_TIMEOUT) as client:
            resp = await client.post(
                f"{BRIDGE_HTTP_URL}/detect-faces", files=files
            )
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
    recognize: Optional[bool] = Form(None),
    check_liveness: Optional[bool] = Form(None),
    min_confidence: Optional[float] = Form(None),
    user=Depends(require_permission("manage_system")),
):
    """Submit a video for async recognition. Either upload a `file` or pass a
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
    if recognize is not None:
        data["recognize"] = str(recognize).lower()
    if check_liveness is not None:
        data["check_liveness"] = str(check_liveness).lower()
    if min_confidence is not None:
        data["min_confidence"] = str(min_confidence)

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
                f"{BRIDGE_HTTP_URL}/video-jobs",
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
    """Poll the bridge for a video job's status."""
    try:
        async with httpx.AsyncClient(timeout=_STATUS_TIMEOUT) as client:
            resp = await client.get(f"{BRIDGE_HTTP_URL}/video-jobs/{job_id}")
    except httpx.HTTPError as e:
        raise _bridge_error("failed to reach bridge", e)
    return _passthrough(resp)


@router.get("/video-jobs/{job_id}/results")
async def get_video_job_results(
    job_id: str,
    user=Depends(get_current_user),
):
    """Fetch the recognition events for a completed video job."""
    try:
        async with httpx.AsyncClient(timeout=_STATUS_TIMEOUT) as client:
            resp = await client.get(
                f"{BRIDGE_HTTP_URL}/video-jobs/{job_id}/results"
            )
    except httpx.HTTPError as e:
        raise _bridge_error("failed to reach bridge", e)
    return _passthrough(resp)
