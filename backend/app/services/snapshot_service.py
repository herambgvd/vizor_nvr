# =============================================================================
# Snapshot Service — On-demand JPEG capture + scheduled per-camera snapshots.
#
# On-demand (original):
#   Captures from go2rtc. Caches latest frame per camera for CACHE_TTL_SECS.
#
# Scheduled (new):
#   Background loop reads cameras with snapshot_config.interval_seconds > 0,
#   saves frames to /data/snapshots/<camera_id>/<YYYY-MM-DD>/<HHMMSS>.jpg.
#   Prunes older-than-retention_days files when retention_days is set.
# =============================================================================

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

from app.core.db_retry import with_db_retry
from app.services.go2rtc_manager import go2rtc_manager


logger = logging.getLogger(__name__)


CACHE_TTL_SECS = 2.0
DEFAULT_TIMEOUT = 5.0
SCHEDULED_LOOP_INTERVAL = 10  # check every 10s; actual capture rate per camera controlled by interval_seconds


def _snapshot_base_path() -> Path:
    """Return the base directory for scheduled snapshots."""
    try:
        from app.config import settings
        return Path(getattr(settings, "SNAPSHOT_PATH", settings.DATA_PATH) ) / "snapshots"
    except Exception:
        return Path("/data/snapshots")


