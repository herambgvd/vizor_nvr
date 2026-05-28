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
#
# CAP ENFORCEMENT
# ───────────────
# The semaphore is the authoritative gate.  acquire() is the single choke
# point — every FFmpeg spawn MUST go through it.  The cap is read from
# settings.FFMPEG_GLOBAL_PROCESS_CAP (env: FFMPEG_GLOBAL_PROCESS_CAP,
# default 192).  Minimum 64, maximum 512 (clamped).
#
# METRICS
# ───────
# Two Prometheus gauges are updated after every acquire/release:
#   gvd_ffmpeg_active_processes   — current slots in use
#   gvd_ffmpeg_governor_cap       — configured cap (static after init)
# A counter gvd_ffmpeg_governor_rejected_total tracks refused slots.
#
# 503 BEHAVIOUR
# ─────────────
# When acquire() returns False, callers should raise:
#   HTTPException(503, detail=governor.cap_reached_detail())
# which includes a Retry-After header hint.  See cap_reached_detail().
# =============================================================================

import asyncio
import logging
import math
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


def _emit_metrics(cap: int, used: int):
    """Update Prometheus gauges (non-fatal if metrics not available)."""
    try:
        from app.core.metrics import (
            GVD_FFMPEG_ACTIVE_PROCESSES,
            GVD_FFMPEG_GOVERNOR_CAP,
        )
        GVD_FFMPEG_ACTIVE_PROCESSES.set(used)
        GVD_FFMPEG_GOVERNOR_CAP.set(cap)
    except Exception:
        pass


def _inc_rejected():
    try:
        from app.core.metrics import GVD_FFMPEG_GOVERNOR_REJECTED
        GVD_FFMPEG_GOVERNOR_REJECTED.inc()
    except Exception:
        pass


class FFmpegResourceGovernor:
    """
    Centralised semaphore for FFmpeg process creation.

    Usage::

        if not await governor.acquire(owner=camera_id, purpose="recording"):
            raise HTTPException(
                status_code=503,
                detail=governor.cap_reached_detail(),
                headers={"Retry-After": "10"},
            )
        try:
            process = await asyncio.create_subprocess_exec(...)
        finally:
            governor.release(owner=camera_id, purpose="recording")

    The semaphore is *per-process* (not per-camera).  Each spawned FFmpeg
    instance consumes one slot.  The cap defaults to 192 (~3 per camera
    for 64 channels) and can be overridden via FFMPEG_GLOBAL_PROCESS_CAP.
    """

    def __init__(self):
        self._cap: int = self._read_cap()
        self._semaphore = asyncio.Semaphore(self._cap)
        self._active: dict = {}  # (owner, purpose) → count
        self._lock = asyncio.Lock()
        # Seed static metric
        _emit_metrics(self._cap, 0)

    def _read_cap(self) -> int:
        try:
            val = int(getattr(settings, "FFMPEG_GLOBAL_PROCESS_CAP", "192") or 192)
        except (ValueError, TypeError):
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

    def cap_reached_detail(self) -> dict:
        """Return a structured detail dict for 503 responses."""
        return {
            "error": "ffmpeg_cap_reached",
            "message": (
                f"FFmpeg process cap reached ({self.used}/{self._cap}). "
                "The system is at maximum recording/processing capacity. "
                "Retry after some recordings complete or increase "
                "FFMPEG_GLOBAL_PROCESS_CAP."
            ),
            "cap": self._cap,
            "used": self.used,
        }

    async def acquire(
        self,
        owner: str,
        purpose: str,
        timeout: Optional[float] = 5.0,
    ) -> bool:
        """
        Try to acquire a slot.  Returns True if granted, False if the cap
        is reached within the timeout.

        On refusal, callers should respond with HTTP 503 + Retry-After header.
        """
        key = (owner, purpose)
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=timeout)
            async with self._lock:
                self._active[key] = self._active.get(key, 0) + 1
            _emit_metrics(self._cap, self.used)
            return True
        except asyncio.TimeoutError:
            logger.warning(
                f"[ffmpeg-gov] Cap reached ({self.used}/{self._cap}) — "
                f"refused slot for purpose={purpose} owner={owner}"
            )
            _inc_rejected()
            _emit_metrics(self._cap, self.used)
            return False

    def release(self, owner: str, purpose: str):
        """Release a previously acquired slot."""
        key = (owner, purpose)
        self._semaphore.release()

        async def _dec():
            async with self._lock:
                cnt = self._active.get(key, 1) - 1
                if cnt > 0:
                    self._active[key] = cnt
                else:
                    self._active.pop(key, None)
            _emit_metrics(self._cap, self.used)

        try:
            asyncio.get_running_loop().create_task(_dec(), name="ffmpeg_gov_dec")
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
