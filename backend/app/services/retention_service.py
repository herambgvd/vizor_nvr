# =============================================================================
# Retention Service — auto-delete old recordings, enforce storage limits
# =============================================================================

import os
import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, func, delete

from app.database import async_session_maker

logger = logging.getLogger(__name__)


class RetentionService:
    """
    Periodically cleans up recordings based on:
    1. Age (retention_days): delete recordings older than N days
    2. Storage limit (retention_max_storage_gb): delete oldest when over limit
    3. Per-pool limits (StoragePool.max_size_bytes)
    4. Storage tier rules (move between pools)
    """

    def __init__(self):
        self._running = False
        self._task = None

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Retention service started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Retention service stopped")

    async def _loop(self):
        await asyncio.sleep(30)  # initial delay

        while self._running:
            try:
                await self._run_retention()
            except Exception as e:
                logger.error(f"Retention error: {e}")

            # Get interval from settings
            interval = 3600  # default 1 hour
            try:
                async with async_session_maker() as db:
                    from app.settings.service import SettingsService
                    mins = await SettingsService.get_int(db, "retention_check_interval_min", 60)
                    interval = mins * 60
            except Exception:
                pass

            await asyncio.sleep(interval)

    async def _run_retention(self):
        from app.recordings.models import Recording
        from app.settings.service import SettingsService
        from app.storage.service import StorageService

        async with async_session_maker() as db:
            config = await SettingsService.get_retention_config(db)

            if not config["enabled"]:
                return

            deleted = 0

            # 1. Age-based retention — honour per-camera override when set
            if config["days"] > 0:
                from app.cameras.models import Camera
                cameras_result = await db.execute(select(Camera))
                cameras_map = {c.id: c for c in cameras_result.scalars().all()}

                # Group cameras by their effective retention
                from collections import defaultdict
                retention_groups: dict[int, list] = defaultdict(list)
                no_camera_default = []

                for cam in cameras_map.values():
                    eff = cam.retention_days if cam.retention_days is not None else config["days"]
                    if eff > 0:
                        retention_groups[eff].append(cam.id)

                # Fetch all unlocked recordings and delete based on per-camera cutoff
                recs_result = await db.execute(
                    select(Recording).where(Recording.locked.is_(False))
                )
                for rec in recs_result.scalars().all():
                    cam = cameras_map.get(rec.camera_id) if rec.camera_id else None
                    eff_days = (
                        cam.retention_days if (cam and cam.retention_days is not None)
                        else config["days"]
                    )
                    if eff_days <= 0:
                        continue
                    cutoff = datetime.utcnow() - timedelta(days=eff_days)
                    if rec.start_time < cutoff:
                        if rec.file_path and os.path.exists(rec.file_path):
                            try:
                                os.unlink(rec.file_path)
                            except Exception as e:
                                logger.warning(f"Failed to delete {rec.file_path}: {e}")
                        await db.delete(rec)
                        deleted += 1

            # 2. Global storage limit
            max_gb = config["max_storage_gb"]
            if max_gb > 0:
                max_bytes = max_gb * 1_073_741_824
                total_size = await db.execute(
                    select(func.coalesce(func.sum(Recording.file_size), 0))
                )
                current = total_size.scalar()

                if current > max_bytes:
                    excess = current - max_bytes
                    # Delete oldest UNLOCKED recordings until under limit
                    oldest = await db.execute(
                        select(Recording)
                        .where(Recording.locked.is_(False))
                        .order_by(Recording.start_time.asc())
                    )
                    freed = 0
                    for rec in oldest.scalars().all():
                        if freed >= excess:
                            break
                        size = rec.file_size or 0
                        if rec.file_path and os.path.exists(rec.file_path):
                            try:
                                os.unlink(rec.file_path)
                                freed += size
                            except Exception:
                                pass
                        await db.delete(rec)
                        deleted += 1

            # 3. Per-pool limits
            pools = await StorageService.get_all_pools(db)
            for pool in pools:
                if pool.max_size_bytes and pool.max_size_bytes > 0:
                    used = StorageService.get_pool_used_bytes(pool.path)
                    if used > pool.max_size_bytes:
                        excess = used - pool.max_size_bytes
                        recs = await db.execute(
                            select(Recording)
                            .where(
                                Recording.storage_pool_id == pool.id,
                                Recording.locked.is_(False),
                            )
                            .order_by(Recording.start_time.asc())
                        )
                        freed = 0
                        for rec in recs.scalars().all():
                            if freed >= excess:
                                break
                            size = rec.file_size or 0
                            if rec.file_path and os.path.exists(rec.file_path):
                                try:
                                    os.unlink(rec.file_path)
                                    freed += size
                                except Exception:
                                    pass
                            await db.delete(rec)
                            deleted += 1

            # 4. Storage tier rules
            await StorageService.execute_tier_rules(db)

            # 5. Refresh token cleanup — purge revoked/expired tokens older than 7 days
            try:
                from app.auth.models import RefreshToken
                from sqlalchemy import delete as sa_delete
                token_cutoff = datetime.utcnow() - timedelta(days=7)
                await db.execute(
                    sa_delete(RefreshToken).where(
                        (RefreshToken.expires_at < token_cutoff) |
                        (RefreshToken.revoked.is_(True) & (RefreshToken.revoked_at < token_cutoff))
                    )
                )
            except Exception as _te:
                logger.debug(f"Token cleanup error: {_te}")

            # 6. Camera snapshot cleanup — retain last N days of snapshots
            try:
                from app.cameras.models import CameraSnapshot
                snap_days = await SettingsService.get_int(db, "snapshot_retention_days", 30)
                if snap_days > 0:
                    snap_cutoff = datetime.utcnow() - timedelta(days=snap_days)
                    old_snaps_result = await db.execute(
                        select(CameraSnapshot).where(CameraSnapshot.captured_at < snap_cutoff)
                    )
                    snap_deleted = 0
                    for snap in old_snaps_result.scalars().all():
                        if snap.file_path and os.path.exists(snap.file_path):
                            try:
                                os.unlink(snap.file_path)
                            except Exception:
                                pass
                        await db.delete(snap)
                        snap_deleted += 1
                    if snap_deleted:
                        logger.info(f"Retention: deleted {snap_deleted} old snapshots")
            except Exception as _se:
                logger.debug(f"Snapshot cleanup error: {_se}")

            await db.commit()

            if deleted:
                logger.info(f"Retention: deleted {deleted} recordings")


# Module singleton
retention_service = RetentionService()
