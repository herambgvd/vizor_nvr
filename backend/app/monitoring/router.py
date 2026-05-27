# =============================================================================
# Monitoring Router
# =============================================================================

from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.monitoring.service import monitoring_service
from app.core.dependencies import get_current_user, get_admin_user
from app.database import get_db

router = APIRouter(prefix="/monitoring", tags=["Monitoring"])


# ---------------------------------------------------------------------------
# Bandwidth policy schemas
# ---------------------------------------------------------------------------

class BandwidthPolicy(BaseModel):
    bandwidth_limit_kbps: int = Field(default=0, ge=0)
    bandwidth_alert_threshold_pct: int = Field(default=80, ge=1, le=100)


@router.get("/resources")
async def system_resources(user: dict = Depends(get_current_user)):
    return monitoring_service.current()


@router.get("/system-info")
async def system_info(user: dict = Depends(get_current_user)):
    """One-time host info: CPU model, GPU model + memory, OS. Cached
    on the client since this rarely changes."""
    return monitoring_service.system_info()


@router.get("/disks")
async def disk_health(user: dict = Depends(get_admin_user)):
    """Return per-volume disk health: psutil usage + latest S.M.A.R.T data.
    Falls back to a fresh S.M.A.R.T poll if no snapshots are persisted yet."""
    import psutil  # type: ignore
    from sqlalchemy import text
    from app.database import async_session_maker

    # ── 1. Gather psutil partition info ──────────────────────────────────────
    partitions: dict = {}  # mount_path → info dict
    try:
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                used_pct = round(usage.percent, 1)
            except Exception:
                usage = None
                used_pct = 0.0
            partitions[part.mountpoint] = {
                "mount_path": part.mountpoint,
                "device": part.device,
                "filesystem": part.fstype,
                "total_bytes": usage.total if usage else 0,
                "used_bytes": usage.used if usage else 0,
                "free_bytes": usage.free if usage else 0,
                "used_pct": used_pct,
                # SMART fields merged below
                "smart_status": "unknown",
                "model": None,
                "serial": None,
                "temp_c": None,
                "reallocated_sectors": None,
                "power_on_hours": None,
                "alerts": [],
            }
    except Exception as _e:
        import logging as _l
        _l.getLogger(__name__).debug(f"psutil disk_partitions failed: {_e}")

    # ── 2. Load latest SMART snapshots from DB ────────────────────────────────
    smart_by_device: dict = {}
    async with async_session_maker() as db:
        try:
            rows = (await db.execute(text(
                "SELECT device, model, serial, passed, temperature_c, power_on_hours, "
                "reallocated_sectors, pending_sectors, captured_at "
                "FROM disk_health_snapshots "
                "WHERE id IN (SELECT MAX(id) FROM disk_health_snapshots GROUP BY device)"
            ))).fetchall()
            for r in rows:
                smart_by_device[r.device] = dict(r._mapping)
        except Exception:
            pass

    if not smart_by_device:
        # No history yet — attempt a live poll
        from app.services.disk_health_service import disk_health_service
        live = await disk_health_service.poll_once()
        for snap in live:
            smart_by_device[snap["device"]] = snap

    # ── 3. Merge SMART data into partition records ─────────────────────────────
    from app.services.disk_health_service import TEMP_WARN_C, TEMP_FAIL_C, REALLOC_WARN, REALLOC_FAIL, PENDING_WARN, PENDING_FAIL  # noqa

    def _smart_status(snap: dict) -> str:
        if not snap.get("passed", True):
            return "fail"
        temp = snap.get("temperature_c") or 0
        realloc = snap.get("reallocated_sectors") or 0
        pending = snap.get("pending_sectors") or 0
        if temp >= TEMP_FAIL_C or realloc >= REALLOC_FAIL or pending >= PENDING_FAIL:
            return "fail"
        if temp >= TEMP_WARN_C or realloc >= REALLOC_WARN or pending >= PENDING_WARN:
            return "warning"
        return "ok"

    def _alerts(snap: dict) -> list:
        alerts = []
        if not snap.get("passed", True):
            alerts.append("S.M.A.R.T overall-health check FAILED")
        temp = snap.get("temperature_c") or 0
        realloc = snap.get("reallocated_sectors") or 0
        pending = snap.get("pending_sectors") or 0
        if temp >= TEMP_FAIL_C:
            alerts.append(f"Critical temperature: {temp}°C")
        elif temp >= TEMP_WARN_C:
            alerts.append(f"High temperature: {temp}°C")
        if realloc >= REALLOC_FAIL:
            alerts.append(f"Critical reallocated sectors: {realloc}")
        elif realloc >= REALLOC_WARN:
            alerts.append(f"Reallocated sectors: {realloc}")
        if pending >= PENDING_FAIL:
            alerts.append(f"Critical pending sectors: {pending}")
        elif pending >= PENDING_WARN:
            alerts.append(f"Pending sectors: {pending}")
        return alerts

    # Try to match device paths — SMART device might be "/dev/sda", partition device might be "/dev/sda1"
    for mount, part_info in partitions.items():
        dev = part_info["device"]
        # Exact match first, then prefix match (e.g. /dev/sda matches /dev/sda1)
        snap = smart_by_device.get(dev)
        if snap is None:
            # Try stripping trailing digit (partition → base device)
            base = dev.rstrip("0123456789")
            snap = smart_by_device.get(base)
        if snap:
            part_info.update({
                "smart_status": _smart_status(snap),
                "model": snap.get("model"),
                "serial": snap.get("serial"),
                "temp_c": snap.get("temperature_c"),
                "reallocated_sectors": snap.get("reallocated_sectors"),
                "power_on_hours": snap.get("power_on_hours"),
                "alerts": _alerts(snap),
            })

    # ── 4. Include SMART-only devices (no matching mount) ──────────────────────
    mounted_devices = {p["device"] for p in partitions.values()}
    extra = []
    for dev, snap in smart_by_device.items():
        if dev not in mounted_devices:
            extra.append({
                "mount_path": None,
                "device": dev,
                "filesystem": None,
                "total_bytes": 0,
                "used_bytes": 0,
                "free_bytes": 0,
                "used_pct": 0,
                "smart_status": _smart_status(snap),
                "model": snap.get("model"),
                "serial": snap.get("serial"),
                "temp_c": snap.get("temperature_c"),
                "reallocated_sectors": snap.get("reallocated_sectors"),
                "power_on_hours": snap.get("power_on_hours"),
                "alerts": _alerts(snap),
            })

    result = list(partitions.values()) + extra
    return {"disks": result}


