# =============================================================================
# Storage Router
# =============================================================================

from typing import List, Optional

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.storage.models import (
    StoragePoolCreate, StoragePoolUpdate, StoragePoolResponse,
    TierRuleCreate, TierRuleResponse, StorageSummary,
    CloudConfigCreate, CloudConfigUpdate, CloudConfigResponse, CloudUploadJob,
    BackupScheduleCreate, BackupScheduleUpdate, BackupScheduleResponse,
)
from app.storage.service import StorageService
from app.core.dependencies import get_admin_user
from app.core.audit_logger import write_audit, client_ip

router = APIRouter(prefix="/storage", tags=["Storage"])
svc = StorageService()


# ── Summary ────────────────────────────────────────────────────────

@router.get("/summary", response_model=StorageSummary)
async def storage_summary(
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.get_summary(db)


# ── Pool CRUD ──────────────────────────────────────────────────────

@router.get("/pools", response_model=List[StoragePoolResponse])
async def list_pools(
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    pools = await svc.get_all_pools(db)
    # Enrich with disk usage
    result = []
    for pool in pools:
        disk = svc.get_disk_usage(pool.path)
        used = svc.get_pool_used_bytes(pool.path)
        result.append(StoragePoolResponse(
            **{c.name: getattr(pool, c.name) for c in pool.__table__.columns},
            used_bytes=used,
            free_bytes=max(0, (pool.max_size_bytes or disk["total_bytes"]) - used),
            recording_count=0,
        ))
    return result


@router.get("/analytics")
async def storage_analytics(
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Daily write rate per camera (last 7/30/90 days) + projected
    days-until-full per pool. Used by the Storage > Analytics tab."""
    from sqlalchemy import text
    # Per-camera daily byte rate
    rows7 = (await db.execute(text("""
        SELECT camera_id, COALESCE(SUM(file_size), 0) AS total
        FROM recordings
        WHERE start_time >= datetime('now', '-7 days')
        GROUP BY camera_id
    """))).fetchall()
    rows30 = (await db.execute(text("""
        SELECT camera_id, COALESCE(SUM(file_size), 0) AS total
        FROM recordings
        WHERE start_time >= datetime('now', '-30 days')
        GROUP BY camera_id
    """))).fetchall()
    rows90 = (await db.execute(text("""
        SELECT camera_id, COALESCE(SUM(file_size), 0) AS total
        FROM recordings
        WHERE start_time >= datetime('now', '-90 days')
        GROUP BY camera_id
    """))).fetchall()

    per_camera = {}
    for cid, total in rows7:
        per_camera.setdefault(cid, {})["bytes_per_day_7d"] = total / 7.0
    for cid, total in rows30:
        per_camera.setdefault(cid, {})["bytes_per_day_30d"] = total / 30.0
    for cid, total in rows90:
        per_camera.setdefault(cid, {})["bytes_per_day_90d"] = total / 90.0

    # Per-pool days-until-full
    summary = await svc.get_summary(db)
    pools_proj = []
    for p in summary["pools"]:
        rate = 0
        # Estimate daily aggregate write rate to this pool from 30-day cameras
        # (cheap heuristic — production tooling can refine).
        free = p["free_bytes"]
        # Sum per_camera bytes_per_day_30d for cameras pinned to this pool
        from sqlalchemy import text as _t
        cams = (await db.execute(_t(
            "SELECT id FROM cameras WHERE storage_pool_id = :pid"
        ), {"pid": p["id"]})).fetchall()
        for (cid,) in cams:
            rate += per_camera.get(cid, {}).get("bytes_per_day_30d", 0)
        days_left = (free / rate) if rate > 0 else None
        pools_proj.append({
            "pool_id": p["id"], "pool_name": p["name"],
            "free_bytes": free, "daily_write_bytes": rate,
            "projected_days_until_full": round(days_left, 1) if days_left else None,
        })

    return {
        "per_camera": per_camera,
        "pools": pools_proj,
        "top_consumers_30d": sorted(
            [{"camera_id": cid, **v} for cid, v in per_camera.items()],
            key=lambda x: x.get("bytes_per_day_30d", 0),
            reverse=True,
        )[:10],
    }


@router.get("/pools/{pool_id}/health")
async def pool_health(
    pool_id: str,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Cheap writability check for a pool — path exists, writable,
    has >=1 GiB headroom (or remaining quota). Used by failover decisions."""
    info = await svc.get_pool_health(db, pool_id)
    if info is None:
        raise HTTPException(404, "Pool not found")
    return info


@router.post("/pools/test-connection")
async def test_pool_connection(
    body: dict,
    user: dict = Depends(get_admin_user),
):
    """Pre-flight check for NAS/NFS/SMB mounts before creating a pool.
    Body: {path: str}. Returns {ok, writable, message}."""
    path = body.get("path", "")
    if not path:
        raise HTTPException(400, "path is required")
    import os
    info = {"path": path, "exists": os.path.isdir(path),
            "writable": os.access(path, os.W_OK) if os.path.isdir(path) else False,
            "message": "ok"}
    if not info["exists"]:
        info["message"] = "Path does not exist on backend host (mount it via fstab/docker volume first)"
    elif not info["writable"]:
        info["message"] = "Path exists but is not writable by the backend process"
    return info


@router.post("/pools", response_model=StoragePoolResponse, status_code=201)
async def create_pool(
    data: StoragePoolCreate,
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    pool = await svc.create_pool(db, data)
    await write_audit(
        db, action="storage_pool_create", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="storage_pool", resource_id=pool.id,
    )
    await db.commit()
    return StoragePoolResponse(
        **{c.name: getattr(pool, c.name) for c in pool.__table__.columns},
        used_bytes=0, free_bytes=0, recording_count=0,
    )


@router.put("/pools/{pool_id}", response_model=StoragePoolResponse)
async def update_pool(
    pool_id: str,
    data: StoragePoolUpdate,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    pool = await svc.update_pool(db, pool_id, data)
    if not pool:
        raise HTTPException(404, "Pool not found")
    return StoragePoolResponse(
        **{c.name: getattr(pool, c.name) for c in pool.__table__.columns},
        used_bytes=0, free_bytes=0, recording_count=0,
    )


@router.delete("/pools/{pool_id}", status_code=204)
async def delete_pool(
    pool_id: str,
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    if not await svc.delete_pool(db, pool_id):
        raise HTTPException(404)
    await write_audit(
        db, action="storage_pool_delete", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="storage_pool", resource_id=pool_id,
        severity="warning",
    )
    await db.commit()


# ── NAS Operations ─────────────────────────────────────────────────

class NASTestRequest(BaseModel):
    server: str
    protocol: str  # nfs / smb
    username: Optional[str] = None
    password: Optional[str] = None
    domain: Optional[str] = None


@router.post("/nas/test-connection")
async def test_nas_connection(
    body: NASTestRequest,
    user: dict = Depends(get_admin_user),
):
    """Test reachability of a NAS server before creating a pool."""
    from app.storage.nas_service import nas_service
    return nas_service.test_connection(
        body.server, body.protocol,
        username=body.username, password=body.password, domain=body.domain,
    )


@router.post("/pools/{pool_id}/mount")
async def mount_nas_pool(
    pool_id: str,
    user: dict = Depends(get_admin_user),
):
    """Manually mount a NAS storage pool."""
    result = await svc.mount_pool(pool_id)
    if not result["ok"]:
        # 500 with the upstream message in the body so the UI surfaces
        # the real reason (e.g. "Container lacks CAP_SYS_ADMIN") instead
        # of the misleading "502 Bad Gateway" axios reports for 502 codes.
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@router.post("/pools/{pool_id}/unmount")
async def unmount_nas_pool(
    pool_id: str,
    user: dict = Depends(get_admin_user),
):
    """Manually unmount a NAS storage pool."""
    result = await svc.unmount_pool(pool_id)
    if not result["ok"]:
        # 500 with the upstream message in the body so the UI surfaces
        # the real reason (e.g. "Container lacks CAP_SYS_ADMIN") instead
        # of the misleading "502 Bad Gateway" axios reports for 502 codes.
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@router.get("/pools/{pool_id}/nas-health")
async def nas_pool_health(
    pool_id: str,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Deep health check for a NAS pool (mount state + write latency)."""
    from app.storage.nas_service import nas_service
    pool = await svc.get_pool(db, pool_id)
    if not pool:
        raise HTTPException(404, "Pool not found")
    if pool.pool_type == "local":
        raise HTTPException(400, "Local pools do not support NAS health checks")
    return nas_service.check_mount_health(pool)


# ── Tier Rules ─────────────────────────────────────────────────────

@router.get("/rules", response_model=List[TierRuleResponse])
async def list_tier_rules(
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.get_all_rules(db)


@router.post("/rules", response_model=TierRuleResponse, status_code=201)
async def create_tier_rule(
    data: TierRuleCreate,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.create_rule(db, data)


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_tier_rule(
    rule_id: str,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    if not await svc.delete_rule(db, rule_id):
        raise HTTPException(404)


# ── System Disk Explorer ───────────────────────────────────────────

@router.get("/disks")
async def system_disks(
    user: dict = Depends(get_admin_user),
):
    """Get system disk partitions and usage info."""
    return await svc.get_system_disk_info()


# ── Cloud Storage Config ───────────────────────────────────────────

@router.get("/cloud", response_model=list[CloudConfigResponse])
async def list_cloud_configs(
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    configs = await svc.get_all_cloud_configs(db)
    return [CloudConfigResponse.model_validate(c) for c in configs]


@router.post("/cloud", response_model=CloudConfigResponse, status_code=201)
async def create_cloud_config(
    data: CloudConfigCreate,
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    cfg = await svc.create_cloud_config(db, data)
    await write_audit(
        db, action="cloud_config_create", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="cloud_config", resource_id=cfg.id,
    )
    await db.commit()
    return CloudConfigResponse.model_validate(cfg)


@router.put("/cloud/{config_id}", response_model=CloudConfigResponse)
async def update_cloud_config(
    config_id: str,
    data: CloudConfigUpdate,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    cfg = await svc.update_cloud_config(db, config_id, data)
    if not cfg:
        raise HTTPException(404, "Cloud config not found")
    return CloudConfigResponse.model_validate(cfg)


@router.delete("/cloud/{config_id}", status_code=204)
async def delete_cloud_config(
    config_id: str,
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    if not await svc.delete_cloud_config(db, config_id):
        raise HTTPException(404)
    await write_audit(
        db, action="cloud_config_delete", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="cloud_config", resource_id=config_id,
        severity="warning",
    )
    await db.commit()


@router.post("/cloud/{config_id}/test")
async def test_cloud_config(
    config_id: str,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    cfg = await svc.get_cloud_config(db, config_id)
    if not cfg:
        raise HTTPException(404, "Cloud config not found")
    return await svc.test_cloud_connection(cfg)


# ── Backup Schedules ───────────────────────────────────────────────

@router.get("/backups", response_model=list[BackupScheduleResponse])
async def list_backup_schedules(
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.storage.models import BackupSchedule
    from sqlalchemy import select
    result = await db.execute(select(BackupSchedule).order_by(BackupSchedule.created_at))
    return [BackupScheduleResponse.model_validate(s) for s in result.scalars().all()]


@router.post("/backups", response_model=BackupScheduleResponse, status_code=201)
async def create_backup_schedule(
    data: BackupScheduleCreate,
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.storage.models import BackupSchedule
    sched = BackupSchedule(**data.model_dump())
    db.add(sched)
    await db.commit()
    await db.refresh(sched)
    await write_audit(
        db, action="backup_schedule_create", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="backup_schedule", resource_id=sched.id,
    )
    await db.commit()
    return BackupScheduleResponse.model_validate(sched)


@router.put("/backups/{schedule_id}", response_model=BackupScheduleResponse)
async def update_backup_schedule(
    schedule_id: str,
    data: BackupScheduleUpdate,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.storage.models import BackupSchedule
    sched = await db.get(BackupSchedule, schedule_id)
    if not sched:
        raise HTTPException(404, "Backup schedule not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(sched, k, v)
    await db.commit()
    await db.refresh(sched)
    return BackupScheduleResponse.model_validate(sched)


@router.delete("/backups/{schedule_id}", status_code=204)
async def delete_backup_schedule(
    schedule_id: str,
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.storage.models import BackupSchedule
    sched = await db.get(BackupSchedule, schedule_id)
    if not sched:
        raise HTTPException(404)
    await db.delete(sched)
    await write_audit(
        db, action="backup_schedule_delete", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="backup_schedule", resource_id=schedule_id,
        severity="warning",
    )
    await db.commit()


@router.post("/backups/{schedule_id}/run")
async def run_backup_now(
    schedule_id: str,
    user: dict = Depends(get_admin_user),
):
    from app.storage.archive_service import archive_service
    result = await archive_service.run_backup_now(schedule_id)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


# ── RAID Management ────────────────────────────────────────────────

@router.get("/raid/arrays")
async def list_raid_arrays(
    user: dict = Depends(get_admin_user),
):
    from app.storage.raid_service import raid_service
    return await raid_service.list_arrays()


@router.get("/raid/devices")
async def list_block_devices(
    user: dict = Depends(get_admin_user),
):
    from app.storage.raid_service import raid_service
    return await raid_service.list_block_devices()


class RAIDCreateBody(BaseModel):
    device: str
    level: str
    members: List[str]
    force: bool = False


@router.post("/raid/arrays")
async def create_raid_array(
    body: RAIDCreateBody,
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.storage.raid_service import raid_service
    result = await raid_service.create_array(body.device, body.level, body.members, body.force)
    await write_audit(
        db, action="raid_create", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="raid", resource_id=body.device,
        description=f"Created RAID {body.level} on {body.device}",
    )
    await db.commit()
    if not result["success"]:
        raise HTTPException(400, result["message"])
    return result


@router.delete("/raid/arrays/{device}")
async def remove_raid_array(
    device: str,
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.storage.raid_service import raid_service
    result = await raid_service.remove_array(device)
    await write_audit(
        db, action="raid_remove", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="raid", resource_id=device,
        description=f"Removed RAID array {device}",
        severity="warning",
    )
    await db.commit()
    if not result["success"]:
        raise HTTPException(400, result["message"])
    return result


@router.post("/cloud/upload")
async def upload_to_cloud(
    job: CloudUploadJob,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.upload_recording_to_cloud(db, job.recording_id, job.cloud_config_id)
