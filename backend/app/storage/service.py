# =============================================================================
# Storage Service — pool CRUD, space tracking, tiering logic
# =============================================================================

import os
import shutil
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.storage.models import StoragePool, StorageTierRule, CloudStorageConfig

logger = logging.getLogger(__name__)


class StorageService:

    # ------------------------------------------------------------------
    # Pool CRUD
    # ------------------------------------------------------------------

    @staticmethod
    async def get_all_pools(db: AsyncSession) -> List[StoragePool]:
        result = await db.execute(select(StoragePool).order_by(StoragePool.priority.desc()))
        return list(result.scalars().all())

    @staticmethod
    async def get_pool(db: AsyncSession, pool_id: str) -> Optional[StoragePool]:
        result = await db.execute(select(StoragePool).where(StoragePool.id == pool_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def create_pool(db: AsyncSession, data) -> StoragePool:
        # Ensure directory exists
        os.makedirs(data.path, exist_ok=True)

        pool = StoragePool(
            name=data.name,
            path=data.path,
            pool_type=data.pool_type,
            max_size_bytes=data.max_size_bytes,
            priority=data.priority,
            is_default=data.is_default,
            mount_options=data.mount_options,
            nas_server=data.nas_server,
            nas_share=data.nas_share,
            nas_protocol=data.nas_protocol,
            nas_username=data.nas_username,
            nas_password=data.nas_password,
            nas_domain=data.nas_domain,
            nas_auto_mount=data.nas_auto_mount,
        )

        # If is_default, un-default all others
        if data.is_default:
            existing = await db.execute(select(StoragePool).where(StoragePool.is_default.is_(True)))
            for p in existing.scalars().all():
                p.is_default = False

        db.add(pool)
        await db.commit()
        await db.refresh(pool)
        return pool

    @staticmethod
    async def update_pool(db: AsyncSession, pool_id: str, data) -> Optional[StoragePool]:
        pool = await StorageService.get_pool(db, pool_id)
        if not pool:
            return None
        update = data.model_dump(exclude_unset=True)
        if update.get("is_default"):
            existing = await db.execute(select(StoragePool).where(StoragePool.is_default.is_(True)))
            for p in existing.scalars().all():
                p.is_default = False
        for k, v in update.items():
            setattr(pool, k, v)
        await db.commit()
        await db.refresh(pool)
        return pool

    @staticmethod
    async def mount_pool(pool_id: str) -> dict:
        """Attempt to mount a NAS pool by ID."""
        from app.storage.nas_service import nas_service
        from app.database import async_session_maker
        async with async_session_maker() as db:
            pool = await StorageService.get_pool(db, pool_id)
            if not pool:
                return {"ok": False, "message": "Pool not found"}
            result = nas_service.mount_pool(pool)
            pool.nas_mount_state = "mounted" if result["ok"] else "error"
            pool.nas_last_mount_error = None if result["ok"] else result["message"]
            # Strip tzinfo: nas_last_mount_at column is TIMESTAMP WITHOUT TIME ZONE.
            # asyncpg refuses to bind a tz-aware datetime to a naive column.
            pool.nas_last_mount_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await db.commit()
            return result

    @staticmethod
    async def unmount_pool(pool_id: str) -> dict:
        """Unmount a NAS pool by ID."""
        from app.storage.nas_service import nas_service
        from app.database import async_session_maker
        async with async_session_maker() as db:
            pool = await StorageService.get_pool(db, pool_id)
            if not pool:
                return {"ok": False, "message": "Pool not found"}
            result = nas_service.unmount_pool(pool.path)
            if result["ok"]:
                pool.nas_mount_state = "unmounted"
                pool.nas_last_mount_error = None
            else:
                pool.nas_mount_state = "error"
                pool.nas_last_mount_error = result["message"]
            await db.commit()
            return result

    @staticmethod
    async def delete_pool(db: AsyncSession, pool_id: str) -> bool:
        pool = await StorageService.get_pool(db, pool_id)
        if not pool:
            return False
        await db.delete(pool)
        await db.commit()
        return True

    @staticmethod
    async def get_default_pool(db: AsyncSession) -> Optional[StoragePool]:
        result = await db.execute(select(StoragePool).where(StoragePool.is_default.is_(True)))
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Pool disk usage
    # ------------------------------------------------------------------

    @staticmethod
    def get_disk_usage(path: str) -> dict:
        """Get disk space for a storage pool path."""
        try:
            total, used, free = shutil.disk_usage(path)
            return {"total_bytes": total, "used_bytes": used, "free_bytes": free}
        except Exception:
            return {"total_bytes": 0, "used_bytes": 0, "free_bytes": 0}

    @staticmethod
    def get_pool_used_bytes(path: str) -> int:
        """Get actual bytes used by files in the pool path."""
        total = 0
        try:
            for root, dirs, files in os.walk(path):
                for f in files:
                    total += os.path.getsize(os.path.join(root, f))
        except Exception:
            pass
        return total

    # ------------------------------------------------------------------
    # Resolve recording path for a camera
    # ------------------------------------------------------------------

    @staticmethod
    def _pool_writable(pool) -> dict:
        """Cheap health check: path exists, is a directory, is writable,
        has at least 1 GiB free (or quota headroom), and is not a stale mount.
        Used by select_writable_pool and exposed at GET /api/storage/pools/{id}/health."""
        path = pool.path
        info = {"id": pool.id, "name": pool.name, "writable": False, "reason": None,
                "free_bytes": 0, "quota_bytes": pool.max_size_bytes}
        if not os.path.isdir(path):
            info["reason"] = "path missing"
            return info
        if not os.access(path, os.W_OK):
            info["reason"] = "not writable"
            return info
        # Stale mount detection: try to create and remove a sentinel file
        try:
            sentinel = os.path.join(path, ".gvd_nvr_write_test")
            with open(sentinel, "w") as f:
                f.write("ok")
            os.remove(sentinel)
        except OSError:
            info["reason"] = "mount stale or read-only"
            return info
        disk = StorageService.get_disk_usage(path)
        free = disk["free_bytes"]
        # If a soft quota is set, prefer the smaller of (disk free, quota remaining)
        if pool.max_size_bytes:
            used = StorageService.get_pool_used_bytes(path)
            quota_left = max(0, pool.max_size_bytes - used)
            free = min(free, quota_left)
        info["free_bytes"] = free
        if free < 1_073_741_824:  # 1 GiB headroom
            info["reason"] = "low space"
            return info
        info["writable"] = True
        return info

    @staticmethod
    async def get_pool_health(db: AsyncSession, pool_id: str) -> Optional[dict]:
        pool = await StorageService.get_pool(db, pool_id)
        if not pool:
            return None
        return StorageService._pool_writable(pool)

    @staticmethod
    async def select_writable_pool(db: AsyncSession, preferred_pool_id: Optional[str] = None):
        """Return the highest-priority healthy pool.

        Order:
          1. The camera's assigned pool, if healthy.
          2. Active pools by descending priority.
          3. The default pool.
        Returns None if no pool is writable — caller falls back to
        settings.STORAGE_PATH.
        """
        if preferred_pool_id:
            pool = await StorageService.get_pool(db, preferred_pool_id)
            if pool and pool.is_active and StorageService._pool_writable(pool)["writable"]:
                return pool
        # Fall through to priority-ordered scan
        result = await db.execute(
            select(StoragePool)
            .where(StoragePool.is_active.is_(True))
            .order_by(StoragePool.priority.desc(), StoragePool.is_default.desc())
        )
        for pool in result.scalars().all():
            if StorageService._pool_writable(pool)["writable"]:
                return pool
        return None

    @staticmethod
    async def resolve_recording_path(db: AsyncSession, camera) -> str:
        """Pick the best writable pool for this camera, fall back to default
        STORAGE_PATH if none is healthy. Logs a warning whenever failover
        kicks in so the operator can correlate with disk events."""
        pool = await StorageService.select_writable_pool(db, camera.storage_pool_id)
        if pool:
            if camera.storage_pool_id and pool.id != camera.storage_pool_id:
                logger.warning(
                    f"[{camera.id}] preferred pool {camera.storage_pool_id} "
                    f"unhealthy, failing over to pool {pool.id} ({pool.name})"
                )
            base = pool.path
        else:
            logger.warning(f"[{camera.id}] no writable pool available, using STORAGE_PATH fallback")
            base = str(settings.STORAGE_PATH)
            # Validate fallback path is actually writable
            try:
                sentinel = os.path.join(base, ".gvd_nvr_write_test")
                os.makedirs(base, exist_ok=True)
                with open(sentinel, "w") as f:
                    f.write("ok")
                os.remove(sentinel)
            except OSError as e:
                logger.error(f"[{camera.id}] STORAGE_PATH fallback is not writable: {e}")
                raise RuntimeError(f"No writable storage available for camera {camera.id}")
        path = os.path.join(base, camera.id)
        os.makedirs(path, exist_ok=True)
        return path

    @staticmethod
    async def has_writable_storage(db: AsyncSession, min_free_gb: Optional[float] = None) -> bool:
        """Return True if ANY storage target (an active pool or the STORAGE_PATH
        fallback) is writable with at least *min_free_gb* GiB of free space.

        Used as a back-pressure gate before (re)starting recordings so a
        disk-full condition backs off instead of restart-storming. Defaults to
        settings.MIN_FREE_GB when no threshold is passed.
        """
        if min_free_gb is None:
            min_free_gb = settings.MIN_FREE_GB
        min_free_bytes = int(min_free_gb * 1_073_741_824)

        # 1. Check active pools (respecting soft quota headroom).
        try:
            result = await db.execute(
                select(StoragePool).where(StoragePool.is_active.is_(True))
            )
            for pool in result.scalars().all():
                info = StorageService._pool_writable(pool)
                if info["writable"] and info["free_bytes"] >= min_free_bytes:
                    return True
        except Exception as e:
            logger.debug(f"has_writable_storage pool scan error: {e}")

        # 2. Fall back to STORAGE_PATH (matches resolve_recording_path fallback).
        try:
            base = str(settings.STORAGE_PATH)
            if os.path.isdir(base) and os.access(base, os.W_OK):
                disk = StorageService.get_disk_usage(base)
                if disk["free_bytes"] >= min_free_bytes:
                    return True
        except Exception as e:
            logger.debug(f"has_writable_storage fallback check error: {e}")

        return False

    @staticmethod
    async def select_mirror_pool(db: AsyncSession, primary_pool_id: str):
        """For redundant recording (Task 4.4): return the next highest-priority
        healthy pool that ISN'T the primary. Returns None if only one pool
        exists or no secondary is healthy."""
        result = await db.execute(
            select(StoragePool)
            .where(
                StoragePool.is_active.is_(True),
                StoragePool.id != primary_pool_id,
            )
            .order_by(StoragePool.priority.desc())
        )
        for pool in result.scalars().all():
            if StorageService._pool_writable(pool)["writable"]:
                return pool
        return None

    # ------------------------------------------------------------------
    # Tier Rules
    # ------------------------------------------------------------------

    @staticmethod
    async def get_all_rules(db: AsyncSession) -> List[StorageTierRule]:
        result = await db.execute(select(StorageTierRule).order_by(StorageTierRule.created_at))
        return list(result.scalars().all())

    @staticmethod
    async def create_rule(db: AsyncSession, data) -> StorageTierRule:
        rule = StorageTierRule(
            name=data.name,
            source_pool_id=data.source_pool_id,
            target_pool_id=data.target_pool_id,
            age_threshold_hours=data.age_threshold_hours,
        )
        db.add(rule)
        await db.commit()
        await db.refresh(rule)
        return rule

    @staticmethod
    async def delete_rule(db: AsyncSession, rule_id: str) -> bool:
        result = await db.execute(select(StorageTierRule).where(StorageTierRule.id == rule_id))
        rule = result.scalar_one_or_none()
        if not rule:
            return False
        await db.delete(rule)
        await db.commit()
        return True

    # ------------------------------------------------------------------
    # Execute tier rules (called by retention service)
    # ------------------------------------------------------------------

    @staticmethod
    async def execute_tier_rules(db: AsyncSession):
        """
        Process all active tier rules: move recordings older than threshold
        from source pool to target pool.
        """
        from app.recordings.models import Recording

        rules = await db.execute(
            select(StorageTierRule).where(StorageTierRule.is_active.is_(True))
        )
        for rule in rules.scalars().all():
            source = await StorageService.get_pool(db, rule.source_pool_id)
            target = await StorageService.get_pool(db, rule.target_pool_id)
            if not source or not target:
                continue
            if not target.is_active:
                continue

            cutoff = datetime.utcnow() - timedelta(hours=rule.age_threshold_hours)

            # Find recordings in source pool older than cutoff
            recs = await db.execute(
                select(Recording).where(
                    Recording.storage_pool_id == source.id,
                    Recording.start_time < cutoff,
                )
            )
            moved = 0
            for rec in recs.scalars().all():
                old_path = rec.file_path
                if not os.path.exists(old_path):
                    continue

                # Build new path under target pool
                relative = os.path.relpath(old_path, source.path)
                new_path = os.path.join(target.path, relative)
                os.makedirs(os.path.dirname(new_path), exist_ok=True)

                try:
                    # Atomic cross-filesystem move: copy to temp, verify, then swap
                    tmp_path = new_path + ".tmp"
                    shutil.copy2(old_path, tmp_path)
                    # Verify checksum after copy (optional but recommended)
                    from app.recordings.service import RecordingService
                    src_hash = RecordingService.compute_sha256(old_path)
                    dst_hash = RecordingService.compute_sha256(tmp_path)
                    if src_hash != dst_hash:
                        os.remove(tmp_path)
                        logger.error(f"Tier move checksum mismatch: {old_path} → {new_path}")
                        continue
                    os.rename(tmp_path, new_path)
                    os.remove(old_path)
                    rec.file_path = new_path
                    rec.storage_pool_id = target.id
                    moved += 1
                except Exception as e:
                    logger.error(f"Tier move failed: {old_path} → {new_path}: {e}")

            if moved:
                rule.last_run_at = datetime.utcnow()
                await db.commit()
                logger.info(f"Tier rule '{rule.name}': moved {moved} recordings")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    @staticmethod
    async def get_summary(db: AsyncSession) -> dict:
        from app.recordings.models import Recording

        pools = await StorageService.get_all_pools(db)
        total_cap = 0
        total_used = 0
        total_free = 0
        pool_data = []

        for pool in pools:
            disk = StorageService.get_disk_usage(pool.path)
            used = StorageService.get_pool_used_bytes(pool.path)

            # Count recordings in this pool
            rec_count = await db.execute(
                select(func.count(Recording.id)).where(Recording.storage_pool_id == pool.id)
            )
            count = rec_count.scalar() or 0

            cap = pool.max_size_bytes or disk["total_bytes"]
            free = max(0, cap - used)
            total_cap += cap
            total_used += used
            total_free += free

            pool_data.append({
                "id": pool.id,
                "name": pool.name,
                "path": pool.path,
                "pool_type": pool.pool_type,
                "max_size_bytes": pool.max_size_bytes,
                "priority": pool.priority,
                "is_default": pool.is_default,
                "is_active": pool.is_active,
                "mount_options": pool.mount_options,
                "used_bytes": used,
                "free_bytes": free,
                "recording_count": count,
                "created_at": pool.created_at,
            })

        return {
            "total_pools": len(pools),
            "total_capacity_bytes": total_cap,
            "total_used_bytes": total_used,
            "total_free_bytes": total_free,
            "pools": pool_data,
        }

    # ------------------------------------------------------------------
    # Cloud Storage Config CRUD
    # ------------------------------------------------------------------

    @staticmethod
    async def get_all_cloud_configs(db: AsyncSession) -> List[CloudStorageConfig]:
        result = await db.execute(
            select(CloudStorageConfig).order_by(CloudStorageConfig.created_at)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_cloud_config(db: AsyncSession, config_id: str) -> Optional[CloudStorageConfig]:
        result = await db.execute(
            select(CloudStorageConfig).where(CloudStorageConfig.id == config_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_cloud_config(db: AsyncSession, data) -> CloudStorageConfig:
        cfg = CloudStorageConfig(
            name=data.name,
            provider=data.provider,
            endpoint=data.endpoint,
            bucket=data.bucket,
            region=data.region,
            access_key=data.access_key,
            secret_key=data.secret_key,
            prefix=data.prefix,
            sync_enabled=data.sync_enabled,
        )
        db.add(cfg)
        await db.commit()
        await db.refresh(cfg)
        return cfg

    @staticmethod
    async def update_cloud_config(db: AsyncSession, config_id: str, data) -> Optional[CloudStorageConfig]:
        cfg = await StorageService.get_cloud_config(db, config_id)
        if not cfg:
            return None
        update = data.model_dump(exclude_unset=True)
        for k, v in update.items():
            setattr(cfg, k, v)
        await db.commit()
        await db.refresh(cfg)
        return cfg

    @staticmethod
    async def delete_cloud_config(db: AsyncSession, config_id: str) -> bool:
        cfg = await StorageService.get_cloud_config(db, config_id)
        if not cfg:
            return False
        await db.delete(cfg)
        await db.commit()
        return True

    @staticmethod
    async def test_cloud_connection(config: CloudStorageConfig) -> dict:
        """Test connectivity to cloud storage bucket."""
        try:
            import boto3
            from botocore.config import Config as BotoConfig

            kwargs = {
                "service_name": "s3",
                "region_name": config.region,
            }
            if config.endpoint:
                kwargs["endpoint_url"] = config.endpoint
            if config.access_key and config.secret_key:
                kwargs["aws_access_key_id"] = config.access_key
                kwargs["aws_secret_access_key"] = config.secret_key

            client = boto3.client(**kwargs, config=BotoConfig(connect_timeout=5, read_timeout=5))
            # Try listing with max 1 to check access
            client.list_objects_v2(Bucket=config.bucket, MaxKeys=1, Prefix=config.prefix)
            return {"success": True, "message": f"Connected to {config.bucket}"}
        except ImportError:
            return {"success": False, "message": "boto3 not installed. Run: pip install boto3"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    @staticmethod
    async def upload_recording_to_cloud(db: AsyncSession, recording_id: str, config_id: str) -> dict:
        """Upload a single recording file to cloud storage."""
        from app.recordings.models import Recording

        cfg = await StorageService.get_cloud_config(db, config_id)
        if not cfg:
            return {"success": False, "message": "Cloud config not found"}

        result = await db.execute(
            select(Recording).where(Recording.id == recording_id)
        )
        recording = result.scalar_one_or_none()
        if not recording:
            return {"success": False, "message": "Recording not found"}

        if not os.path.exists(recording.file_path):
            return {"success": False, "message": "Recording file not found on disk"}

        try:
            import boto3
            from botocore.config import Config as BotoConfig

            kwargs = {
                "service_name": "s3",
                "region_name": cfg.region,
            }
            if cfg.endpoint:
                kwargs["endpoint_url"] = cfg.endpoint
            if cfg.access_key and cfg.secret_key:
                kwargs["aws_access_key_id"] = cfg.access_key
                kwargs["aws_secret_access_key"] = cfg.secret_key

            client = boto3.client(**kwargs, config=BotoConfig(connect_timeout=10, read_timeout=60))

            filename = os.path.basename(recording.file_path)
            camera_id = recording.camera_id if hasattr(recording, "camera_id") else "unknown"
            key = f"{cfg.prefix}{camera_id}/{filename}"

            file_size = os.path.getsize(recording.file_path)
            client.upload_file(recording.file_path, cfg.bucket, key)

            logger.info(f"Uploaded recording {recording_id} to {cfg.bucket}/{key} ({file_size} bytes)")
            return {
                "success": True,
                "message": f"Uploaded to {cfg.bucket}/{key}",
                "key": key,
                "size_bytes": file_size,
            }
        except ImportError:
            return {"success": False, "message": "boto3 not installed"}
        except Exception as e:
            logger.error(f"Cloud upload failed: {e}")
            return {"success": False, "message": str(e)}

    @staticmethod
    async def get_system_disk_info() -> dict:
        """Get system disk usage information for disk explorer."""
        disks = []
        try:
            import psutil
            for part in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    disks.append({
                        "device": part.device,
                        "mountpoint": part.mountpoint,
                        "fstype": part.fstype,
                        "total_bytes": usage.total,
                        "used_bytes": usage.used,
                        "free_bytes": usage.free,
                        "percent": usage.percent,
                    })
                except PermissionError:
                    continue
        except ImportError:
            # Fallback to root
            total, used, free = shutil.disk_usage("/")
            disks.append({
                "device": "/",
                "mountpoint": "/",
                "fstype": "unknown",
                "total_bytes": total,
                "used_bytes": used,
                "free_bytes": free,
                "percent": round(used / total * 100, 1) if total else 0,
            })
        return {"disks": disks}
