# =============================================================================
# Thumbnail Pre-Generation Service (Cross-cutting X.5)
# =============================================================================
#
# Hover-scrub on the timeline used to invoke FFmpeg synchronously per hover,
# causing CPU spikes and slow first-paint. This background worker walks the
# recordings table every 60 s and pre-generates a 320-wide JPEG thumbnail at
# the midpoint of every finalized segment that doesn't have one yet.
#
# - One JPEG per recording (data/thumbnails/{camera_id}/seg_{recording_id}.jpg)
# - Skips recordings still in-flight (no end_time)
# - Skips empty / missing files
# - Bounded queue (max 8 ffmpeg jobs in flight) so a backlog doesn't starve
#   live recordings of CPU.
# =============================================================================

import asyncio
import logging
import os
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


class ThumbnailService:
    def __init__(self, interval_seconds: int = 60, concurrency: int = 4):
        self._interval = interval_seconds
        self._sem = asyncio.Semaphore(concurrency)
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            f"Thumbnail service started "
            f"(interval={self._interval}s, concurrency={self._sem._value})"
        )

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        await asyncio.sleep(30)  # let other startup tasks settle
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.error(f"thumbnail tick error: {e}")
            await asyncio.sleep(self._interval)

    async def _tick(self):
        """One pass: pick up to 50 recordings without thumbnails, generate."""
        from sqlalchemy import text
        from app.database import async_session_maker

        async with async_session_maker() as db:
            rows = (await db.execute(text("""
                SELECT id, camera_id, file_path, start_time, end_time, duration
                FROM recordings
                WHERE end_time IS NOT NULL
                  AND (file_size IS NULL OR file_size > 10240)
                ORDER BY start_time DESC
                LIMIT 200
            """))).fetchall()

        tasks = []
        for r in rows:
            thumb_path = self._thumb_path(r[1], r[0])
            if os.path.exists(thumb_path):
                continue
            if not r[2] or not os.path.exists(r[2]):
                continue
            tasks.append(asyncio.create_task(self._make_thumb(r[2], thumb_path, r[5] or 60)))
            if len(tasks) >= 50:
                break

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    def _thumb_path(camera_id: str, recording_id: str) -> str:
        d = os.path.join(settings.THUMBNAIL_PATH, camera_id)
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f"seg_{recording_id}.jpg")

    async def _make_thumb(self, source: str, dest: str, duration: int):
        async with self._sem:
            # Seek to middle of segment so the frame is representative.
            offset = max(1, duration // 2)
            try:
                proc = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-y", "-ss", str(offset), "-i", source,
                    "-frames:v", "1", "-q:v", "6", "-vf", "scale=320:-1",
                    dest,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(proc.wait(), timeout=20)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except Exception:
                    pass
            except Exception as e:
                logger.debug(f"thumb gen failed for {source}: {e}")


thumbnail_service = ThumbnailService()
