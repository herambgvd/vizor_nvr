# =============================================================================
# FRS forensic investigate + person tour (proxy → bridge HTTP).
#
#   Investigate (forensic snapshot search by query face):
#     POST /api/ai/frs/investigate          (multipart UploadFile + form top_k) → hits
#   Tour (cross-camera where/when a person was seen):
#     GET  /api/ai/frs/tour/timeline/{person_id}                              → entries
#
# The NVR backend stays gRPC-free: these endpoints proxy via httpx to the
# bridge HTTP API (BRIDGE_HTTP_URL), which holds the FRS gRPC client. All
# investigate/tour data lives in the FRS scenario db — NVR adds no tables.
# Reads require an authenticated user.
# =============================================================================
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.core.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai/frs", tags=["FRS Investigate"])

BRIDGE_HTTP_URL = os.getenv("BRIDGE_HTTP_URL", "http://localhost:8099").rstrip("/")

_SEARCH_TIMEOUT = httpx.Timeout(120.0)
_STATUS_TIMEOUT = httpx.Timeout(30.0)


# =============================================================================
# Helpers
# =============================================================================

def _bridge_error(detail: str, exc: Optional[Exception] = None) -> HTTPException:
    if exc is not None:
        logger.warning("[frs-investigate] bridge call failed: %s (%s)", detail, exc)
    else:
        logger.warning("[frs-investigate] bridge call failed: %s", detail)
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
# Investigate (forensic snapshot search by query face)
# =============================================================================

@router.post("/investigate")
async def investigate(
    file: UploadFile = File(...),
    top_k: int = Form(50),
    user=Depends(get_current_user),
):
    """Stream a query face to the bridge and return matching snapshot hits."""
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty upload")
    files = {"file": (file.filename or "image.jpg", data,
                      file.content_type or "application/octet-stream")}
    form = {"top_k": str(top_k)}
    try:
        async with httpx.AsyncClient(timeout=_SEARCH_TIMEOUT) as client:
            resp = await client.post(
                f"{BRIDGE_HTTP_URL}/investigate", data=form, files=files
            )
    except httpx.HTTPError as e:
        raise _bridge_error("failed to reach bridge", e)
    return _passthrough(resp)


# =============================================================================
# Tour (cross-camera where/when a person was seen)
# =============================================================================

@router.get("/tour/timeline/{person_id}")
async def person_tour_timeline(
    person_id: str,
    user=Depends(get_current_user),
):
    """Fetch the cross-camera timeline of where/when a person was seen."""
    try:
        async with httpx.AsyncClient(timeout=_STATUS_TIMEOUT) as client:
            resp = await client.get(
                f"{BRIDGE_HTTP_URL}/person-timeline/{person_id}"
            )
    except httpx.HTTPError as e:
        raise _bridge_error("failed to reach bridge", e)
    return _passthrough(resp)
