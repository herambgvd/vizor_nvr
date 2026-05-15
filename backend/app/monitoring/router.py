# =============================================================================
# Monitoring Router
# =============================================================================

from typing import Optional
from fastapi import APIRouter, Depends, Query

from app.monitoring.service import monitoring_service
from app.core.dependencies import get_current_user, get_admin_user

router = APIRouter(prefix="/monitoring", tags=["Monitoring"])


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
    """Return latest S.M.A.R.T snapshot per device. Falls back to a fresh
    poll if no snapshots have been persisted yet."""
    from sqlalchemy import text
    from app.database import async_session_maker
    async with async_session_maker() as db:
        rows = (await db.execute(text(
            "SELECT device, model, serial, passed, temperature_c, power_on_hours, "
            "reallocated_sectors, pending_sectors, captured_at "
            "FROM disk_health_snapshots "
            "WHERE id IN (SELECT MAX(id) FROM disk_health_snapshots GROUP BY device)"
        ))).fetchall()
    if not rows:
        from app.services.disk_health_service import disk_health_service
        return {"disks": await disk_health_service.poll_once()}
    return {"disks": [dict(r._mapping) for r in rows]}


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
