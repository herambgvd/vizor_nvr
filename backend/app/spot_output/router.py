# =============================================================================
# Spot Output Router — API for managing physical monitor outputs
# =============================================================================

import uuid
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy import select

from app.database import get_db
from app.core.dependencies import get_current_user, get_admin_user
from app.core.audit_logger import write_audit, client_ip
from app.spot_output.models import SpotOutput, SpotOutputCreate, SpotOutputUpdate, SpotOutputResponse
from app.spot_output.service import spot_output_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/spot-outputs", tags=["Spot Output"])


def _to_response(spot) -> SpotOutputResponse:
    return SpotOutputResponse(
        id=spot.id,
        name=spot.name,
        layout=spot.layout,
        camera_ids=spot.camera_ids or [],
        quality=spot.quality,
        stream_name=spot.stream_name,
        is_active=spot.is_active,
        rtsp_url=spot_output_service.get_rtsp_url(spot.stream_name),
        created_at=spot.created_at,
    )


@router.get("", response_model=List[SpotOutputResponse])
async def list_spot_outputs(db=Depends(get_db), user=Depends(get_current_user)):
    result = await db.execute(select(SpotOutput).order_by(SpotOutput.created_at))
    spots = result.scalars().all()
    return [_to_response(s) for s in spots]


@router.post("", response_model=SpotOutputResponse, status_code=status.HTTP_201_CREATED)
async def create_spot_output(
    request: Request,
    data: SpotOutputCreate,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    stream_name = f"spot_{uuid.uuid4().hex[:8]}"
    spot = SpotOutput(
        name=data.name,
        layout=data.layout,
        camera_ids=data.camera_ids or [],
        quality=data.quality,
        stream_name=stream_name,
        is_active=data.is_active,
    )
    db.add(spot)
    await db.commit()
    await db.refresh(spot)

    if spot.is_active and spot.camera_ids:
        ok = await spot_output_service.create_spot_stream(spot)
        if not ok:
            logger.warning(f"[spot-output] Stream creation failed for spot {spot.id}")
    elif spot.is_active and not spot.camera_ids:
        logger.info(f"[spot-output] Created spot {spot.id} with no cameras — stream not started")

    await write_audit(
        action="spot_output_created",
        actor=user.get("username", ""),
        detail={"id": spot.id, "name": spot.name, "layout": spot.layout, "camera_ids": spot.camera_ids},
        ip=client_ip(request),
    )
    return _to_response(spot)


@router.get("/{spot_id}", response_model=SpotOutputResponse)
async def get_spot_output(spot_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    result = await db.execute(select(SpotOutput).where(SpotOutput.id == spot_id))
    spot = result.scalar_one_or_none()
    if not spot:
        raise HTTPException(status_code=404, detail="Spot output not found")
    return _to_response(spot)


@router.patch("/{spot_id}", response_model=SpotOutputResponse)
async def update_spot_output(
    request: Request,
    spot_id: str,
    data: SpotOutputUpdate,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(select(SpotOutput).where(SpotOutput.id == spot_id))
    spot = result.scalar_one_or_none()
    if not spot:
        raise HTTPException(status_code=404, detail="Spot output not found")

    old_layout = spot.layout
    old_cameras = list(spot.camera_ids or [])

    if data.name is not None:
        spot.name = data.name
    if data.layout is not None:
        spot.layout = data.layout
    if data.camera_ids is not None:
        spot.camera_ids = data.camera_ids
    if data.quality is not None:
        spot.quality = data.quality
    if data.is_active is not None:
        spot.is_active = data.is_active

    await db.commit()
    await db.refresh(spot)

    if spot.is_active:
        if spot.camera_ids:
            await spot_output_service.update_spot_stream(spot)
        else:
            # No cameras — remove stale stream but keep record active
            await spot_output_service.delete_spot_stream(spot.stream_name)
            logger.info(f"[spot-output] Spot {spot.id} has no cameras — stream removed")
    else:
        await spot_output_service.delete_spot_stream(spot.stream_name)

    await write_audit(
        action="spot_output_updated",
        actor=user.get("username", ""),
        detail={
            "id": spot.id,
            "name": spot.name,
            "layout_before": old_layout,
            "layout_after": spot.layout,
            "cameras_before": old_cameras,
            "cameras_after": list(spot.camera_ids or []),
            "is_active": spot.is_active,
        },
        ip=client_ip(request),
    )
    return _to_response(spot)


@router.delete("/{spot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_spot_output(
    request: Request,
    spot_id: str,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(select(SpotOutput).where(SpotOutput.id == spot_id))
    spot = result.scalar_one_or_none()
    if not spot:
        raise HTTPException(status_code=404, detail="Spot output not found")

    await spot_output_service.delete_spot_stream(spot.stream_name)
    await db.delete(spot)
    await db.commit()

    await write_audit(
        action="spot_output_deleted",
        actor=user.get("username", ""),
        detail={"id": spot_id, "name": spot.name},
        ip=client_ip(request),
    )
    return None


@router.post("/{spot_id}/preview")
async def preview_spot_output(
    spot_id: str,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    """Return a JPEG preview snapshot of the spot output's first camera.

    Operators can use this to confirm the layout and stream before committing
    decoder-wall changes.  Returns a JPEG image (Content-Type: image/jpeg).
    If the camera does not have a snapshot available, returns 404.
    """
    result = await db.execute(select(SpotOutput).where(SpotOutput.id == spot_id))
    spot = result.scalar_one_or_none()
    if not spot:
        raise HTTPException(status_code=404, detail="Spot output not found")

    camera_ids = spot.camera_ids or []
    if not camera_ids:
        raise HTTPException(
            status_code=422,
            detail="Spot output has no cameras configured — cannot generate preview",
        )

    # Fetch snapshot for the first camera in the layout
    first_camera_id = camera_ids[0]
    import os
    from app.config import settings as _settings

    snapshot_path = os.path.join(
        _settings.THUMBNAIL_PATH, f"{first_camera_id}_latest.jpg"
    )
    if os.path.exists(snapshot_path):
        try:
            with open(snapshot_path, "rb") as fh:
                data = fh.read()
            return Response(content=data, media_type="image/jpeg")
        except OSError as exc:
            logger.warning(f"[spot-output] Preview read failed for {spot_id}: {exc}")

    raise HTTPException(
        status_code=404,
        detail=(
            f"No snapshot available for camera {first_camera_id}. "
            "Snapshots are generated by the camera monitor — ensure the camera is online."
        ),
    )
