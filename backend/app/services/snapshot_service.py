# =============================================================================
# Snapshot Service — On-demand JPEG capture from go2rtc.
#
# Used by:
#   - FRS enrollment ("capture from camera" flow)
#   - AI event thumbnails (bridge pulls a frame when ingesting an event
#     that has no snapshot_path)
#   - UI "instant preview" buttons on camera pages
#
# Caches the most recent frame per camera in memory for a short window
# (CACHE_TTL_SECS) so repeated requests within the window don't hammer
# go2rtc. Cache key is stream_id; bytes are JPEG payloads.
# =============================================================================

import asyncio
import logging
import time
from typing import Optional

import httpx

from app.services.go2rtc_manager import go2rtc_manager


logger = logging.getLogger(__name__)


CACHE_TTL_SECS = 2.0
DEFAULT_TIMEOUT = 5.0


class SnapshotService:
    def __init__(self) -> None:
        # stream_id -> (jpeg_bytes, fetched_at_monotonic)
        self._cache: dict[str, tuple[bytes, float]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._client: Optional[httpx.AsyncClient] = None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _get_lock(self, stream_id: str) -> asyncio.Lock:
        # One lock per stream so concurrent fetches dedupe to one go2rtc call.
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
            # Re-check cache under the lock (someone else may have fetched
            # while we were waiting)
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


# Module-level singleton — imported wherever a snapshot is needed.
snapshot_service = SnapshotService()
