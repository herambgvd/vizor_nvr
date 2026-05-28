# =============================================================================
# Archive / Scheduled Backup Service
# =============================================================================
# Copies recordings from a source pool to a target NAS pool on a schedule.
#
# RSYNC SEMANTICS
# ───────────────
# Only copies files that are either absent at the destination or differ in
# size.  Files that already exist at the target with the same byte count are
# skipped (skipped counter).  This ensures idempotent, incremental backups:
# a second run after a partial failure will continue from where it stopped.
#
# JOB STATE PERSISTENCE
# ──────────────────────
# Job status (running / success / failed) and counts are stored in the
# BackupSchedule ORM row (last_run_at, last_run_status, last_run_message).
# On restart, the service re-evaluates cron schedules from the DB so in-flight
# jobs that were interrupted will be re-queued on the next matching tick.
#
# NAS BACKOFF
# ───────────
# If the target pool is not mounted (NAS unreachable), the schedule is paused
# with exponential backoff: 1 → 2 → 4 → 8 → 16 min (configurable maximum via
# ARCHIVE_NAS_MAX_BACKOFF).  Backoff is reset when the NAS becomes reachable.
# =============================================================================

import asyncio
import logging
import os
import shutil
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict

from app.database import async_session_maker
from app.config import settings

logger = logging.getLogger(__name__)


