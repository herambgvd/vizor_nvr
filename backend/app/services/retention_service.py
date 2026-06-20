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

    # Max wall-clock seconds to spend scanning a single pool's on-disk size.
    # A stale NFS mount can make os.walk() hang indefinitely; this bounds it.
    _POOL_WALK_TIMEOUT = 30
    # Fire an operator alert once unlink failures reach this many in a single
    # retention cycle (deletes failing = disk fills silently otherwise).
    _UNLINK_ALERT_THRESHOLD = 5

    def __init__(self):
        self._running = False
        self._task = None
        # Count of unlink failures in the CURRENT retention cycle (reset each run).
        self._unlink_failures = 0
        # Whether we've already alerted for this cycle (avoid alert spam).
        self._unlink_alert_fired = False

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

    async def _record_unlink_failure(self, file_path: str, error: Exception):
        """Track an unlink failure and, once persistent failures cross the
        threshold in this cycle, fire the existing alert mechanisms so an
        operator knows deletes are failing (disk fills silently otherwise).

        Reuses linkage_engine.fire_event + notification_service.notify — the
        same alert path used by ffmpeg_manager / camera_monitor.
        """
        self._unlink_failures += 1
        logger.warning(f"Failed to delete {file_path}: {error}")
        if (
            self._unlink_failures >= self._UNLINK_ALERT_THRESHOLD
            and not self._unlink_alert_fired
        ):
            self._unlink_alert_fired = True
            reason = (
                f"Retention delete failures: {self._unlink_failures} recording file(s) "
                f"could not be unlinked this cycle (permission / read-only remount?). "
                f"Disk may fill — manual intervention needed."
            )
            logger.error(reason)
            try:
                from app.events.linkage_service import linkage_engine
                from app.notifications.service import notification_service
                from app.notifications.models import NotificationEvent
                await linkage_engine.fire_event(
                    camera_id=None,
                    event_type="storage_error",
                    severity="critical",
                    title="Retention delete failures",
                    description=reason,
                    metadata={"unlink_failures": self._unlink_failures},
                )
                await notification_service.notify(
                    NotificationEvent.SYSTEM_ERROR,
                    {"message": reason},
                )
            except Exception as e:
                logger.debug(f"Retention unlink-failure alert dispatch error: {e}")

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

        # Reset per-cycle unlink failure tracking (alert fires once per cycle).
        self._unlink_failures = 0
        self._unlink_alert_fired = False

        async with async_session_maker() as db:
            config = await SettingsService.get_retention_config(db)

            if not config["enabled"]:
                return

            deleted = 0

            # 0. Stale export lock cleanup — unlock recordings locked >24h ago
            try:
                stale_cutoff = datetime.utcnow() - timedelta(hours=24)
                stale_locked = await db.execute(
                    select(Recording).where(
                        Recording.locked.is_(True),
                        Recording.locked_at < stale_cutoff,
                    )
                )
                for rec in stale_locked.scalars().all():
                    rec.locked = False
                    rec.locked_by = None
                    logger.info(f"Retention: cleared stale lock on {rec.file_path}")
            except Exception as _sle:
                logger.debug(f"Stale lock cleanup error: {_sle}")

            # 1. Age-based retention — honour per-camera override when set
            if config["days"] > 0:
                from app.cameras.models import Camera
                cameras_result = await db.execute(select(Camera))
                cameras_map = {c.id: c for c in cameras_result.scalars().all()}

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
                        # TOCTOU guard: re-check lock status before unlink
                        fresh = await db.execute(
                            select(Recording).where(
                                Recording.id == rec.id,
                                Recording.locked.is_(False),
                            )
                        )
                        if fresh.scalar_one_or_none() is None:
                            continue
                        if rec.file_path and os.path.exists(rec.file_path):
                            try:
                                os.unlink(rec.file_path)
                            except Exception as e:
                                await self._record_unlink_failure(rec.file_path, e)
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
                        # TOCTOU guard
                        fresh = await db.execute(
                            select(Recording).where(
                                Recording.id == rec.id,
                                Recording.locked.is_(False),
                            )
                        )
                        if fresh.scalar_one_or_none() is None:
                            continue
                        size = rec.file_size or 0
                        if rec.file_path and os.path.exists(rec.file_path):
                            try:
                                os.unlink(rec.file_path)
                                freed += size
                            except Exception as e:
                                await self._record_unlink_failure(rec.file_path, e)
                        await db.delete(rec)
                        deleted += 1

            # 3. Per-pool limits
            pools = await StorageService.get_all_pools(db)
            for pool in pools:
                if pool.max_size_bytes and pool.max_size_bytes > 0:
                    # Guard the os.walk size computation with a timeout: a hung /
                    # stale NFS mount must not block the entire retention loop
                    # forever. On timeout, log + skip THIS pool this cycle.
                    try:
                        used = await asyncio.wait_for(
                            asyncio.to_thread(StorageService.get_pool_used_bytes, pool.path),
                            timeout=self._POOL_WALK_TIMEOUT,
                        )
                    except asyncio.TimeoutError:
                        logger.error(
                            f"Retention: pool '{pool.name}' size scan timed out after "
                            f"{self._POOL_WALK_TIMEOUT}s (stale/hung mount at {pool.path}?) "
                            f"— skipping this pool this cycle"
                        )
                        continue
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
                            # TOCTOU guard
                            fresh = await db.execute(
                                select(Recording).where(
                                    Recording.id == rec.id,
                                    Recording.locked.is_(False),
                                )
                            )
                            if fresh.scalar_one_or_none() is None:
                                continue
                            size = rec.file_size or 0
                            if rec.file_path and os.path.exists(rec.file_path):
                                try:
                                    os.unlink(rec.file_path)
                                    freed += size
                                except Exception as e:
                                    await self._record_unlink_failure(rec.file_path, e)
                            await db.delete(rec)
                            deleted += 1

            # 3b. Per-camera storage cap — prevents one high-bitrate camera from
            #     evicting other cameras' footage via the global limit. For each
            #     camera with a configured cap, sum ITS OWN recorded bytes and
            #     delete only ITS oldest segments until under the cap.
            from app.cameras.models import Camera
            capped_result = await db.execute(
                select(Camera).where(
                    Camera.max_storage_gb.isnot(None),
                    Camera.max_storage_gb > 0,
                )
            )
            for cam in capped_result.scalars().all():
                cap_bytes = cam.max_storage_gb * 1_073_741_824
                cam_total = await db.execute(
                    select(func.coalesce(func.sum(Recording.file_size), 0))
                    .where(Recording.camera_id == cam.id)
                )
                cam_used = cam_total.scalar() or 0
                if cam_used <= cap_bytes:
                    continue
                cam_excess = cam_used - cap_bytes
                cam_recs = await db.execute(
                    select(Recording)
                    .where(
                        Recording.camera_id == cam.id,
                        Recording.locked.is_(False),
                    )
                    .order_by(Recording.start_time.asc())
                )
                freed = 0
                for rec in cam_recs.scalars().all():
                    if freed >= cam_excess:
                        break
                    # TOCTOU guard — only delete this camera's own unlocked rows
                    fresh = await db.execute(
                        select(Recording).where(
                            Recording.id == rec.id,
                            Recording.camera_id == cam.id,
                            Recording.locked.is_(False),
                        )
                    )
                    if fresh.scalar_one_or_none() is None:
                        continue
                    size = rec.file_size or 0
                    if rec.file_path and os.path.exists(rec.file_path):
                        try:
                            os.unlink(rec.file_path)
                            freed += size
                        except Exception as e:
                            await self._record_unlink_failure(rec.file_path, e)
                    await db.delete(rec)
                    deleted += 1
                if freed:
                    logger.info(
                        f"Retention: camera {cam.id} over {cam.max_storage_gb}GB cap — "
                        f"freed {freed / 1_073_741_824:.2f}GB"
                    )

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
