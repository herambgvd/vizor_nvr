# =============================================================================
# Settings Router
# =============================================================================

from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.settings.models import (
    SettingResponse, SettingUpdate, BulkSettingsUpdate,
    RetentionConfig, RecordingConfig,
)
from app.settings.service import SettingsService
from app.core.dependencies import get_current_user, get_admin_user, require_license_feature
from app.core.audit_logger import write_audit, client_ip

router = APIRouter(prefix="/settings", tags=["Settings"])
svc = SettingsService()


@router.get("/public/branding")
async def public_branding(db: AsyncSession = Depends(get_db)):
    """Public whitelabel metadata used by login and the app shell."""
    theme_mode = await svc.get_value(db, "theme_mode", "dark")
    font_size_raw = await svc.get_value(db, "theme_font_size", "14")
    try:
        font_size = min(18, max(12, int(font_size_raw)))
    except (TypeError, ValueError):
        font_size = 14
    light = theme_mode == "light"
    # Operator display timezone — exposed app-wide so every screen renders times
    # in the configured zone (falls back to the legacy key, then UTC).
    tz = await svc.get_value(db, "system_timezone", "") or await svc.get_value(db, "timezone", "UTC")
    return {
        "system_name": await svc.get_value(db, "system_name", "Vizor NVR"),
        "timezone": tz or "UTC",
        "logo_url": await svc.get_value(db, "brand_logo_url", ""),
        "favicon_url": await svc.get_value(db, "brand_favicon_url", ""),
        "theme_mode": "light" if light else "dark",
        # Fixed enterprise palette. Keep these keys for frontend/backward
        # compatibility, but do not read old custom color settings here.
        "background_color": "#FFFFFF" if light else "#000000",
        "button_color": "#111827" if light else "#FFFFFF",
        "text_color": "#111827" if light else "#F9FAFB",
        "hover_color": "#F3F4F6" if light else "#111111",
        "font_size": str(font_size),
    }