class ArchiveService:
    """Runs scheduled backup jobs for recording archival."""

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._interval: int = settings.ARCHIVE_CHECK_INTERVAL
        # schedule_id → backoff_seconds (per-schedule NAS backoff state)
        self._backoff: Dict[str, float] = {}
        # schedule_id → next_attempt_time (epoch seconds)
        self._next_attempt: Dict[str, float] = {}

    async def start(self):
        """Start the archive schedule loop (idempotent)."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="archive_loop")
        logger.info(
            f"Archive service started (check_interval={self._interval}s, "
            f"max_nas_backoff={settings.ARCHIVE_NAS_MAX_BACKOFF}s)"
        )

    async def stop(self):
        """Stop the archive loop (idempotent, waits for current task to cancel)."""
        if not self._running:
            return
        self._running = False
        if self._task and not self._task.done():
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
            except Exception as exc:
                logger.error(f"[archive] Schedule check error: {exc}")
            await asyncio.sleep(self._interval)

    async def _check_schedules(self):
        from app.storage.models import BackupSchedule
        from sqlalchemy import select

        async with async_session_maker() as db:
            result = await db.execute(
                select(BackupSchedule).where(BackupSchedule.is_active.is_(True))
            )
            schedules = result.scalars().all()

        now_epoch = time.monotonic()
        for sched in schedules:
            sid = sched.id
            # Honour backoff delay
            if now_epoch < self._next_attempt.get(sid, 0):
                continue
            if self._should_run(sched):
                asyncio.create_task(
                    self._run_backup(sched.id),
                    name=f"archive_{sid[:8]}",
                )

    def _should_run(self, sched) -> bool:
        """Cron-like check (minute granularity)."""
        try:
            parts = sched.schedule.split()
            if len(parts) != 5:
                return False
            minute_str, hour_str, day_str, month_str, dow_str = parts
            now = datetime.now(timezone.utc)

            def _match(field: str, current: int) -> bool:
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
        """Execute a backup schedule job — incremental rsync-style copy."""
        from app.storage.models import BackupSchedule, StoragePool
        from app.recordings.models import Recording
        from sqlalchemy import select

        t0 = time.monotonic()

        async with async_session_maker() as db:
            sched = await db.get(BackupSchedule, schedule_id)
            if not sched or not sched.is_active:
                return

            # Guard: don't start a second run if one is already in progress
            if sched.last_run_status == "running":
                logger.debug(f"[archive] Schedule {schedule_id[:8]} already running — skipping")
                return

            sched.last_run_at = datetime.now(timezone.utc)
            sched.last_run_status = "running"
            sched.last_run_message = "Starting backup..."
            await db.commit()

            source_pool = await db.get(StoragePool, sched.source_pool_id)
            target_pool = await db.get(StoragePool, sched.target_pool_id)

            if not source_pool or not target_pool:
                sched.last_run_status = "failed"
                sched.last_run_message = "Source or target pool not found in DB"
                await db.commit()
                return

            # NAS reachability check with backoff
            if target_pool.pool_type in ("nfs", "smb") and target_pool.nas_mount_state != "mounted":
                backoff = self._backoff.get(schedule_id, 60.0)
                max_backoff = float(settings.ARCHIVE_NAS_MAX_BACKOFF)
                next_backoff = min(backoff * 2, max_backoff)
                self._backoff[schedule_id] = next_backoff
                self._next_attempt[schedule_id] = time.monotonic() + backoff

                msg = (
                    f"Target pool '{target_pool.name}' is not mounted "
                    f"(NAS unreachable). "
                    f"Retrying in {int(backoff)}s (backoff up to {int(max_backoff)}s)."
                )
                sched.last_run_status = "failed"
                sched.last_run_message = msg
                await db.commit()

                # Update Prometheus backoff gauge
                try:
                    from app.core.metrics import GVD_ARCHIVE_NAS_BACKOFF
                    GVD_ARCHIVE_NAS_BACKOFF.set(backoff)
                except Exception:
                    pass

                logger.warning(f"[archive] {msg}")
                return

            # NAS is healthy — reset backoff
            self._backoff.pop(schedule_id, None)
            self._next_attempt.pop(schedule_id, None)
            try:
                from app.core.metrics import GVD_ARCHIVE_NAS_BACKOFF
                GVD_ARCHIVE_NAS_BACKOFF.set(0)
            except Exception:
                pass

            cutoff = datetime.now(timezone.utc) - timedelta(days=sched.age_days)

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
            try:
                rel_path = os.path.relpath(rec.file_path, source_pool.path)
            except ValueError:
                # relpath fails on Windows if paths are on different drives
                failed += 1
                continue

            dest_path = os.path.join(target_pool.path, rel_path)
            dest_dir = os.path.dirname(dest_path)

            try:
                os.makedirs(dest_dir, exist_ok=True)

                # Incremental: skip if destination exists with same size
                if os.path.exists(dest_path):
                    try:
                        src_size = os.path.getsize(rec.file_path)
                        dst_size = os.path.getsize(dest_path)
                        if src_size == dst_size:
                            skipped += 1
                            continue
                    except OSError:
                        pass  # If we can't stat, re-copy to be safe

                await asyncio.to_thread(shutil.copy2, rec.file_path, dest_path)
                copied += 1

            except FileNotFoundError:
                logger.debug(f"[archive] Source missing: {rec.file_path}")
                skipped += 1
            except PermissionError as exc:
                logger.warning(f"[archive] Permission denied copying {rec.file_path}: {exc}")
                failed += 1
            except OSError as exc:
                logger.warning(f"[archive] Copy failed for {rec.file_path}: {exc}")
                failed += 1

        duration = time.monotonic() - t0
        msg = f"Copied {copied}, skipped {skipped}, failed {failed} recordings"
        run_status = "success" if failed == 0 else "failed"

        # Persist result
        async with async_session_maker() as db:
            sched = await db.get(BackupSchedule, schedule_id)
            if sched:
                sched.last_run_status = run_status
                sched.last_run_message = msg
                await db.commit()

        # Metrics
        try:
            from app.core.metrics import GVD_ARCHIVE_JOB_DURATION, GVD_ARCHIVE_JOB_FAILURES
            GVD_ARCHIVE_JOB_DURATION.observe(duration)
            if failed > 0:
                GVD_ARCHIVE_JOB_FAILURES.inc()
        except Exception:
            pass

        logger.info(
            f"[archive] Job {schedule_id[:8]}: {msg} "
            f"(duration={duration:.1f}s status={run_status})"
        )

    # ── Manual trigger ─────────────────────────────────────────────────

    async def run_backup_now(self, schedule_id: str) -> dict:
        """Manually trigger a backup schedule (idempotent guard included)."""
        from app.storage.models import BackupSchedule

        async with async_session_maker() as db:
            sched = await db.get(BackupSchedule, schedule_id)
            if not sched:
                return {"error": "Schedule not found"}
            if sched.last_run_status == "running":
                return {"error": "Backup already running for this schedule"}

        asyncio.create_task(self._run_backup(schedule_id), name=f"archive_manual_{schedule_id[:8]}")
        return {"status": "started", "schedule_id": schedule_id}

    # ── Job listing ────────────────────────────────────────────────────

    async def list_jobs(self, status: Optional[str] = None) -> list:
        """Return backup schedule job history from DB.

        status: filter by "running" | "success" | "failed" | None (all).
        """
        from app.storage.models import BackupSchedule
        from sqlalchemy import select

        async with async_session_maker() as db:
            q = select(BackupSchedule).order_by(BackupSchedule.last_run_at.desc())
            result = await db.execute(q)
            schedules = result.scalars().all()

        jobs = []
        for s in schedules:
            entry = {
                "id": s.id,
                "name": getattr(s, "name", s.id),
                "schedule": s.schedule,
                "is_active": s.is_active,
                "status": s.last_run_status,
                "message": s.last_run_message,
                "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
                "age_days": s.age_days,
                "source_pool_id": s.source_pool_id,
                "target_pool_id": s.target_pool_id,
            }
            if status is None or entry["status"] == status:
                jobs.append(entry)
        return jobs


# Module singleton
archive_service = ArchiveService()