class SnapshotService:
    def __init__(self) -> None:
        # stream_id -> (jpeg_bytes, fetched_at_monotonic)
        self._cache: dict[str, tuple[bytes, float]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._client: Optional[httpx.AsyncClient] = None

        # Scheduled snapshot state
        # camera_id -> monotonic time of last scheduled save
        self._last_scheduled: dict[str, float] = {}
        self._sched_running = False
        self._sched_task: Optional[asyncio.Task] = None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        return self._client

    async def close(self) -> None:
        self._sched_running = False
        if self._sched_task:
            self._sched_task.cancel()
            try:
                await self._sched_task
            except asyncio.CancelledError:
                pass
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _get_lock(self, stream_id: str) -> asyncio.Lock:
        lock = self._locks.get(stream_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[stream_id] = lock
        return lock

    async def get(
        self,
        stream_id: str,
        bypass_cache: bool = False,
    ) -> Optional[bytes]:
        """Returns JPEG bytes for the latest frame, or None if go2rtc has
        no current frame available (camera offline)."""
        now = time.monotonic()

        if not bypass_cache:
            cached = self._cache.get(stream_id)
            if cached and (now - cached[1]) < CACHE_TTL_SECS:
                return cached[0]

        async with self._get_lock(stream_id):
            cached = self._cache.get(stream_id)
            if cached and not bypass_cache and (now - cached[1]) < CACHE_TTL_SECS:
                return cached[0]

            url = go2rtc_manager.get_snapshot_url(stream_id)
            try:
                client = await self._http()
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.warning(
                        "go2rtc snapshot failed for %s: HTTP %d",
                        stream_id, resp.status_code,
                    )
                    return None
                jpeg = resp.content
                if not jpeg or not jpeg.startswith(b"\xff\xd8"):
                    logger.warning("go2rtc returned non-JPEG for %s", stream_id)
                    return None
                self._cache[stream_id] = (jpeg, time.monotonic())
                return jpeg
            except httpx.RequestError as e:
                logger.warning("go2rtc snapshot request error for %s: %s", stream_id, e)
                return None

    # =========================================================================
    # Scheduled snapshot loop
    # =========================================================================

    async def start_scheduler(self) -> None:
        """Start the background scheduler (called from lifespan)."""
        if self._sched_running:
            return
        self._sched_running = True
        self._sched_task = asyncio.create_task(self._scheduler_loop())
        logger.info("Scheduled snapshot service started")

    async def _scheduler_loop(self) -> None:
        await asyncio.sleep(15)  # Wait for other services to settle
        _transient_sleep = SCHEDULED_LOOP_INTERVAL
        _transient_count = 0
        while self._sched_running:
            try:
                await self._tick()
                _transient_sleep = SCHEDULED_LOOP_INTERVAL
                _transient_count = 0
            except (OperationalError, InterfaceError, DBAPIError) as e:
                _transient_count += 1
                _transient_sleep = min(_transient_sleep * 2, 120)
                if _transient_count == 1:
                    logger.warning(
                        "Snapshot scheduler: transient DB error (%s); "
                        "backing off to %.0fs poll",
                        type(e).__name__, _transient_sleep,
                    )
            except Exception as e:
                logger.error("Snapshot scheduler error: %s", e)
            await asyncio.sleep(_transient_sleep)

    async def _tick(self) -> None:
        from app.database import async_session_maker
        from app.cameras.models import Camera
        from sqlalchemy import select

        async with async_session_maker() as db:
            result = await db.execute(
                select(Camera).where(Camera.is_enabled.is_(True))
            )
            cameras = result.scalars().all()

        now = time.monotonic()
        for camera in cameras:
            cfg = camera.snapshot_config or {}
            if not cfg.get("enabled"):
                continue
            interval = cfg.get("interval_seconds", 0)
            if interval <= 0:
                continue
            last = self._last_scheduled.get(camera.id, 0.0)
            if (now - last) < interval:
                continue
            # Time to take a snapshot
            asyncio.create_task(
                self._save_snapshot(camera.id, cfg.get("retention_days"))
            )
            self._last_scheduled[camera.id] = now

    async def _save_snapshot(self, camera_id: str, retention_days: Optional[int]) -> None:
        """Fetch a JPEG from go2rtc and save it to disk."""
        jpeg = await self.get(camera_id, bypass_cache=True)
        if not jpeg:
            logger.debug("Scheduled snapshot: no frame for camera %s", camera_id)
            return

        now_utc = datetime.now(timezone.utc)
        date_str = now_utc.strftime("%Y-%m-%d")
        time_str = now_utc.strftime("%H%M%S")
        base = _snapshot_base_path() / camera_id / date_str
        base.mkdir(parents=True, exist_ok=True)
        dest = base / f"{time_str}.jpg"
        try:
            dest.write_bytes(jpeg)
            logger.debug("Saved scheduled snapshot: %s", dest)
        except OSError as e:
            logger.warning("Could not write snapshot %s: %s", dest, e)
            return

        # Pruning
        if retention_days and retention_days > 0:
            self._prune_old_snapshots(camera_id, retention_days)

    def _prune_old_snapshots(self, camera_id: str, retention_days: int) -> None:
        """Delete date-dirs older than retention_days for this camera."""
        import calendar
        cam_dir = _snapshot_base_path() / camera_id
        if not cam_dir.is_dir():
            return
        cutoff = time.time() - retention_days * 86400
        for date_dir in cam_dir.iterdir():
            if not date_dir.is_dir():
                continue
            # dir name is YYYY-MM-DD — parse as epoch
            try:
                dt = datetime.strptime(date_dir.name, "%Y-%m-%d")
                ts = calendar.timegm(dt.timetuple())
                if ts < cutoff:
                    for f in date_dir.iterdir():
                        try:
                            f.unlink()
                        except OSError:
                            pass
                    try:
                        date_dir.rmdir()
                        logger.debug("Pruned snapshot dir: %s", date_dir)
                    except OSError:
                        pass
            except ValueError:
                pass

    # =========================================================================
    # Gallery helpers (used by snapshot router)
    # =========================================================================

    def list_snapshots(
        self,
        camera_id: str,
        from_dt: Optional[datetime] = None,
        to_dt: Optional[datetime] = None,
        limit: int = 200,
    ) -> list[dict]:
        """Return list of {timestamp_iso, url, path} dicts from filesystem."""
        cam_dir = _snapshot_base_path() / camera_id
        if not cam_dir.is_dir():
            return []
        results = []
        for date_dir in sorted(cam_dir.iterdir()):
            if not date_dir.is_dir():
                continue
            try:
                date_str = date_dir.name
                datetime.strptime(date_str, "%Y-%m-%d")  # validate
            except ValueError:
                continue
            for fname in sorted(date_dir.iterdir()):
                if fname.suffix.lower() != ".jpg":
                    continue
                try:
                    ts = datetime.strptime(
                        f"{date_str} {fname.stem}", "%Y-%m-%d %H%M%S"
                    ).replace(tzinfo=timezone.utc)
                    if from_dt and ts < from_dt:
                        continue
                    if to_dt and ts > to_dt:
                        continue
                    results.append({
                        "timestamp": ts.isoformat(),
                        "url": f"/api/cameras/{camera_id}/snapshots/files/{date_str}/{fname.name}",
                        "path": str(fname),
                    })
                    if len(results) >= limit:
                        return results
                except (ValueError, OSError):
                    continue
        return results

    def get_snapshot_path(self, camera_id: str, date: str, filename: str) -> Optional[Path]:
        """Return absolute path to a snapshot file, or None if invalid/missing."""
        # Sanitise inputs — no path traversal
        if ".." in date or ".." in filename:
            return None
        p = _snapshot_base_path() / camera_id / date / filename
        if p.is_file():
            return p
        return None


# Module-level singleton — imported wherever a snapshot is needed.
snapshot_service = SnapshotService()
