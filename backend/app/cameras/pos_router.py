# =============================================================================
# POS / ATM Overlay Router
# =============================================================================

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.core.dependencies import get_current_user, require_permission
from app.services.pos_overlay_service import pos_overlay_service

router = APIRouter(prefix="/pos-overlay", tags=["POS Overlay"])


class POSTextRequest(BaseModel):
    text: str


@router.post("/{camera_id}")
async def set_pos_text(
    camera_id: str,
    body: POSTextRequest,
    user: dict = Depends(require_permission("manage_camera")),
):
    """Push POS/ATM text overlay for a camera.

    The text will be burned into the camera's recording via FFmpeg drawtext.
    """
    pos_overlay_service.set_text(camera_id, body.text)
    return {"ok": True, "camera_id": camera_id, "text": body.text}


@router.delete("/{camera_id}")
async def clear_pos_text(
    camera_id: str,
    user: dict = Depends(require_permission("manage_camera")),
):
    """Clear POS text overlay for a camera."""
    pos_overlay_service.clear_text(camera_id)
    return {"ok": True, "camera_id": camera_id}


@router.get("/{camera_id}")
async def get_pos_text(
    camera_id: str,
    user: dict = Depends(require_permission("view_live")),
):
    """Get current POS text for a camera."""
    text = pos_overlay_service.get_text(camera_id)
    return {"camera_id": camera_id, "text": text}
