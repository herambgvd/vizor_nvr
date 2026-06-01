# =============================================================================
# AIService — scenario catalog queries, license sync, camera-cap enforcement.
#
# Licensing model: the signed license carries `features` (slugs like "frs")
# and an optional `feature_limits` map ({"frs": 8}) for per-scenario camera
# caps. `sync_licensing()` projects that onto ai_scenarios.licensed/camera_limit
# at boot and on license change. An operator may then `enabled`-toggle any
# licensed scenario. A scenario is OPERABLE iff licensed AND enabled.
# =============================================================================
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AIScenario, CameraAIConfig

logger = logging.getLogger(__name__)


class CameraCapExceeded(Exception):
    def __init__(self, scenario_slug: str, limit: int):
        super().__init__(f"camera limit reached for {scenario_slug} ({limit})")
        self.scenario_slug = scenario_slug
        self.limit = limit


class ScenarioNotOperable(Exception):
    def __init__(self, scenario_slug: str, reason: str):
        super().__init__(f"scenario {scenario_slug} not operable: {reason}")
        self.scenario_slug = scenario_slug
        self.reason = reason


class AIService:
    # ── License projection ──────────────────────────────────────────────
    @staticmethod
    async def sync_licensing(db: AsyncSession) -> None:
        """Project the signed license onto ai_scenarios.{licensed,camera_limit}.
        Called at boot (after license load + seed) and after license change."""
        from app.license.service import get_license_service

        lic = get_license_service()
        # Licensed AI scenarios come from the signed license `scenarios` list;
        # the per-AI-camera cap is `ai_camera_limit` (falls back to camera_limit).
        scenarios = set(lic.scenarios()) if lic.is_active() else set()
        ai_cap = lic.ai_camera_limit() if lic.is_active() else 0
        if not ai_cap:
            ai_cap = lic.camera_limit() if lic.is_active() else 0

        rows = (await db.execute(select(AIScenario))).scalars().all()
        for s in rows:
            licensed = s.slug in scenarios
            s.licensed = licensed
            if not licensed:
                s.enabled = False           # can't run an unlicensed scenario
                s.camera_limit = 0
            else:
                s.camera_limit = int(ai_cap or 0)
        await db.commit()
        logger.info("[ai] licensing synced: scenarios=%s ai_cap=%s",
                    sorted(scenarios), ai_cap)

    # ── Queries ─────────────────────────────────────────────────────────
    @staticmethod
    async def list_scenarios(db: AsyncSession, operable_only: bool = False):
        q = select(AIScenario).order_by(AIScenario.name)
        rows = (await db.execute(q)).scalars().all()
        if operable_only:
            # OPERABLE = plugin installed (registered) ∧ licensed ∧ operator-enabled.
            rows = [s for s in rows if s.registered and s.licensed and s.enabled]
        return rows

    @staticmethod
    async def get_scenario(db: AsyncSession, scenario_id: str) -> Optional[AIScenario]:
        return (await db.execute(
            select(AIScenario).where(AIScenario.id == scenario_id)
        )).scalar_one_or_none()

    @staticmethod
    async def get_scenario_by_slug(db: AsyncSession, slug: str) -> Optional[AIScenario]:
        return (await db.execute(
            select(AIScenario).where(AIScenario.slug == slug)
        )).scalar_one_or_none()

    @staticmethod
    async def active_camera_count(db: AsyncSession, scenario_id: str) -> int:
        return int((await db.execute(
            select(func.count(CameraAIConfig.id)).where(
                CameraAIConfig.scenario_id == scenario_id,
                CameraAIConfig.enabled.is_(True),
            )
        )).scalar() or 0)

    # ── Mutations ───────────────────────────────────────────────────────
    @staticmethod
    async def set_enabled(db: AsyncSession, scenario: AIScenario, enabled: bool) -> AIScenario:
        if enabled and not scenario.licensed:
            raise ScenarioNotOperable(scenario.slug, "not licensed")
        if enabled and not scenario.registered:
            raise ScenarioNotOperable(scenario.slug, "plugin not installed")
        scenario.enabled = enabled
        await db.commit()
        await db.refresh(scenario)
        return scenario

    @staticmethod
    async def assert_can_add_camera(db: AsyncSession, scenario: AIScenario) -> None:
        """Raise if enabling another camera would breach the license cap."""
        if not (scenario.licensed and scenario.enabled):
            raise ScenarioNotOperable(scenario.slug, "not licensed/enabled")
        if scenario.camera_limit and scenario.camera_limit > 0:
            count = await AIService.active_camera_count(db, scenario.id)
            if count >= scenario.camera_limit:
                raise CameraCapExceeded(scenario.slug, scenario.camera_limit)


ai_service = AIService()
