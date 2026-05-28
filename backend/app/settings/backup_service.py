# =============================================================================
# Config Backup / Restore Service
# =============================================================================
#
# Exports all NVR configuration (cameras, users, settings, rules)
# to an encrypted JSON archive. Does NOT include video recordings.
# =============================================================================

import json
import logging
import os
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

from app.database import async_session_maker
from app.config import settings

logger = logging.getLogger(__name__)


class BackupService:
    """
    Backup and restore NVR configuration.
    """

    BACKUP_VERSION = "2.0"

    async def create_backup(self, password: str) -> str:
        """
        Create an encrypted backup archive.
        Returns the path to the backup file.
        """
        backup_data = await self._export_config()

        # Generate encryption key from password
        salt = os.urandom(16)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=600000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        fernet = Fernet(key)

        # Encrypt JSON
        json_bytes = json.dumps(backup_data, indent=2, default=str).encode("utf-8")
        encrypted = fernet.encrypt(json_bytes)

        # Write to ZIP with metadata
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(settings.EXPORT_PATH, f"gvd_nvr_backup_{ts}.zip")
        os.makedirs(settings.EXPORT_PATH, exist_ok=True)

        with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("backup.json.enc", encrypted)
            zf.writestr("metadata.json", json.dumps({
                "version": self.BACKUP_VERSION,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "salt": base64.b64encode(salt).decode(),
            }))

        logger.info(f"Backup created: {backup_path}")
        return backup_path

    async def restore_backup(self, backup_path: str, password: str) -> bool:
        """
        Restore configuration from an encrypted backup archive.
        WARNING: Overwrites existing configuration!
        """
        with zipfile.ZipFile(backup_path, "r") as zf:
            metadata = json.loads(zf.read("metadata.json").decode())
            salt = base64.b64decode(metadata["salt"])
            encrypted = zf.read("backup.json.enc")

        # Derive key
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=600000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        fernet = Fernet(key)

        try:
            decrypted = fernet.decrypt(encrypted)
            backup_data = json.loads(decrypted.decode("utf-8"))
        except Exception as e:
            logger.error(f"Backup decryption failed (wrong password?): {e}")
            return False

        await self._import_config(backup_data)
        logger.info(f"Backup restored from: {backup_path}")
        return True

    async def _export_config(self) -> Dict[str, Any]:
        """Export all configuration tables."""
        data = {
            "version": self.BACKUP_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "cameras": [],
            "camera_groups": [],
            "users": [],
            "roles": [],
            "settings": [],
            "linkage_rules": [],
            "storage_pools": [],
            "cloud_configs": [],
            "webhooks": [],
        }

        async with async_session_maker() as db:
            from sqlalchemy import select
            from app.cameras.models import Camera, CameraGroup
            from app.auth.models import User, Role
            from app.settings.models import Settings
            from app.events.models import EventLinkageRule
            from app.storage.models import StoragePool, CloudStorageConfig
            from app.notifications.models import WebhookConfig

            # Cameras (decrypt ONVIF creds for portability)
            from app.core.crypto import decrypt_value
            cameras = (await db.execute(select(Camera))).scalars().all()
            for cam in cameras:
                c = cam.__dict__.copy()
                c.pop("_sa_instance_state", None)
                if c.get("onvif_password"):
                    c["onvif_password"] = decrypt_value(c["onvif_password"]) or ""
                if c.get("onvif_username"):
                    c["onvif_username"] = decrypt_value(c["onvif_username"]) or ""
                data["cameras"].append(c)

            # Groups
            groups = (await db.execute(select(CameraGroup))).scalars().all()
            for g in groups:
                d = g.__dict__.copy()
                d.pop("_sa_instance_state", None)
                data["camera_groups"].append(d)

            # Users (keep hashed passwords — they're portable)
            users = (await db.execute(select(User))).scalars().all()
            for u in users:
                d = u.__dict__.copy()
                d.pop("_sa_instance_state", None)
                # Don't export TOTP secrets in plaintext backup
                d.pop("totp_secret", None)
                d.pop("totp_recovery_codes", None)
                data["users"].append(d)

            # Roles
            roles = (await db.execute(select(Role))).scalars().all()
            for r in roles:
                d = r.__dict__.copy()
                d.pop("_sa_instance_state", None)
                data["roles"].append(d)

            # Settings
            settings_list = (await db.execute(select(Settings))).scalars().all()
            for s in settings_list:
                d = s.__dict__.copy()
                d.pop("_sa_instance_state", None)
                data["settings"].append(d)

            # Linkage rules
            rules = (await db.execute(select(EventLinkageRule))).scalars().all()
            for r in rules:
                d = r.__dict__.copy()
                d.pop("_sa_instance_state", None)
                data["linkage_rules"].append(d)

            # Storage
            pools = (await db.execute(select(StoragePool))).scalars().all()
            for p in pools:
                d = p.__dict__.copy()
                d.pop("_sa_instance_state", None)
                data["storage_pools"].append(d)

            clouds = (await db.execute(select(CloudStorageConfig))).scalars().all()
            for c in clouds:
                d = c.__dict__.copy()
                d.pop("_sa_instance_state", None)
                data["cloud_configs"].append(d)

            # Webhooks
            hooks = (await db.execute(select(WebhookConfig))).scalars().all()
            for h in hooks:
                d = h.__dict__.copy()
                d.pop("_sa_instance_state", None)
                data["webhooks"].append(d)

        return data

    async def _import_config(self, data: Dict[str, Any]):
        """Import configuration, overwriting existing data."""
        async with async_session_maker() as db:
            from sqlalchemy import select, delete
            from app.cameras.models import Camera, CameraGroup, camera_group_members
            from app.auth.models import User, Role
            from app.settings.models import Settings
            from app.events.models import EventLinkageRule
            from app.storage.models import StoragePool, CloudStorageConfig
            from app.notifications.models import WebhookConfig

            # Truncate tables (careful order to avoid FK violations).
            # Do NOT delete Camera until after recordings are preserved.
            # Instead, we use ON DELETE SET NULL on recordings.camera_id
            # or we preserve recordings by updating camera_id to NULL first.
            await db.execute(delete(camera_group_members))
            await db.execute(delete(WebhookConfig))
            await db.execute(delete(CloudStorageConfig))
            await db.execute(delete(EventLinkageRule))
            await db.execute(delete(Settings))
            # Preserve recordings by nulling camera_id before camera deletion
            from app.recordings.models import Recording
            await db.execute(
                Recording.__table__.update().where(Recording.camera_id.isnot(None))
                .values(camera_id=None)
            )
            await db.execute(delete(CameraGroup))
            await db.execute(delete(Camera))
            await db.execute(delete(StoragePool))
            await db.execute(delete(User))
            await db.execute(delete(Role))

            # Insert roles first (users depend on them)
            for r in data.get("roles", []):
                db.add(Role(**{k: v for k, v in r.items() if k != "id" or v}))

            # Users
            for u in data.get("users", []):
                db.add(User(**{k: v for k, v in u.items() if k != "id" or v}))

            # Settings
            for s in data.get("settings", []):
                db.add(Settings(**{k: v for k, v in s.items() if k != "id" or v}))

            # Storage pools
            for p in data.get("storage_pools", []):
                db.add(StoragePool(**{k: v for k, v in p.items() if k != "id" or v}))

            # Cloud configs
            for c in data.get("cloud_configs", []):
                db.add(CloudStorageConfig(**{k: v for k, v in c.items() if k != "id" or v}))

            # Camera groups
            for g in data.get("camera_groups", []):
                db.add(CameraGroup(**{k: v for k, v in g.items() if k != "id" or v}))

            # Cameras (re-encrypt ONVIF creds)
            from app.core.crypto import encrypt_value
            for c in data.get("cameras", []):
                if c.get("onvif_password"):
                    c["onvif_password"] = encrypt_value(c["onvif_password"])
                if c.get("onvif_username"):
                    c["onvif_username"] = encrypt_value(c["onvif_username"])
                db.add(Camera(**{k: v for k, v in c.items() if k != "id" or v}))

            # Linkage rules
            for r in data.get("linkage_rules", []):
                db.add(EventLinkageRule(**{k: v for k, v in r.items() if k != "id" or v}))

            # Webhooks
            for h in data.get("webhooks", []):
                db.add(WebhookConfig(**{k: v for k, v in h.items() if k != "id" or v}))

            await db.commit()


# Module singleton
backup_service = BackupService()
