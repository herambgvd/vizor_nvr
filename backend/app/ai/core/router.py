# =============================================================================
# AI scenario catalog + licensing API.
#   GET  /api/ai/scenarios            — catalog (all, with license/enable state)
#   GET  /api/ai/scenarios/active     — operable scenarios (licensed + enabled)
#   GET  /api/ai/scenarios/{id}       — one scenario
#   PUT  /api/ai/scenarios/{id}/enable — operator toggle (requires licensed)
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import get_current_user, require_permission
from app.auth.api_keys import require_scope
from app.ai.models import ScenarioResponse, ScenarioToggle
from app.ai.core.service import ai_service, ScenarioNotOperable
from app.ai.core.registry import register_manifest, unregister, ManifestError

router = APIRouter(prefix="/api/ai", tags=["AI Scenarios"])


def _to_response(scenario, active_count: int) -> ScenarioResponse:
    r = ScenarioResponse.model_validate(scenario)
    r.active_camera_count = active_count
    return r


@router.get("/scenarios", response_model=list[ScenarioResponse])
async def list_scenarios(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scenarios = await ai_service.list_scenarios(db)
    out = []
    for s in scenarios:
        cnt = await ai_service.active_camera_count(db, s.id)
        out.append(_to_response(s, cnt))
    return out


@router.get("/scenarios/active", response_model=list[ScenarioResponse])
async def list_active_scenarios(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scenarios = await ai_service.list_scenarios(db, operable_only=True)
    out = []
    for s in scenarios:
        cnt = await ai_service.active_camera_count(db, s.id)
        out.append(_to_response(s, cnt))
    return out


# ── Plugin registry (Phase 1) ───────────────────────────────────────────────
# Scenarios self-register from their manifest (scenario.json); the bridge may
# also register manifests from a scenarios.d/ dir. Auth via the bridge API key
# (events:ingest scope) so unattended scenario containers can register on boot.

@router.post("/scenarios/register", response_model=ScenarioResponse)
async def register_scenario(
    manifest: dict,
    key=Depends(require_scope("events:ingest")),
    db: AsyncSession = Depends(get_db),
):
    """Upsert a scenario catalog row from its manifest, then re-project the
    signed license so an entitled-but-just-registered scenario flips licensed."""
    try:
        row = await register_manifest(db, manifest)
    except ManifestError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    await db.commit()
    await ai_service.sync_licensing(db)        # entitlement ↔ manifest match
    await db.refresh(row)
    cnt = await ai_service.active_camera_count(db, row.id)
    return _to_response(row, cnt)


@router.get("/scenarios/registry")
async def list_registry(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """All known scenarios with plugin/registration state."""
    scenarios = await ai_service.list_scenarios(db)
    return [
        {
            "slug": s.slug, "name": s.name, "version": s.version,
            "source": s.source, "registered": s.registered,
            "licensed": s.licensed, "enabled": s.enabled,
            "capabilities": s.capabilities or [],
            "registered_at": s.registered_at.isoformat() if s.registered_at else None,
        }
        for s in scenarios
    ]


@router.delete("/scenarios/{slug}/register")
async def unregister_scenario(
    slug: str,
    user=Depends(require_permission("manage_system")),
    db: AsyncSession = Depends(get_db),
):
    """Soft-uninstall a scenario (keeps row + per-camera config for re-install)."""
    ok = await unregister(db, slug)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "scenario not found")
    return {"ok": True, "slug": slug}


@router.get("/scenarios/{scenario_id}", response_model=ScenarioResponse)
async def get_scenario(
    scenario_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    s = await ai_service.get_scenario(db, scenario_id)
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "scenario not found")
    cnt = await ai_service.active_camera_count(db, s.id)
    return _to_response(s, cnt)


@router.put("/scenarios/{scenario_id}/enable", response_model=ScenarioResponse)
async def toggle_scenario(
    scenario_id: str,
    body: ScenarioToggle,
    user=Depends(require_permission("manage_system")),
    db: AsyncSession = Depends(get_db),
):
    s = await ai_service.get_scenario(db, scenario_id)
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "scenario not found")
    try:
        s = await ai_service.set_enabled(db, s, body.enabled)
    except ScenarioNotOperable as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))
    cnt = await ai_service.active_camera_count(db, s.id)
    return _to_response(s, cnt)
