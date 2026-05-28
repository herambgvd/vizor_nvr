# =============================================================================
# FFmpeg Resource Governor — global process cap for 64-channel NVR
# =============================================================================
# At 64 cameras, each service can spawn FFmpeg processes:
#   - Recording: 1 per camera (main stream)
#   - Sub-stream recording: 1 per camera (optional)
#   - Motion detection: 1 per camera (optional)
#   - Prebuffer: 1 per camera (optional)
# Total potential: 4 × 64 = 256 FFmpeg processes.
# This governor enforces a configurable global cap and provides
# backpressure so services can degrade gracefully instead of OOM-ing.
# =============================================================================

import asyncio
import logging
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


class FFmpegResourceGovernor:
    """
    Centralised semaphore for FFmpeg process creation.

    Usage:
        if not await governor.acquire(owner=camera_id, purpose="recording"):
            logger.warning("At global FFmpeg cap — skipping recording start")
            return False
        try:
            process = await asyncio.create_subprocess_exec(...)
        finally:
            governor.release(owner=camera_id, purpose="recording")

    The semaphore is *per-process* (not per-camera).  Each spawned FFmpeg
    instance consumes one slot.  The cap defaults to 192 (~3 per camera
    for 64 channels) and can be overridden via the
    ``ffmpeg_global_process_cap`` setting.
    """

    def __init__(self):
        self._cap: int = self._read_cap()
        self._semaphore = asyncio.Semaphore(self._cap)
        self._active: dict = {}  # (owner, purpose) → count
        self._lock = asyncio.Lock()

    def _read_cap(self) -> int:
        try:
            val = int(getattr(settings, "FFMPEG_GLOBAL_PROCESS_CAP", "192") or 192)
        except Exception:
            val = 192
        return max(64, min(512, val))

    @property
    def cap(self) -> int:
        return self._cap

    @property
    def available(self) -> int:
        return self._semaphore._value  # asyncio.Semaphore exposes this

    @property
    def used(self) -> int:
        return self._cap - self.available

    async def acquire(
        self,
        owner: str,
        purpose: str,
        timeout: Optional[float] = 5.0,
    ) -> bool:
        """
        Try to acquire a slot.  Returns True if granted, False if the cap
        is reached and we don't want to wait indefinitely.
        """
        key = (owner, purpose)
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=timeout)
            async with self._lock:
                self._active[key] = self._active.get(key, 0) + 1
            return True
        except asyncio.TimeoutError:
            logger.warning(
                f"FFmpeg governor: cap reached ({self.used}/{self._cap}). "
                f"Could not grant slot for {purpose} on camera {owner}"
            )
            return False

    def release(self, owner: str, purpose: str):
        key = (owner, purpose)
        self._semaphore.release()
        async def _dec():
            async with self._lock:
                cnt = self._active.get(key, 1) - 1
                if cnt > 0:
                    self._active[key] = cnt
                else:
                    self._active.pop(key, None)
        # Fire-and-forget bookkeeping; safe because _active is only informative
        try:
            asyncio.get_running_loop().create_task(_dec())
        except RuntimeError:
            pass

    def status(self) -> dict:
        return {
            "cap": self._cap,
            "used": self.used,
            "available": self.available,
            "active_breakdown": dict(self._active),
        }


# Module singleton
ffmpeg_governor = FFmpegResourceGovernor()
