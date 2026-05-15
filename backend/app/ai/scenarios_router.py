# =============================================================================
# AI Scenarios Router
#
# Public catalog of AI capabilities (FRS, People Counting, PPE, LPR, etc.)
# and per-camera enablement/configuration. Frontend reads catalog to show
# scenario tabs + roadmap "Coming Soon" badges. Per-camera config drives
# Metropolis Perception / Behavior Analytics pipelines.
#
# Endpoints:
#   GET    /api/ai/scenarios                              — catalog
#   GET    /api/ai/scenarios/{slug}                        — single scenario
#   GET    /api/ai/cameras/{camera_id}/scenarios           — per-camera config list
#   PUT    /api/ai/cameras/{camera_id}/scenarios/{slug}    — enable/configure
#   DELETE /api/ai/cameras/{camera_id}/scenarios/{slug}    — disable + remove
# =============================================================================

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AIScenario, CameraAIConfig
from app.core.dependencies import get_current_user, require_permission
from app.database import get_db


router = APIRouter(prefix="/api/ai", tags=["AI Scenarios"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ScenarioOut(BaseModel):
    slug: str
    name: str
    description: Optional[str]
    category: Optional[str]
    tier: str
    status: str
    metropolis_service: Optional[str]
    requires_models: List[str]
    default_config: dict
    use_cases: Optional[List[str]] = None
    enabled: bool
    module_tabs: Optional[List[str]] = None
    camera_config_schema: Optional[dict] = None
    licensed: bool = True   # derived from license file at response time

    class Config:
        from_attributes = True


class CameraScenarioConfig(BaseModel):
    scenario_slug: str
    enabled: bool
    config: dict


class CameraScenarioUpsert(BaseModel):
    enabled: bool = True
    config: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

@router.get(
    "/scenarios",
    response_model=List[ScenarioOut],
    summary="List AI scenarios catalog (filterable by category / tier / status)",
)
async def list_scenarios(
    category: Optional[str] = Query(None, description="person|vehicle|behavior|safety|security|search"),
    tier: Optional[str] = Query(None, description="free|pro|business|enterprise"),
    status_filter: Optional[str] = Query(None, alias="status", description="ga|beta|planned"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[ScenarioOut]:
    stmt = select(AIScenario)
    if category:
        stmt = stmt.where(AIScenario.category == category)
    if tier:
        stmt = stmt.where(AIScenario.tier == tier)
    if status_filter:
        stmt = stmt.where(AIScenario.status == status_filter)
    stmt = stmt.order_by(AIScenario.category, AIScenario.name)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    from app.license.service import get_license_service
    lic = get_license_service()
    out: List[ScenarioOut] = []
    for r in rows:
        m = ScenarioOut.model_validate(r)
        # When no license installed, treat every GA scenario as licensed
        # (dev mode). When licensed, mark only whitelisted entries.
        m.licensed = (
            (not lic.is_active()) or lic.is_scenario_licensed(r.slug)
        )
        out.append(m)
    return out


@router.get(
    "/scenarios/{slug}",
    response_model=ScenarioOut,
    summary="Get one scenario by slug",
)
async def get_scenario(
    slug: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScenarioOut:
    result = await db.execute(select(AIScenario).where(AIScenario.slug == slug))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Scenario '{slug}' not found")
    from app.license.service import get_license_service
    lic = get_license_service()
    m = ScenarioOut.model_validate(row)
    m.licensed = (not lic.is_active()) or lic.is_scenario_licensed(row.slug)
    return m


# ---------------------------------------------------------------------------
# Per-camera scenario config
# ---------------------------------------------------------------------------

@router.get(
    "/cameras/{camera_id}/scenarios",
    response_model=List[CameraScenarioConfig],
    summary="List AI scenarios enabled on a camera",
)
async def list_camera_scenarios(
    camera_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[CameraScenarioConfig]:
    stmt = (
        select(CameraAIConfig, AIScenario)
        .join(AIScenario, AIScenario.id == CameraAIConfig.scenario_id)
        .where(CameraAIConfig.camera_id == camera_id)
    )
    result = await db.execute(stmt)
    out: List[CameraScenarioConfig] = []
    for cfg, scenario in result.all():
        out.append(CameraScenarioConfig(
            scenario_slug=scenario.slug,
            enabled=cfg.enabled,
            config=cfg.config or {},
        ))
    return out


@router.put(
    "/cameras/{camera_id}/scenarios/{slug}",
    response_model=CameraScenarioConfig,
    summary="Enable or update an AI scenario on a camera",
)
async def upsert_camera_scenario(
    camera_id: str,
    slug: str,
    payload: CameraScenarioUpsert,
    user=Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
) -> CameraScenarioConfig:
    # Resolve scenario id from slug
    sc_result = await db.execute(select(AIScenario).where(AIScenario.slug == slug))
    scenario = sc_result.scalar_one_or_none()
    if not scenario:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Scenario '{slug}' not found")
    if scenario.status != "ga":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Scenario '{slug}' is '{scenario.status}', not yet generally available",
        )

    # License gate — scenario must appear in the install's license whitelist
    # AND the camera must not exceed the AI-enabled camera cap.
    from app.license.service import get_license_service
    lic = get_license_service()
    if lic.is_active():
        if not lic.is_scenario_licensed(slug):
            raise HTTPException(
                402,
                f"Scenario '{slug}' is not included in your license",
            )
        # Count distinct cameras currently enabled for any AI scenario.
        # The current camera_id counts only if not already AI-enabled.
        from sqlalchemy import distinct, func as sa_func
        existing_for_cam = (await db.execute(
            select(CameraAIConfig).where(
                CameraAIConfig.camera_id == camera_id,
                CameraAIConfig.enabled.is_(True),
            )
        )).scalars().first()
        if not existing_for_cam:
            ai_cam_count = (await db.execute(
                select(sa_func.count(distinct(CameraAIConfig.camera_id))).where(
                    CameraAIConfig.enabled.is_(True),
                )
            )).scalar() or 0
            if lic.ai_camera_limit() and ai_cam_count >= lic.ai_camera_limit():
                raise HTTPException(
                    402,
                    f"AI camera cap reached: {ai_cam_count}/{lic.ai_camera_limit()}",
                )

    # Validate config against per-scenario Pydantic schema
    from app.ai.scenarios import validate_config
    try:
        validated_config = validate_config(scenario.slug, payload.config)
    except Exception as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Invalid config for scenario '{slug}': {e}",
        )

    # Find existing row or create new one
    existing = await db.execute(
        select(CameraAIConfig).where(
            CameraAIConfig.camera_id == camera_id,
            CameraAIConfig.scenario_id == scenario.id,
        )
    )
    row = existing.scalar_one_or_none()
    if row:
        row.enabled = payload.enabled
        row.config = validated_config
    else:
        row = CameraAIConfig(
            camera_id=camera_id,
            scenario_id=scenario.id,
            enabled=payload.enabled,
            config=validated_config,
        )
        db.add(row)

    await db.commit()
    await db.refresh(row)

    # Notify DeepStream workers to reload config
    try:
        from app.ai.people.router import _publish_reload
        await _publish_reload()
    except Exception:
        pass

    return CameraScenarioConfig(
        scenario_slug=scenario.slug,
        enabled=row.enabled,
        config=row.config or {},
    )


@router.delete(
    "/cameras/{camera_id}/scenarios/{slug}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disable and remove a scenario from a camera",
)
async def disable_camera_scenario(
    camera_id: str,
    slug: str,
    user=Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
) -> None:
    sc_result = await db.execute(select(AIScenario).where(AIScenario.slug == slug))
    scenario = sc_result.scalar_one_or_none()
    if not scenario:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Scenario '{slug}' not found")

    existing = await db.execute(
        select(CameraAIConfig).where(
            CameraAIConfig.camera_id == camera_id,
            CameraAIConfig.scenario_id == scenario.id,
        )
    )
    row = existing.scalar_one_or_none()
    if not row:
        return
    await db.delete(row)
    await db.commit()
