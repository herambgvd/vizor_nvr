# =============================================================================
# Spot Output Router — API for managing physical monitor outputs
# =============================================================================

import uuid
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.core.dependencies import get_current_user
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
async def create_spot_output(data: SpotOutputCreate, db=Depends(get_db), user=Depends(get_current_user)):
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

    if spot.is_active:
        ok = await spot_output_service.create_spot_stream(spot)
        if not ok:
            logger.warning(f"Spot output stream creation failed for {spot.id}")

    return _to_response(spot)


@router.get("/{spot_id}", response_model=SpotOutputResponse)
async def get_spot_output(spot_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    result = await db.execute(select(SpotOutput).where(SpotOutput.id == spot_id))
    spot = result.scalar_one_or_none()
    if not spot:
        raise HTTPException(status_code=404, detail="Spot output not found")
    return _to_response(spot)


@router.patch("/{spot_id}", response_model=SpotOutputResponse)
async def update_spot_output(spot_id: str, data: SpotOutputUpdate, db=Depends(get_db), user=Depends(get_current_user)):
    result = await db.execute(select(SpotOutput).where(SpotOutput.id == spot_id))
    spot = result.scalar_one_or_none()
    if not spot:
        raise HTTPException(status_code=404, detail="Spot output not found")

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
        await spot_output_service.update_spot_stream(spot)
    else:
        await spot_output_service.delete_spot_stream(spot.stream_name)

    return _to_response(spot)


@router.delete("/{spot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_spot_output(spot_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    result = await db.execute(select(SpotOutput).where(SpotOutput.id == spot_id))
    spot = result.scalar_one_or_none()
    if not spot:
        raise HTTPException(status_code=404, detail="Spot output not found")

    await spot_output_service.delete_spot_stream(spot.stream_name)
    await db.delete(spot)
    await db.commit()
    return None