@router.get("", response_model=List[SettingResponse])
async def list_settings(
    category: Optional[str] = Query(None),
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    items = await svc.get_all(db, category)
    # Mask sensitive values
    result = []
    for s in items:
        val = s.value
        if s.is_sensitive and val:
            # Encrypted-at-rest secrets (SMTP password, Twilio token, ...) must
            # never leave the API as ciphertext or cleartext — show a fixed mask.
            val = "********"
        elif s.key in ("license_key",) and val:
            val = val[:4] + "****" + val[-4:] if len(val) > 8 else "****"
        result.append(SettingResponse(
            key=s.key, value=val, value_type=s.value_type,
            category=s.category, description=s.description,
            is_sensitive=s.is_sensitive, updated_at=s.updated_at,
        ))
    return result


@router.get("/{key}", response_model=SettingResponse)
async def get_setting(
    key: str,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    setting = await svc.get(db, key)
    if not setting:
        raise HTTPException(404)
    val = setting.value
    if setting.is_sensitive and val:
        val = "********"  # never expose the encrypted-at-rest secret
    return SettingResponse(
        key=setting.key, value=val, value_type=setting.value_type,
        category=setting.category, description=setting.description,
        is_sensitive=setting.is_sensitive, updated_at=setting.updated_at,
    )


@router.put("/{key}", response_model=SettingResponse)
async def update_setting(
    key: str,
    body: SettingUpdate,
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    setting = await svc.set_value(db, key, body.value)
    # Do not record sensitive secret values into the audit log.
    audit_value = "********" if setting.is_sensitive else body.value
    await write_audit(
        db, action="setting_update", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="setting",
        description=f"Setting '{key}' updated",
        details={"key": key, "value": audit_value},
    )
    await db.commit()
    val = setting.value
    if setting.is_sensitive and val:
        val = "********"  # never echo the encrypted-at-rest secret back
    return SettingResponse(
        key=setting.key, value=val, value_type=setting.value_type,
        category=setting.category, description=setting.description,
        is_sensitive=setting.is_sensitive, updated_at=setting.updated_at,
    )


@router.put("", status_code=204)
async def bulk_update_settings(
    body: BulkSettingsUpdate,
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    await svc.bulk_update(db, body.settings)
    await write_audit(
        db, action="setting_bulk_update", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="setting",
        details={"keys": list(body.settings.keys())},
    )
    await db.commit()


# ── Backup / Restore ─────────────────────────────────────────────

@router.get("/backup")
async def backup_config(
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Export full NVR configuration as JSON.
    Sensitive values (passwords) are omitted for security.
    """
    from datetime import datetime, timezone
    import json
    from sqlalchemy import select
    from app.cameras.models import Camera, CameraGroup
    from app.storage.models import StoragePool, StorageTierRule
    from app.notifications.models import Webhook

    # Settings (mask passwords)
    all_settings = await svc.get_all(db)
    MASKED_KEYS = {"smtp_password", "license_key"}
    settings_export = {
        s.key: ("" if s.key in MASKED_KEYS else s.value)
        for s in all_settings
    }

    # Cameras (strip sensitive auth from URLs is NOT done since they're needed for restore)
    cameras_result = await db.execute(select(Camera))
    cameras_export = []
    for cam in cameras_result.scalars().all():
        cameras_export.append({
            "id": cam.id,
            "name": cam.name,
            "main_stream_url": cam.main_stream_url,
            "sub_stream_url": cam.sub_stream_url,
            "detect_stream_url": cam.detect_stream_url,
            "onvif_host": cam.onvif_host,
            "onvif_port": cam.onvif_port,
            "onvif_username": cam.onvif_username,
            "location": cam.location,
            "description": cam.description,
            "recording_fps": cam.recording_fps,
            "recording_schedule": cam.recording_schedule,
            "bandwidth_limit_kbps": cam.bandwidth_limit_kbps,
            "is_enabled": cam.is_enabled,
            "storage_pool_id": cam.storage_pool_id,
        })

    # Storage pools
    pools_result = await db.execute(select(StoragePool))
    pools_export = []
    for pool in pools_result.scalars().all():
        pools_export.append({
            "id": pool.id,
            "name": pool.name,
            "path": pool.path,
            "max_size_bytes": pool.max_size_bytes,
            "priority": pool.priority,
        })

    # Webhook configs (mask secrets)
    webhooks_result = await db.execute(select(Webhook))
    webhooks_export = []
    for wh in webhooks_result.scalars().all():
        webhooks_export.append({
            "id": wh.id,
            "name": wh.name,
            "url": wh.url,
            "events": wh.events,
            "is_enabled": wh.is_enabled,
        })

    payload = {
        "backup_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "settings": settings_export,
        "cameras": cameras_export,
        "storage_pools": pools_export,
        "webhooks": webhooks_export,
    }

    await write_audit(
        db, action="config_backup", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="system",
        description="Configuration backup exported",
    )
    await db.commit()

    from fastapi.responses import JSONResponse
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f"attachment; filename=nvr_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"},
    )


class RestoreRequest(BaseModel):
    backup: dict
    restore_settings: bool = True
    restore_cameras: bool = False    # Off by default — may overwrite live cameras
    restore_webhooks: bool = True
    restore_storage_pools: bool = False  # Off by default — paths may differ on new machine


@router.post("/restore", status_code=200)
async def restore_config(
    body: RestoreRequest,
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Import configuration from a backup JSON.
    By default only restores settings and webhooks.
    Set restore_cameras=true / restore_storage_pools=true explicitly.
    """
    from pydantic import ValidationError

    backup = body.backup
    if backup.get("backup_version") not in ("1.0",):
        raise HTTPException(400, "Unsupported backup version")

    restored: dict[str, int] = {}

    if body.restore_settings and "settings" in backup:
        settings_dict = {k: v for k, v in backup["settings"].items() if v != ""}
        await svc.bulk_update(db, settings_dict)
        restored["settings"] = len(settings_dict)

    if body.restore_webhooks and "webhooks" in backup:
        from app.notifications.models import Webhook
        from sqlalchemy import select
        count = 0
        for wh_data in backup["webhooks"]:
            existing = await db.execute(
                select(Webhook).where(Webhook.id == wh_data["id"])
            )
            wh = existing.scalar_one_or_none()
            if not wh:
                db.add(Webhook(
                    id=wh_data["id"],
                    name=wh_data["name"],
                    url=wh_data["url"],
                    events=wh_data.get("events", []),
                    is_enabled=wh_data.get("is_enabled", True),
                ))
                count += 1
        restored["webhooks"] = count

    if body.restore_storage_pools and "storage_pools" in backup:
        from app.storage.models import StoragePool
        from sqlalchemy import select
        import os
        count = 0
        for sp_data in backup["storage_pools"]:
            if not os.path.isdir(sp_data["path"]):
                continue  # Skip pools whose paths don't exist on this machine
            existing = await db.execute(
                select(StoragePool).where(StoragePool.id == sp_data["id"])
            )
            sp = existing.scalar_one_or_none()
            if not sp:
                db.add(StoragePool(
                    id=sp_data["id"],
                    name=sp_data["name"],
                    path=sp_data["path"],
                    max_size_bytes=sp_data.get("max_size_bytes"),
                    priority=sp_data.get("priority", 0),
                ))
                count += 1
        restored["storage_pools"] = count

    if body.restore_cameras and "cameras" in backup:
        from app.cameras.models import Camera
        from sqlalchemy import select
        count = 0
        for cam_data in backup["cameras"]:
            existing = await db.execute(
                select(Camera).where(Camera.id == cam_data["id"])
            )
            cam = existing.scalar_one_or_none()
            if not cam:
                db.add(Camera(
                    id=cam_data["id"],
                    name=cam_data["name"],
                    main_stream_url=cam_data["main_stream_url"],
                    sub_stream_url=cam_data.get("sub_stream_url"),
                    detect_stream_url=cam_data.get("detect_stream_url"),
                    onvif_host=cam_data.get("onvif_host"),
                    onvif_port=cam_data.get("onvif_port", 80),
                    onvif_username=cam_data.get("onvif_username"),
                    location=cam_data.get("location"),
                    description=cam_data.get("description"),
                    recording_fps=cam_data.get("recording_fps"),
                    recording_schedule=cam_data.get("recording_schedule"),
                    bandwidth_limit_kbps=cam_data.get("bandwidth_limit_kbps", 0),
                    is_enabled=cam_data.get("is_enabled", True),
                    storage_pool_id=cam_data.get("storage_pool_id"),
                ))
                count += 1
        restored["cameras"] = count

    await write_audit(
        db, action="config_restore", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="system",
        description="Configuration restored from backup",
        details={"restored": restored},
    )
    await db.commit()
    return {"message": "Restore complete", "restored": restored}


# ── Convenience endpoints ────────────────────────────────────────

@router.get("/config/retention", response_model=RetentionConfig)
async def get_retention_config(
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.get_retention_config(db)


@router.put("/config/retention", response_model=RetentionConfig)
async def update_retention_config(
    body: RetentionConfig,
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    await svc.bulk_update(db, {
        "retention_enabled": str(body.enabled).lower(),
        "retention_days": str(body.days),
        "retention_max_storage_gb": str(body.max_storage_gb),
        "retention_check_interval_min": str(body.check_interval_min),
    })
    await write_audit(
        db, action="retention_config_update", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="setting",
    )
    await db.commit()
    return body


@router.get("/config/recording", response_model=RecordingConfig)
async def get_recording_config(
    _licensed: bool = Depends(require_license_feature("recording")),
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.get_recording_config(db)


# ─────────────────────────────────────────────────────────────────────────────
# TLS / HTTPS management
# ─────────────────────────────────────────────────────────────────────────────

from app.settings import tls_service as _tls


class TLSGenerateRequest(BaseModel):
    common_name: str = "gvd-nvr.local"
    days_valid: int = 365


class TLSUploadRequest(BaseModel):
    cert_pem: str
    key_pem: str


@router.get("/tls/status")
async def tls_status(user: dict = Depends(get_admin_user)):
    """Return the current cert's CN, issuer, expiry, fingerprint."""
    return _tls.status().to_dict()


@router.post("/tls/generate-self-signed")
async def tls_generate_self_signed(
    body: TLSGenerateRequest,
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate (or replace) the self-signed cert. Overwrites any existing
    cert at CERT_PATH. After this, restart nginx to pick up the new files."""
    st = _tls.generate_self_signed(body.common_name, body.days_valid)
    await write_audit(
        db, action="tls_generate_self_signed",
        user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="tls",
        description=f"Self-signed cert generated (CN={body.common_name}, {body.days_valid}d)",
    )
    await db.commit()
    return st.to_dict()


@router.post("/tls/upload")
async def tls_upload(
    body: TLSUploadRequest,
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Install an operator-supplied PEM cert + key. Validates the key matches
    the cert before persisting. Reload nginx after install."""
    try:
        st = _tls.install_custom(body.cert_pem.encode(), body.key_pem.encode())
    except ValueError as e:
        raise HTTPException(400, str(e))
    await write_audit(
        db, action="tls_upload",
        user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="tls",
        description=f"Custom TLS cert installed (CN={st.common_name})",
    )
    await db.commit()
    return st.to_dict()


@router.put("/config/recording", response_model=RecordingConfig)
async def update_recording_config(
    body: RecordingConfig,
    request: Request,
    _licensed: bool = Depends(require_license_feature("recording")),
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    await svc.bulk_update(db, {
        "default_segment_duration": str(body.segment_duration),
        "default_recording_fps": str(body.default_fps),
        "recording_format": body.format,
        "ffmpeg_recovery_enabled": str(body.ffmpeg_recovery).lower(),
        "ffmpeg_health_check_interval": str(body.health_check_interval),
    })
    await write_audit(
        db, action="recording_config_update", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="setting",
    )
    await db.commit()
    return body
