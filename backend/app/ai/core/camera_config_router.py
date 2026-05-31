# =============================================================================
# AI per-camera scenario enablement API (F3).
#   GET    /api/ai/scenarios/{scenario_id}/cameras  — configs for a scenario
#   POST   /api/ai/scenarios/{scenario_id}/cameras  — assign a camera
#   GET    /api/ai/camera-configs/{id}              — one config
#   PUT    /api/ai/camera-configs/{id}              — update enable/config
#   DELETE /api/ai/camera-configs/{id}              — unassign
# =============================================================================
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import get_current_user, require_permission
from app.ai.models import (
    CameraAIConfigCreate, CameraAIConfigUpdate, CameraAIConfigResponse,
)
from app.ai.core.service import ai_service, CameraCapExceeded, ScenarioNotOperable
from app.ai.core.camera_config_service import (
    camera_config_service, CameraConfigConflict,
)

router = APIRouter(prefix="/api/ai", tags=["AI Camera Config"])


class CameraAIConfigWithName(CameraAIConfigResponse):
    camera_name: Optional[str] = None


async def _to_response(db: AsyncSession, config) -> CameraAIConfigWithName:
    r = CameraAIConfigWithName.model_validate(config)
    r.camera_name = await camera_config_service.get_camera_name(db, config.camera_id)
    return r


@router.get(
    "/scenarios/{scenario_id}/cameras",
    response_model=list[CameraAIConfigWithName],
)
async def list_scenario_cameras(
    scenario_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scenario = await ai_service.get_scenario(db, scenario_id)
    if scenario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "scenario not found")
    configs = await camera_config_service.list_for_scenario(db, scenario_id)
    return [await _to_response(db, c) for c in configs]


@router.post(
    "/scenarios/{scenario_id}/cameras",
    response_model=CameraAIConfigWithName,
    status_code=status.HTTP_201_CREATED,
)
async def assign_camera(
    scenario_id: str,
    body: CameraAIConfigCreate,
    user=Depends(require_permission("manage_system")),
    db: AsyncSession = Depends(get_db),
):
    # Path scenario_id is authoritative.
    body.scenario_id = scenario_id
    try:
        config = await camera_config_service.create(db, body)
    except (CameraCapExceeded, ScenarioNotOperable) as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))
    except CameraConfigConflict as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    return await _to_response(db, config)


@router.get("/camera-configs/{config_id}", response_model=CameraAIConfigWithName)
async def get_camera_config(
    config_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    config = await camera_config_service.get(db, config_id)
    if config is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "camera config not found")
    return await _to_response(db, config)


@router.put("/camera-configs/{config_id}", response_model=CameraAIConfigWithName)
async def update_camera_config(
    config_id: str,
    body: CameraAIConfigUpdate,
    user=Depends(require_permission("manage_system")),
    db: AsyncSession = Depends(get_db),
):
    try:
        config = await camera_config_service.update(db, config_id, body)
    except (CameraCapExceeded, ScenarioNotOperable) as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))
    if config is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "camera config not found")
    return await _to_response(db, config)


@router.delete("/camera-configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unassign_camera(
    config_id: str,
    user=Depends(require_permission("manage_system")),
    db: AsyncSession = Depends(get_db),
):
    ok = await camera_config_service.delete(db, config_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "camera config not found")
    return None


# ── Bridge bookkeeping ───────────────────────────────────────────────────
from pydantic import BaseModel  # noqa: E402


class _StreamStateUpdate(BaseModel):
    state: str                  # "running" | "stopped" | "error"
    error: Optional[str] = None


@router.put("/camera-configs/{config_id}/state", response_model=CameraAIConfigResponse)
async def report_stream_state(
    config_id: str,
    body: _StreamStateUpdate,
    user=Depends(require_permission("manage_system")),
    db: AsyncSession = Depends(get_db),
):
    """Called by the bridge to record reconciled per-stream state."""
    config = await camera_config_service.set_stream_state(
        db, config_id, body.state, body.error
    )
    if config is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "camera config not found")
    return await _to_response(db, config)
