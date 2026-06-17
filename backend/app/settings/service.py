# =============================================================================
# Settings Service
# =============================================================================

import json
import logging
from typing import Optional, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.settings.models import Settings, DEFAULT_SETTINGS

logger = logging.getLogger(__name__)


class SettingsService:

    @staticmethod
    async def seed_defaults(db: AsyncSession):
        """Create default settings if they don't exist."""
        for key, meta in DEFAULT_SETTINGS.items():
            existing = await db.execute(select(Settings).where(Settings.key == key))
            if existing.scalar_one_or_none() is None:
                db.add(Settings(
                    key=key,
                    value=meta["value"],
                    value_type=meta["type"],
                    category=meta["category"],
                    description=meta["desc"],
                    is_sensitive=meta.get("sensitive", False),
                ))
        await db.commit()
        logger.info("Default settings seeded")

    @staticmethod
    async def get_all(db: AsyncSession, category: Optional[str] = None) -> List[Settings]:
        q = select(Settings)
        if category:
            q = q.where(Settings.category == category)
        q = q.order_by(Settings.category, Settings.key)
        result = await db.execute(q)
        return list(result.scalars().all())

    @staticmethod
    async def get(db: AsyncSession, key: str) -> Optional[Settings]:
        result = await db.execute(select(Settings).where(Settings.key == key))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_value(db: AsyncSession, key: str, default: str = "") -> str:
        setting = await SettingsService.get(db, key)
        if setting:
            return setting.value or default
        return default

    @staticmethod
    async def get_int(db: AsyncSession, key: str, default: int = 0) -> int:
        v = await SettingsService.get_value(db, key, str(default))
        try:
            return int(v)
        except ValueError:
            return default

    @staticmethod
    async def get_bool(db: AsyncSession, key: str, default: bool = False) -> bool:
        v = await SettingsService.get_value(db, key, str(default).lower())
        return v.lower() in ("true", "1", "yes")

    @staticmethod
    async def set_value(db: AsyncSession, key: str, value: str,
                        category: str = None, is_sensitive: bool = False) -> Settings:
        meta = DEFAULT_SETTINGS.get(key)
        if meta:
            category = category or meta["category"]
            is_sensitive = is_sensitive or meta.get("sensitive", False)
        setting = await SettingsService.get(db, key)
        if setting:
            setting.value = value
            if category is not None:
                setting.category = category
            if is_sensitive:
                setting.is_sensitive = True
        else:
            setting = Settings(
                key=key,
                value=value,
                value_type=meta["type"] if meta else "string",
                category=category or "general",
                description=meta["desc"] if meta else None,
                is_sensitive=is_sensitive,
            )
            db.add(setting)
        await db.commit()
        await db.refresh(setting)
        return setting

    @staticmethod
    async def bulk_update(db: AsyncSession, values: Dict[str, str]):
        for key, value in values.items():
            meta = DEFAULT_SETTINGS.get(key)
            setting = await SettingsService.get(db, key)
            if setting:
                setting.value = value
                if meta:
                    setting.value_type = meta["type"]
                    setting.category = meta["category"]
                    setting.description = meta["desc"]
                    setting.is_sensitive = meta.get("sensitive", setting.is_sensitive)
            else:
                db.add(Settings(
                    key=key,
                    value=value,
                    value_type=meta["type"] if meta else "string",
                    category=meta["category"] if meta else "general",
                    description=meta["desc"] if meta else None,
                    is_sensitive=meta.get("sensitive", False) if meta else False,
                ))
        await db.commit()

    @staticmethod
    async def get_max_cameras(db: AsyncSession) -> int:
        return await SettingsService.get_int(db, "max_cameras", 16)

    @staticmethod
    async def get_retention_config(db: AsyncSession) -> dict:
        return {
            "enabled": await SettingsService.get_bool(db, "retention_enabled", True),
            "days": await SettingsService.get_int(db, "retention_days", 30),
            "max_storage_gb": await SettingsService.get_int(db, "retention_max_storage_gb", 0),
            "check_interval_min": await SettingsService.get_int(db, "retention_check_interval_min", 60),
        }

    @staticmethod
    async def get_recording_config(db: AsyncSession) -> dict:
        return {
            "segment_duration": await SettingsService.get_int(db, "default_segment_duration", 900),
            "default_fps": await SettingsService.get_int(db, "default_recording_fps", 0),
            "format": await SettingsService.get_value(db, "recording_format", "mp4"),
            "ffmpeg_recovery": await SettingsService.get_bool(db, "ffmpeg_recovery_enabled", True),
            "health_check_interval": await SettingsService.get_int(db, "ffmpeg_health_check_interval", 30),
        }
