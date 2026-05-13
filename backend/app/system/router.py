# =============================================================================
# System Router — licensing, NTP, DDNS, version/update endpoints
# =============================================================================

import logging
import os
import shutil
import subprocess
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.database import get_db
from app.core.dependencies import get_admin_user, get_current_user
from app.core.audit_logger import write_audit, client_ip

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/system", tags=["System"])


# ─── Version + uptime ─────────────────────────────────────────────────────────

import time as _t
_BOOT_TIME = _t.time()


@router.get("/info")
async def system_info(user: dict = Depends(get_current_user)):
    """Version, uptime, host platform hints."""
    import platform, psutil  # type: ignore
    return {
        "version": __version__,
        "uptime_seconds": int(_t.time() - _BOOT_TIME),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": psutil.cpu_count() if hasattr(psutil, "cpu_count") else None,
        "memory_total_bytes": psutil.virtual_memory().total if hasattr(psutil, "virtual_memory") else None,
    }


# ─── License (Phase 7.1) ──────────────────────────────────────────────────────

@router.get("/license/status")
async def license_status(user: dict = Depends(get_admin_user)):
    from app.core.licensing import status as _ls
    return _ls().to_dict()


@router.post("/license/upload")
async def license_upload(
    file: UploadFile = File(...),
    request: Request = None,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Persist a vendor-signed license.json bundle. The next request to
    /license/status will re-evaluate it."""
    from app.core.licensing import _license_path
    body = await file.read()
    if len(body) > 64_000:
        raise HTTPException(400, "License file too large")
    lp = _license_path()
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_bytes(body)
    os.chmod(lp, 0o600)
    await write_audit(
        db, action="license_upload",
        user_id=user["id"], username=user["username"],
        ip_address=client_ip(request) if request else None,
        resource_type="license",
        description=f"License file uploaded ({len(body)} bytes)",
    )
    await db.commit()
    from app.core.licensing import status as _ls
    return _ls().to_dict()


# ─── NTP (Phase 7.6) ──────────────────────────────────────────────────────────

class NTPConfigBody(BaseModel):
    server: str


@router.get("/ntp/status")
async def ntp_status(user: dict = Depends(get_admin_user)):
    """Best-effort NTP status. Uses `timedatectl status` on Linux; falls back
    to reporting the configured server only."""
    from app.settings.service import SettingsService
    from app.database import async_session_maker
    async with async_session_maker() as db:
        server = await SettingsService.get_value(db, "ntp_server", "pool.ntp.org")
    out = {"server": server, "synchronized": None, "last_sync": None}
    if shutil.which("timedatectl"):
        try:
            res = subprocess.run(
                ["timedatectl", "show", "--property=NTPSynchronized,TimeUSec"],
                capture_output=True, timeout=5, text=True,
            )
            for line in res.stdout.splitlines():
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k == "NTPSynchronized":
                    out["synchronized"] = v.strip().lower() == "yes"
                elif k == "TimeUSec":
                    out["last_sync"] = v.strip()
        except Exception as e:
            logger.debug(f"timedatectl probe failed: {e}")
    return out


@router.post("/ntp/sync")
async def ntp_sync(
    body: NTPConfigBody,
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Save the operator-chosen NTP server and (on Linux+systemd) request an
    immediate resync via timedatectl. Saves the server name into settings so
    the install script / system unit can pick it up."""
    from app.settings.service import SettingsService
    await SettingsService.set_value(db, "ntp_server", body.server, category="system")
    if shutil.which("timedatectl"):
        try:
            subprocess.run(["timedatectl", "set-ntp", "true"],
                           timeout=5, check=False)
        except Exception as e:
            logger.warning(f"timedatectl set-ntp failed: {e}")
    await write_audit(
        db, action="ntp_set",
        user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="system",
        description=f"NTP server set to {body.server}",
    )
    await db.commit()
    return await ntp_status(user)


# ─── DDNS (Phase 7.8) ─────────────────────────────────────────────────────────

class DDNSConfig(BaseModel):
    provider: str   # noip | dyndns | cloudflare
    hostname: str
    username: Optional[str] = None
    password: Optional[str] = None
    token: Optional[str] = None   # used by cloudflare
    zone_id: Optional[str] = None # used by cloudflare


@router.get("/ddns/status")
async def ddns_status(user: dict = Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    from app.settings.service import SettingsService
    return {
        "provider": await SettingsService.get_value(db, "ddns_provider", ""),
        "hostname": await SettingsService.get_value(db, "ddns_hostname", ""),
        "last_update_at": await SettingsService.get_value(db, "ddns_last_update_at", ""),
        "last_update_status": await SettingsService.get_value(db, "ddns_last_update_status", ""),
    }


@router.put("/ddns/config")
async def ddns_set_config(
    body: DDNSConfig,
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.settings.service import SettingsService
    from app.core.crypto import encrypt_value
    await SettingsService.set_value(db, "ddns_provider", body.provider, category="network")
    await SettingsService.set_value(db, "ddns_hostname", body.hostname, category="network")
    if body.username:
        await SettingsService.set_value(db, "ddns_username", body.username, category="network")
    if body.password:
        await SettingsService.set_value(db, "ddns_password", encrypt_value(body.password),
                                        category="network", is_sensitive=True)
    if body.token:
        await SettingsService.set_value(db, "ddns_token", encrypt_value(body.token),
                                        category="network", is_sensitive=True)
    if body.zone_id:
        await SettingsService.set_value(db, "ddns_zone_id", body.zone_id, category="network")
    await write_audit(
        db, action="ddns_config_set",
        user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="system",
        description=f"DDNS config set: {body.provider} → {body.hostname}",
    )
    await db.commit()
    return await ddns_status(user, db)


# ─── Auto-update (Phase 7.5) ──────────────────────────────────────────────────

@router.get("/updates/check")
async def updates_check(user: dict = Depends(get_admin_user)):
    """Stub for the auto-update mechanism. Real deployments swap this for an
    HTTPS GET to a vendor update server; offline installs leave it returning
    the current version unchanged."""
    return {
        "current_version": __version__,
        "latest_version": __version__,
        "update_available": False,
        "release_notes_url": None,
    }


@router.post("/updates/apply")
async def updates_apply(user: dict = Depends(get_admin_user)):
    """Apply the latest update. On the reference docker-compose deployment
    this is a no-op — operator runs `docker compose pull && docker compose up
    -d` on the host. The endpoint exists so the UI button has a target."""
    raise HTTPException(501, "Auto-apply requires a vendor update server — "
                             "pull the latest image with `docker compose pull` instead")