@router.get("/resources/history")
async def resource_history(
    minutes: int = Query(60, le=360),
    user: dict = Depends(get_current_user),
):
    return monitoring_service.history(minutes)


@router.get("/bandwidth")
async def all_bandwidth(user: dict = Depends(get_current_user)):
    """Current bandwidth per camera (kbps)."""
    return monitoring_service.get_all_bandwidth()


# NOTE: /bandwidth/alerts MUST be registered before /bandwidth/{camera_id}
# so the literal path wins over the wildcard.
@router.get("/bandwidth/alerts")
async def bandwidth_alerts(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return bandwidth_alert events from the last 24 hours with camera names."""
    from app.events.service import EventService
    from app.cameras.models import Camera
    from sqlalchemy import select

    since = datetime.utcnow() - timedelta(hours=24)
    events, _ = await EventService.list_events(
        db,
        event_type="bandwidth_alert",
        start_date=since,
        limit=200,
    )

    camera_ids = list({e.camera_id for e in events if e.camera_id})
    cam_names: dict[str, str] = {}
    if camera_ids:
        result = await db.execute(
            select(Camera.id, Camera.name).where(Camera.id.in_(camera_ids))
        )
        cam_names = {row[0]: row[1] for row in result.fetchall()}

    return [
        {
            "id": e.id,
            "camera_id": e.camera_id,
            "camera_name": cam_names.get(e.camera_id or "", e.camera_id),
            "timestamp": e.triggered_at.isoformat() if e.triggered_at else None,
            "current_kbps": (e.event_metadata or {}).get("current_kbps"),
            "limit_kbps": (e.event_metadata or {}).get("limit_kbps"),
            "threshold_pct": (e.event_metadata or {}).get("threshold_pct"),
            "severity": e.severity,
        }
        for e in events
    ]


@router.get("/bandwidth/{camera_id}")
async def camera_bandwidth(
    camera_id: str,
    user: dict = Depends(get_current_user),
):
    return monitoring_service.get_camera_bandwidth(camera_id)


@router.get("/bandwidth/{camera_id}/history")
async def camera_bandwidth_history(
    camera_id: str,
    minutes: int = Query(60, le=360),
    user: dict = Depends(get_current_user),
):
    return monitoring_service.get_bandwidth_history(camera_id, minutes)


# ------------------------------------------------------------------
# System Health Dashboard — single endpoint for frontend dashboard
# ------------------------------------------------------------------

@router.get("/health")
async def system_health(user: dict = Depends(get_current_user)):
    """
    Aggregated health dashboard:
    - System resources (CPU / RAM / disk)
    - FFmpeg process status per camera
    - go2rtc status
    - Active recording count
    - Storage usage per pool
    - Any cameras in failover mode
    """
    import os
    from app.services.ffmpeg_manager import ffmpeg_manager
    from app.services.go2rtc_manager import go2rtc_manager
    from app.database import async_session_maker
    from app.cameras.service import CameraService
    from app.storage.service import StorageService

    # System resources
    resources = monitoring_service.current()

    # FFmpeg processes
    ffmpeg_health = await ffmpeg_manager.health_check()
    active_cameras = len(ffmpeg_health)
    failover_cameras = [cid for cid, s in ffmpeg_health.items() if s.get("failover_active")]

    # go2rtc
    go2rtc_ok = await go2rtc_manager.is_healthy()

    # DB queries
    async with async_session_maker() as db:
        all_cameras = await CameraService.get_all(db)
        total_cameras = len(all_cameras)
        online_cameras = sum(1 for c in all_cameras if c.status == "online")
        offline_cameras = sum(1 for c in all_cameras if c.status in ("offline", "error"))

        pools = await StorageService.get_all_pools(db)
        storage_summary = []
        for pool in pools:
            used_bytes = StorageService.get_pool_used_bytes(pool.path)
            total_bytes = pool.max_size_bytes or 0
            pct = round((used_bytes / total_bytes) * 100, 1) if total_bytes > 0 else 0
            storage_summary.append({
                "pool_id": pool.id,
                "name": pool.name,
                "path": pool.path,
                "used_gb": round(used_bytes / 1_073_741_824, 2),
                "total_gb": round(total_bytes / 1_073_741_824, 2) if total_bytes else None,
                "percent_used": pct,
                "warning": pct > 85,
                "critical": pct > 95,
            })

    return {
        "system": resources,
        "cameras": {
            "total": total_cameras,
            "online": online_cameras,
            "offline": offline_cameras,
            "recording": active_cameras,
            "failover": failover_cameras,
        },
        "ffmpeg": {
            "active_processes": active_cameras,
            "processes": ffmpeg_health,
        },
        "go2rtc": {
            "healthy": go2rtc_ok,
        },
        "storage": storage_summary,
    }


# ---------------------------------------------------------------------------
# Per-camera bandwidth policy
# ---------------------------------------------------------------------------

@router.get("/cameras/{camera_id}/bandwidth/policy")
async def get_bandwidth_policy(
    camera_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get per-camera bandwidth limit and alert threshold."""
    from app.cameras.models import Camera
    from sqlalchemy import select
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    cam = result.scalar_one_or_none()
    if not cam:
        raise HTTPException(404, "Camera not found")
    return BandwidthPolicy(
        bandwidth_limit_kbps=cam.bandwidth_limit_kbps or 0,
        bandwidth_alert_threshold_pct=cam.bandwidth_alert_threshold_pct or 80,
    )


@router.put("/cameras/{camera_id}/bandwidth/policy")
async def update_bandwidth_policy(
    camera_id: str,
    body: BandwidthPolicy,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Update per-camera bandwidth limit and alert threshold (admin only)."""
    from app.cameras.models import Camera
    from sqlalchemy import select
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    cam = result.scalar_one_or_none()
    if not cam:
        raise HTTPException(404, "Camera not found")
    cam.bandwidth_limit_kbps = body.bandwidth_limit_kbps
    cam.bandwidth_alert_threshold_pct = body.bandwidth_alert_threshold_pct
    await db.commit()
    return body
