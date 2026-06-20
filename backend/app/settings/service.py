# =============================================================================
# Settings Service
# =============================================================================

import json
import logging
from typing import Optional, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.settings.models import Settings, DEFAULT_SETTINGS
from app.core.crypto import encrypt_value, decrypt_value, is_encrypted

logger = logging.getLogger(__name__)


# Keys whose stored value must be encrypted at rest (Fernet, machine-bound).
# Derived from DEFAULT_SETTINGS entries flagged "sensitive". Secrets like the
# SMTP password and Twilio auth token are encrypted on write and transparently
# decrypted on read so callers stay unchanged.
SENSITIVE_KEYS = frozenset(
    k for k, meta in DEFAULT_SETTINGS.items() if meta.get("sensitive")
)


# Mask the API returns for sensitive values. An incoming write equal to this
# sentinel means "unchanged" — the UI rendered the mask and the operator did not
# retype the secret, so the stored ciphertext must be preserved as-is.
SENSITIVE_MASK = "********"

# Keys that the list endpoint masks but that are NOT Fernet-encrypted secrets
# (so they don't live in SENSITIVE_KEYS). A bulk write echoing such a mask back
# must be ignored, or the stored value would be overwritten with the mask. The
# license_key list mask is "xxxx****xxxx"; guard any value containing "****".
_PARTIAL_MASKED_KEYS = frozenset({"license_key"})


def _is_sensitive_key(key: str) -> bool:
    return key in SENSITIVE_KEYS


def _is_masked_write(key: str, value: Optional[str]) -> bool:
    """True if `value` is a UI mask that must not overwrite the stored value."""
    if not value:
        return False
    if _is_sensitive_key(key) and value == SENSITIVE_MASK:
        return True
    if key in _PARTIAL_MASKED_KEYS and "****" in value:
        return True
    return False


def _encrypt_if_sensitive(key: str, value: Optional[str]) -> Optional[str]:
    """Encrypt the value when the key is sensitive. Idempotent and safe on
    empty/None values (passed through by encrypt_value)."""
    if value and _is_sensitive_key(key):
        return encrypt_value(value)
    return value


def _decrypt_if_sensitive(key: str, value: Optional[str]) -> Optional[str]:
    """Decrypt a sensitive value for return to callers. Legacy plaintext rows
    (no 'enc:' prefix) are returned as-is; a corrupt/undecryptable ciphertext
    is logged and returned as-is rather than raising, so reads never 500."""
    if not value or not _is_sensitive_key(key):
        return value
    if not is_encrypted(value):
        return value  # legacy plaintext — returned until next write re-encrypts
    try:
        return decrypt_value(value)
    except Exception as e:
        logger.error(f"Failed to decrypt sensitive setting '{key}': {e}")
        return value


class SettingsService:

    # Expose decrypt helper so routers can return cleartext-equivalent values
    # without reimplementing the sensitive-key logic.
    @staticmethod
    def decrypt_for_display(key: str, value: Optional[str]) -> Optional[str]:
        return _decrypt_if_sensitive(key, value)

    @staticmethod
    async def seed_defaults(db: AsyncSession):
        """Create default settings if they don't exist."""
        for key, meta in DEFAULT_SETTINGS.items():
            existing = await db.execute(select(Settings).where(Settings.key == key))
            if existing.scalar_one_or_none() is None:
                db.add(Settings(
                    key=key,
                    value=_encrypt_if_sensitive(key, meta["value"]),
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
            return _decrypt_if_sensitive(key, setting.value) or default
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
        # Unchanged-secret guard: a write equal to the UI mask (full "********"
        # for encrypted secrets, or "xxxx****xxxx" for license_key) means the
        # operator left the masked field untouched — keep the existing value.
        if _is_masked_write(key, value) and setting:
            return setting
        stored_value = _encrypt_if_sensitive(key, value)
        if setting:
            setting.value = stored_value
            if category is not None:
                setting.category = category
            if is_sensitive:
                setting.is_sensitive = True
        else:
            setting = Settings(
                key=key,
                value=stored_value,
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
            # Unchanged-secret guard (see set_value): skip masked writes so a
            # re-saved mask never overwrites the real secret or license key.
            if _is_masked_write(key, value) and setting:
                continue
            stored_value = _encrypt_if_sensitive(key, value)
            if setting:
                setting.value = stored_value
                if meta:
                    setting.value_type = meta["type"]
                    setting.category = meta["category"]
                    setting.description = meta["desc"]
                    setting.is_sensitive = meta.get("sensitive", setting.is_sensitive)
            else:
                db.add(Settings(
                    key=key,
                    value=stored_value,
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
