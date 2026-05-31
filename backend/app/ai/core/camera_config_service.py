# =============================================================================
# CameraConfigService — per-(camera, scenario) enablement (F3).
#
# CRUD over camera_ai_configs with license-cap enforcement. Assigning a camera
# to a scenario goes through ai_service.assert_can_add_camera (operable +
# camera-cap check) before insert. Uniqueness is (camera, scenario). The bridge
# updates stream bookkeeping via set_stream_state().
# =============================================================================
from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import CameraAIConfig, CameraAIConfigCreate, CameraAIConfigUpdate
from app.ai.core.service import ai_service, ScenarioNotOperable
from app.cameras.models import Camera

logger = logging.getLogger(__name__)


class CameraConfigConflict(Exception):
    """Camera is already assigned to the scenario."""

    def __init__(self, camera_id: str, scenario_id: str):
        super().__init__(f"camera {camera_id} already assigned to scenario {scenario_id}")
        self.camera_id = camera_id
        self.scenario_id = scenario_id


class CameraConfigService:
    # ── Queries ─────────────────────────────────────────────────────────
    @staticmethod
    async def list_for_scenario(db: AsyncSession, scenario_id: str) -> List[CameraAIConfig]:
        rows = (await db.execute(
            select(CameraAIConfig)
            .where(CameraAIConfig.scenario_id == scenario_id)
            .order_by(CameraAIConfig.created_at)
        )).scalars().all()
        return list(rows)

    @staticmethod
    async def list_for_camera(db: AsyncSession, camera_id: str) -> List[CameraAIConfig]:
        rows = (await db.execute(
            select(CameraAIConfig)
            .where(CameraAIConfig.camera_id == camera_id)
            .order_by(CameraAIConfig.created_at)
        )).scalars().all()
        return list(rows)

    @staticmethod
    async def get(db: AsyncSession, config_id: str) -> Optional[CameraAIConfig]:
        return (await db.execute(
            select(CameraAIConfig).where(CameraAIConfig.id == config_id)
        )).scalar_one_or_none()

    @staticmethod
    async def _get_existing(
        db: AsyncSession, camera_id: str, scenario_id: str
    ) -> Optional[CameraAIConfig]:
        return (await db.execute(
            select(CameraAIConfig).where(
                CameraAIConfig.camera_id == camera_id,
                CameraAIConfig.scenario_id == scenario_id,
            )
        )).scalar_one_or_none()

    @staticmethod
    async def get_camera_name(db: AsyncSession, camera_id: str) -> Optional[str]:
        return (await db.execute(
            select(Camera.name).where(Camera.id == camera_id)
        )).scalar_one_or_none()

    # ── Mutations ───────────────────────────────────────────────────────
    @staticmethod
    async def create(db: AsyncSession, payload: CameraAIConfigCreate) -> CameraAIConfig:
        """Assign a camera to a scenario.

        Enforces: scenario exists + operable, camera exists, license camera-cap,
        and (camera, scenario) uniqueness — all before insert.
        """
        scenario = await ai_service.get_scenario(db, payload.scenario_id)
        if scenario is None:
            raise ScenarioNotOperable(payload.scenario_id, "scenario not found")

        camera = (await db.execute(
            select(Camera).where(Camera.id == payload.camera_id)
        )).scalar_one_or_none()
        if camera is None:
            raise ValueError(f"camera {payload.camera_id} not found")

        existing = await CameraConfigService._get_existing(
            db, payload.camera_id, payload.scenario_id
        )
        if existing is not None:
            raise CameraConfigConflict(payload.camera_id, payload.scenario_id)

        # Cap enforcement — only counts against the limit when enabling.
        if payload.enabled:
            await ai_service.assert_can_add_camera(db, scenario)

        config = CameraAIConfig(
            camera_id=payload.camera_id,
            scenario_id=payload.scenario_id,
            enabled=payload.enabled,
            config=payload.config,
            stream_state="stopped",
        )
        db.add(config)
        await db.commit()
        await db.refresh(config)
        logger.info(
            "[ai] camera %s assigned to scenario %s (enabled=%s)",
            payload.camera_id, scenario.slug, payload.enabled,
        )
        return config

    @staticmethod
    async def update(
        db: AsyncSession, config_id: str, payload: CameraAIConfigUpdate
    ) -> Optional[CameraAIConfig]:
        config = await CameraConfigService.get(db, config_id)
        if config is None:
            return None

        # Re-check the cap when flipping disabled → enabled.
        if payload.enabled is True and not config.enabled:
            scenario = await ai_service.get_scenario(db, config.scenario_id)
            if scenario is None:
                raise ScenarioNotOperable(config.scenario_id, "scenario not found")
            await ai_service.assert_can_add_camera(db, scenario)

        if payload.enabled is not None:
            config.enabled = payload.enabled
        if payload.config is not None:
            config.config = payload.config

        await db.commit()
        await db.refresh(config)
        return config

    @staticmethod
    async def delete(db: AsyncSession, config_id: str) -> bool:
        config = await CameraConfigService.get(db, config_id)
        if config is None:
            return False
        await db.delete(config)
        await db.commit()
        logger.info("[ai] camera config %s unassigned", config_id)
        return True

    @staticmethod
    async def set_stream_state(
        db: AsyncSession,
        config_id: str,
        state: str,
        error: Optional[str] = None,
    ) -> Optional[CameraAIConfig]:
        """Bridge bookkeeping: record the reconciled stream state for a config."""
        config = await CameraConfigService.get(db, config_id)
        if config is None:
            return None
        config.stream_state = state
        config.last_error = error
        config.last_synced_at = datetime.utcnow()
        await db.commit()
        await db.refresh(config)
        return config


camera_config_service = CameraConfigService()
