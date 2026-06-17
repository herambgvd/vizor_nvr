# =============================================================================
# System Router — licensing, NTP, DDNS, version/update endpoints
# =============================================================================

import io
import json
import logging
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone as _tz
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import StreamingResponse
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
async def license_status(
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Legacy system route backed by the active .lic license service."""
    from sqlalchemy import func, select
    from app.cameras.models import Camera
    from app.license.service import get_license_service

    cam_total = (await db.execute(select(func.count(Camera.id)))).scalar() or 0
    return get_license_service().snapshot(int(cam_total))


@router.post("/license/upload")
async def license_upload(
    file: UploadFile = File(...),
    request: Request = None,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Legacy upload route backed by the active .lic license service."""
    from sqlalchemy import func, select
    from app.cameras.models import Camera
    from app.license.service import LicenseError, get_license_service

    body = await file.read()
    if len(body) > 64_000:
        raise HTTPException(400, "License file too large")
    blob = body.decode("utf-8", errors="ignore").strip()
    try:
        await get_license_service().activate(blob)
    except LicenseError as e:
        raise HTTPException(400, str(e))
    await write_audit(
        db, action="license_upload",
        user_id=user["id"], username=user["username"],
        ip_address=client_ip(request) if request else None,
        resource_type="license",
        description=f"License file uploaded ({len(body)} bytes)",
    )
    await db.commit()
    cam_total = (await db.execute(select(func.count(Camera.id)))).scalar() or 0
    return get_license_service().snapshot(int(cam_total))


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


# ─── Hardware Acceleration Probe (L1) ─────────────────────────────────────────

@router.get("/hwaccel")
async def get_hwaccel(user: dict = Depends(get_admin_user)):
    """
    Return the cached hardware-acceleration probe result.
    Probes ffmpeg for available HW encoders/decoders (NVENC, VAAPI,
    VideoToolbox, QSV) on first call; subsequent calls return the cache.

    On macOS Docker Desktop, containers run in a Linux VM without GPU
    passthrough so videotoolbox will NOT appear here even on Mac hosts.
    On a Linux host with an NVIDIA GPU, nvenc should appear.
    """
    from app.services.hwaccel_probe import probe
    return probe()


# ─── Diagnostic Bundle (Q6) ───────────────────────────────────────────────────

_SECRET_PATTERNS = [
    "password", "secret", "token", "key", "passwd", "pwd", "credential",
]


def _sanitize_env_line(line: str) -> str:
    """Replace secret values in KEY=VALUE lines with ***."""
    stripped = line.strip()
    if "=" not in stripped or stripped.startswith("#"):
        return line
    key, _, val = stripped.partition("=")
    if any(pat in key.lower() for pat in _SECRET_PATTERNS) and val:
        return f"{key}=***\n"
    return line


def _sanitize_compose(content: str) -> str:
    """Strip obvious secret values from docker-compose yaml content."""
    import re
    # Replace environment values that look like secrets
    return re.sub(
        r'((?:password|secret|token|key|passwd)\s*[:=]\s*)([^\s\n#]+)',
        r'\1***',
        content,
        flags=re.IGNORECASE,
    )


@router.get("/diagnostics/bundle")
async def diagnostics_bundle(
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream a gzipped tar archive containing sanitized diagnostic data.

    Contents:
    - manifest.json   — NVR version, host OS, timestamp, camera count, alembic head
    - compose.yml     — docker-compose.yml with secrets stripped
    - env.txt         — .env file with secrets replaced by ***
    - app.log         — last 5000 lines from backend container stdout
    - cameras.json    — camera list with ONVIF passwords stripped
    - audit-last-7d.csv — last 7 days of audit log
    - disk_health.json  — current disk health snapshot
    - hwaccel.json      — hardware acceleration probe result
    """
    from sqlalchemy import text
    from app.services.hwaccel_probe import probe as hwaccel_probe

    timestamp = datetime.now(_tz.utc)
    ts_str = timestamp.strftime("%Y%m%d-%H%M%S")
    archive_name = f"gvd-nvr-diagnostics-{ts_str}.tar.gz"

    # ── collect data ──────────────────────────────────────────────────────────

    # 1. manifest.json
    alembic_head = "unknown"
    try:
        result = subprocess.run(
            ["alembic", "current"],
            capture_output=True, text=True, timeout=10,
            cwd=os.environ.get("APP_DIR", "/app"),
        )
        alembic_head = result.stdout.strip().split("\n")[0] if result.returncode == 0 else "unknown"
    except Exception as e:
        logger.debug(f"alembic current failed: {e}")

    camera_count = 0
    try:
        row = await db.execute(text("SELECT COUNT(*) FROM cameras"))
        camera_count = row.scalar() or 0
    except Exception as e:
        logger.debug(f"camera count query failed: {e}")

    manifest = {
        "nvr_version": __version__,
        "timestamp_utc": timestamp.isoformat(),
        "hostname": platform.node(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "camera_count": camera_count,
        "alembic_head": alembic_head,
        "env_name": os.environ.get("ENV_NAME", "production"),
    }

    # 2. docker-compose.yml (sanitized)
    compose_content = ""
    script_dir = os.environ.get("COMPOSE_DIR", "/app")
    for candidate in [
        os.path.join(script_dir, "docker-compose.yml"),
        "/app/docker-compose.yml",
        "/opt/gvd-nvr/docker-compose.yml",
    ]:
        if os.path.exists(candidate):
            try:
                with open(candidate) as f:
                    compose_content = _sanitize_compose(f.read())
            except Exception as e:
                compose_content = f"# Error reading compose file: {e}"
            break
    if not compose_content:
        compose_content = "# docker-compose.yml not found at expected paths"

    # 3. .env (sanitized)
    env_content = ""
    for candidate in [
        "/app/.env",
        "/opt/gvd-nvr/.env",
        os.path.join(script_dir, ".env"),
    ]:
        if os.path.exists(candidate):
            try:
                with open(candidate) as f:
                    env_content = "".join(_sanitize_env_line(l) for l in f)
            except Exception as e:
                env_content = f"# Error reading .env: {e}"
            break
    if not env_content:
        env_content = "# .env not found at expected paths"

    # 4. app.log (last 5000 lines from container log)
    log_content = ""
    try:
        log_result = subprocess.run(
            ["docker", "compose", "logs", "--no-color", "--tail=5000", "backend"],
            capture_output=True, text=True, timeout=30,
            cwd=os.environ.get("COMPOSE_DIR", "/opt/gvd-nvr"),
        )
        log_content = log_result.stdout or log_result.stderr or "# No log output"
    except Exception as e:
        # Inside container: read from /proc/1/fd/1 or default log path
        for log_path in ["/var/log/app.log", "/app/app.log"]:
            if os.path.exists(log_path):
                try:
                    with open(log_path) as f:
                        lines = f.readlines()
                        log_content = "".join(lines[-5000:])
                    break
                except Exception:
                    pass
        if not log_content:
            log_content = f"# Could not retrieve logs: {e}"

    # 5. cameras.json (strip ONVIF passwords)
    cameras_data = []
    try:
        rows = await db.execute(text(
            "SELECT id, name, onvif_host, onvif_port, onvif_username, "
            "recording_mode, is_active, created_at FROM cameras"
        ))
        for row in rows.fetchall():
            r = dict(row._mapping)
            # Explicitly do NOT include onvif_password
            cameras_data.append(r)
    except Exception as e:
        cameras_data = [{"error": str(e)}]
    # Serialize datetimes
    cameras_json = json.dumps(
        cameras_data,
        default=lambda o: o.isoformat() if hasattr(o, "isoformat") else str(o),
        indent=2,
    )

    # 6. audit-last-7d.csv
    audit_csv = "timestamp,action,username,ip_address,resource_type,description\n"
    try:
        audit_rows = await db.execute(text(
            "SELECT created_at, action, username, ip_address, resource_type, description "
            "FROM audit_logs "
            "WHERE created_at >= datetime('now', '-7 days') "
            "ORDER BY created_at DESC "
            "LIMIT 10000"
        ))
        import csv as _csv
        buf = io.StringIO()
        writer = _csv.writer(buf)
        writer.writerow(["timestamp", "action", "username", "ip_address", "resource_type", "description"])
        for row in audit_rows.fetchall():
            writer.writerow([
                str(row[0] or ""),
                str(row[1] or ""),
                str(row[2] or ""),
                str(row[3] or ""),
                str(row[4] or ""),
                str(row[5] or ""),
            ])
        audit_csv = buf.getvalue()
    except Exception as e:
        audit_csv = f"error,{e},,,,\n"

    # 7. disk_health.json
    disk_health_json = "{}"
    try:
        from app.monitoring.disk_health import get_disk_health
        disk_health_json = json.dumps(await get_disk_health(), default=str, indent=2)
    except Exception as e:
        disk_health_json = json.dumps({"error": str(e)})

    # 8. hwaccel.json
    hwaccel_json = "{}"
    try:
        hwaccel_json = json.dumps(hwaccel_probe(), default=str, indent=2)
    except Exception as e:
        hwaccel_json = json.dumps({"error": str(e)})

    # ── build tar.gz in memory ────────────────────────────────────────────────

    def _add_text(tf: tarfile.TarFile, name: str, content: str) -> None:
        data = content.encode("utf-8", errors="replace")
        info = tarfile.TarInfo(name=name)
        info.size = len(data)
        info.mtime = int(timestamp.timestamp())
        tf.addfile(info, io.BytesIO(data))

    buf_out = io.BytesIO()
    with tarfile.open(fileobj=buf_out, mode="w:gz") as tf:
        _add_text(tf, "manifest.json",     json.dumps(manifest, indent=2))
        _add_text(tf, "compose.yml",       compose_content)
        _add_text(tf, "env.txt",           env_content)
        _add_text(tf, "app.log",           log_content)
        _add_text(tf, "cameras.json",      cameras_json)
        _add_text(tf, "audit-last-7d.csv", audit_csv)
        _add_text(tf, "disk_health.json",  disk_health_json)
        _add_text(tf, "hwaccel.json",      hwaccel_json)

    await write_audit(
        db, action="diagnostics_bundle_download",
        user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="system",
        description=f"Diagnostic bundle downloaded: {archive_name}",
    )
    await db.commit()

    buf_out.seek(0)
    archive_bytes = buf_out.read()

    return StreamingResponse(
        io.BytesIO(archive_bytes),
        media_type="application/gzip",
        headers={
            "Content-Disposition": f'attachment; filename="{archive_name}"',
            "Content-Length": str(len(archive_bytes)),
        },
    )
