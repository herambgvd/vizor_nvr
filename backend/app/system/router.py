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


# ─── Time / Timezone (Feature A1) ─────────────────────────────────────────────

class TimeConfigBody(BaseModel):
    timezone: Optional[str] = None
    ntp_server: Optional[str] = None   # set null to disable NTP and use manual time
    manual_utc: Optional[str] = None   # ISO-8601, used when ntp_server is null


@router.get("/time")
async def get_time(user: dict = Depends(get_admin_user)):
    """Return current NVR UTC time, timezone, NTP server and sync status."""
    from datetime import datetime, timezone as _tz
    from app.settings.service import SettingsService
    from app.database import async_session_maker
    async with async_session_maker() as db:
        tz_name = await SettingsService.get_value(db, "system_timezone", "UTC")
        ntp_server = await SettingsService.get_value(db, "ntp_server", None)
    ntp_synced = None
    if shutil.which("timedatectl"):
        try:
            res = subprocess.run(
                ["timedatectl", "show", "--property=NTPSynchronized"],
                capture_output=True, timeout=5, text=True,
            )
            for line in res.stdout.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    if k == "NTPSynchronized":
                        ntp_synced = v.strip().lower() == "yes"
        except Exception as e:
            logger.debug(f"timedatectl probe failed: {e}")
    return {
        "now_utc": datetime.now(_tz.utc).isoformat(),
        "timezone": tz_name,
        "ntp_server": ntp_server,
        "ntp_synced": ntp_synced,
    }


@router.put("/time")
async def set_time(
    body: TimeConfigBody,
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Update timezone and/or NTP server. If ntp_server is null and manual_utc
    is given, attempts to set the system clock (requires privilege)."""
    from app.settings.service import SettingsService
    changes = []
    if body.timezone:
        await SettingsService.set_value(db, "system_timezone", body.timezone, category="system")
        changes.append(f"timezone={body.timezone}")
        if shutil.which("timedatectl"):
            try:
                subprocess.run(["timedatectl", "set-timezone", body.timezone],
                               timeout=5, check=False)
            except Exception as e:
                logger.warning(f"timedatectl set-timezone failed: {e}")
    if body.ntp_server is not None:
        await SettingsService.set_value(db, "ntp_server", body.ntp_server, category="system")
        changes.append(f"ntp_server={body.ntp_server}")
        if shutil.which("timedatectl"):
            try:
                subprocess.run(["timedatectl", "set-ntp", "true"],
                               timeout=5, check=False)
            except Exception as e:
                logger.warning(f"timedatectl set-ntp failed: {e}")
        elif shutil.which("ntpdate") and body.ntp_server:
            try:
                subprocess.run(["ntpdate", "-u", body.ntp_server],
                               timeout=15, check=False)
            except Exception as e:
                logger.warning(f"ntpdate failed: {e}")
    elif body.manual_utc:
        # Disable NTP and set manual clock if possible
        if shutil.which("timedatectl"):
            try:
                subprocess.run(["timedatectl", "set-ntp", "false"],
                               timeout=5, check=False)
                subprocess.run(["timedatectl", "set-time", body.manual_utc],
                               timeout=5, check=False)
            except Exception as e:
                logger.warning(f"timedatectl set-time failed: {e}")
        changes.append(f"manual_utc={body.manual_utc}")
    await write_audit(
        db, action="time_config_set",
        user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="system",
        description=f"Time settings updated: {', '.join(changes)}",
    )
    await db.commit()
    return await get_time(user)


@router.post("/time/push")
async def push_time_to_cameras(
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Push current NVR time to every online camera via ONVIF SetSystemDateAndTime."""
    from sqlalchemy import text
    from app.cameras.onvif_service import onvif_service
    rows = (await db.execute(text(
        "SELECT id, name, onvif_host, onvif_port, onvif_username, onvif_password "
        "FROM cameras WHERE onvif_host IS NOT NULL AND onvif_host != ''"
    ))).fetchall()
    cameras = [dict(r._mapping) for r in rows]
    pushed = 0
    failed = []
    for cam in cameras:
        ok = await onvif_service.sync_camera_time(
            host=cam["onvif_host"],
            port=cam.get("onvif_port") or 80,
            username=cam.get("onvif_username") or "admin",
            password=cam.get("onvif_password") or "admin",
        )
        if ok:
            pushed += 1
        else:
            failed.append({"camera_id": cam["id"], "name": cam.get("name"), "host": cam["onvif_host"]})
    await write_audit(
        db, action="time_push_cameras",
        user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="system",
        description=f"Time pushed to {pushed} cameras, {len(failed)} failed",
    )
    await db.commit()
    return {"pushed": pushed, "failed": failed}


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


# ─── Network config (Feature A2) ──────────────────────────────────────────────

class NetworkConfigBody(BaseModel):
    lan_subnet: Optional[str] = None
    cors_origins: Optional[str] = None
    nvr_public_host: Optional[str] = None
    go2rtc_candidates: Optional[str] = None


@router.get("/network")
async def get_network(user: dict = Depends(get_admin_user)):
    """Return current network info (read-only host info + app-level mutable knobs)."""
    import socket
    import platform
    from app.settings.service import SettingsService
    from app.database import async_session_maker

    interfaces = []
    try:
        import psutil  # type: ignore
        for iface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                import psutil as _p
                if addr.family == _p.AF_LINK:
                    continue
                import socket as _s
                if addr.family not in (_s.AF_INET, _s.AF_INET6):
                    continue
                interfaces.append({
                    "name": iface,
                    "ip": addr.address,
                    "mask": addr.netmask,
                    "family": "ipv4" if addr.family == _s.AF_INET else "ipv6",
                })
    except Exception as e:
        logger.debug(f"psutil net_if_addrs failed: {e}")

    async with async_session_maker() as db:
        lan_subnet = await SettingsService.get_value(db, "lan_subnet", "")
        cors_origins = await SettingsService.get_value(db, "cors_origins", "*")
        nvr_public_host = await SettingsService.get_value(db, "nvr_public_host", "")
        go2rtc_candidates = await SettingsService.get_value(db, "go2rtc_candidates", "")

    return {
        "hostname": socket.gethostname(),
        "platform": platform.system(),
        "interfaces": interfaces,
        "lan_subnet": lan_subnet,
        "cors_origins": cors_origins,
        "nvr_public_host": nvr_public_host,
        "go2rtc_candidates": go2rtc_candidates,
    }


@router.put("/network")
async def set_network(
    body: NetworkConfigBody,
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Persist mutable application-level network knobs."""
    from app.settings.service import SettingsService
    changes = []
    if body.lan_subnet is not None:
        await SettingsService.set_value(db, "lan_subnet", body.lan_subnet, category="network")
        changes.append(f"lan_subnet={body.lan_subnet}")
    if body.cors_origins is not None:
        await SettingsService.set_value(db, "cors_origins", body.cors_origins, category="network")
        changes.append(f"cors_origins={body.cors_origins}")
    if body.nvr_public_host is not None:
        await SettingsService.set_value(db, "nvr_public_host", body.nvr_public_host, category="network")
        changes.append(f"nvr_public_host={body.nvr_public_host}")
    if body.go2rtc_candidates is not None:
        await SettingsService.set_value(db, "go2rtc_candidates", body.go2rtc_candidates, category="network")
        changes.append(f"go2rtc_candidates={body.go2rtc_candidates}")
    if not changes:
        raise HTTPException(400, "No mutable network fields provided")
    await write_audit(
        db, action="network_config_set",
        user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="system",
        description=f"Network config updated: {', '.join(changes)}",
    )
    await db.commit()
    return await get_network(user)


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
