# =============================================================================
# Archive / Scheduled Backup Service
# =============================================================================
# Copies recordings from a source pool to a target NAS pool on a schedule.
# Uses rsync-style logic: copies files older than N days, skipping existing.
# =============================================================================

import asyncio
import logging
import os
import shutil
from datetime import datetime, timezone, timedelta
from typing import Optional, List

from app.database import async_session_maker
from app.config import settings

logger = logging.getLogger(__name__)


class ArchiveService:
    """Runs scheduled backup jobs for recording archival."""

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._interval = 60  # check schedules every 60 seconds

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Archive service started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Archive service stopped")

    async def _loop(self):
        while self._running:
            try:
                await self._check_schedules()
            except Exception as e:
                logger.error(f"Archive schedule check error: {e}")
            await asyncio.sleep(self._interval)

    async def _check_schedules(self):
        from app.storage.models import BackupSchedule
        from sqlalchemy import select

        async with async_session_maker() as db:
            result = await db.execute(
                select(BackupSchedule).where(BackupSchedule.is_active.is_(True))
            )
            schedules = result.scalars().all()

        for sched in schedules:
            if self._should_run(sched):
                asyncio.create_task(self._run_backup(sched.id))

    def _should_run(self, sched) -> bool:
        """Simple cron-like check: minute-level granularity."""
        try:
            parts = sched.schedule.split()
            if len(parts) != 5:
                return False
            minute_str, hour_str, day_str, month_str, dow_str = parts
            now = datetime.now(timezone.utc)

            def _match(field, current):
                if field == "*":
                    return True
                if "," in field:
                    return str(current) in field.split(",")
                if "-" in field:
                    start, end = field.split("-")
                    return int(start) <= current <= int(end)
                return int(field) == current

            return (
                _match(minute_str, now.minute)
                and _match(hour_str, now.hour)
                and _match(day_str, now.day)
                and _match(month_str, now.month)
                and _match(dow_str, now.weekday())
            )
        except Exception:
            return False

    async def _run_backup(self, schedule_id: str):
        from app.storage.models import BackupSchedule, StoragePool
        from app.recordings.models import Recording
        from sqlalchemy import select, update

        async with async_session_maker() as db:
            sched = await db.get(BackupSchedule, schedule_id)
            if not sched or not sched.is_active:
                return

            # Mark running
            sched.last_run_at = datetime.now(timezone.utc)
            sched.last_run_status = "running"
            sched.last_run_message = "Starting backup..."
            await db.commit()

            source_pool = await db.get(StoragePool, sched.source_pool_id)
            target_pool = await db.get(StoragePool, sched.target_pool_id)
            if not source_pool or not target_pool:
                sched.last_run_status = "failed"
                sched.last_run_message = "Source or target pool not found"
                await db.commit()
                return

            # Check target is mounted (for NAS pools)
            if target_pool.pool_type in ("nfs", "smb") and target_pool.nas_mount_state != "mounted":
                sched.last_run_status = "failed"
                sched.last_run_message = f"Target pool {target_pool.name} is not mounted"
                await db.commit()
                return

            cutoff = datetime.now(timezone.utc) - timedelta(days=sched.age_days)

            # Find recordings to copy
            result = await db.execute(
                select(Recording)
                .where(
                    Recording.start_time < cutoff,
                    Recording.file_path.startswith(source_pool.path),
                )
                .limit(500)
            )
            recordings = result.scalars().all()

            copied = 0
            skipped = 0
            failed = 0

            for rec in recordings:
                if not self._running:
                    break
                rel_path = os.path.relpath(rec.file_path, source_pool.path)
                dest_path = os.path.join(target_pool.path, rel_path)
                dest_dir = os.path.dirname(dest_path)

                try:
                    os.makedirs(dest_dir, exist_ok=True)
                    if os.path.exists(dest_path) and os.path.getsize(dest_path) == os.path.getsize(rec.file_path):
                        skipped += 1
                        continue
                    await asyncio.to_thread(shutil.copy2, rec.file_path, dest_path)
                    copied += 1
                except Exception as e:
                    logger.warning(f"Archive copy failed for {rec.file_path}: {e}")
                    failed += 1

            msg = f"Copied {copied}, skipped {skipped}, failed {failed} recordings"
            sched.last_run_status = "success" if failed == 0 else "failed"
            sched.last_run_message = msg
            await db.commit()
            logger.info(f"Archive job {schedule_id}: {msg}")

    async def run_backup_now(self, schedule_id: str) -> dict:
        """Manually trigger a backup schedule."""
        from app.storage.models import BackupSchedule

        async with async_session_maker() as db:
            sched = await db.get(BackupSchedule, schedule_id)
            if not sched:
                return {"error": "Schedule not found"}
            if sched.last_run_status == "running":
                return {"error": "Backup already running"}

        asyncio.create_task(self._run_backup(schedule_id))
        return {"status": "started", "schedule_id": schedule_id}


# Module singleton
archive_service = ArchiveService()
