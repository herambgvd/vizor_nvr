# =============================================================================
# VST (Video Storage Toolkit) Adapter Client
#
# NVIDIA's Video Storage Toolkit is the Metropolis-native recording engine.
# Replaces ffmpeg-based recording + MediaMTX. Provides:
#   - RTSP stream ingest with on-demand transcoding
#   - Segment-based recording (fmp4) to local FS or S3
#   - HLS playback API
#   - REST API for stream + segment management
#
# VST distribution: NVIDIA NGC enterprise catalog. Requires NGC API key
# and Metropolis SDK acceptance. Standard image path:
#   nvcr.io/nvidia/vst/vst:<version>
#
# This module is a thin async REST client that the NVR backend uses to:
#   1. Add cameras to VST when the user adds them in NVR UI
#   2. Pull segment lists for timeline scrub
#   3. Issue HLS playback URLs
#   4. Trigger snapshot generation
#
# For local dev w/o VST access, set VST_URL="" — the client returns mock
# data so the rest of the stack can be exercised end-to-end.
# =============================================================================

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import httpx


logger = logging.getLogger(__name__)


# Environment knobs
VST_URL = os.environ.get("VST_URL", "").rstrip("/")
VST_API_KEY = os.environ.get("VST_API_KEY", "")
VST_DEFAULT_SEGMENT_SECONDS = int(os.environ.get("VST_SEGMENT_SECONDS", "60"))
VST_STORAGE_BACKEND = os.environ.get("VST_STORAGE_BACKEND", "filesystem")  # filesystem | s3
VST_DEFAULT_RETENTION_DAYS = int(os.environ.get("VST_RETENTION_DAYS", "14"))


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------

@dataclass
class VSTStream:
    stream_id: str
    rtsp_url: str
    recording_enabled: bool
    segment_seconds: int
    retention_days: int
    storage_backend: str


@dataclass
class VSTSegment:
    stream_id: str
    started_at: datetime
    duration_seconds: float
    path: str
    bytes: int
    has_motion: bool = False


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class VSTClient:
    """Async REST client for NVIDIA VST.

    Mock mode (VST_URL empty) returns deterministic fake data so the
    rest of the stack can be exercised end-to-end without VST. Real mode
    forwards to the VST REST API.
    """

    def __init__(self, base_url: str = VST_URL, api_key: str = VST_API_KEY) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def mock_mode(self) -> bool:
        return not self.base_url

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=httpx.Timeout(10.0, connect=3.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── Stream management ───────────────────────────────────────────────

    async def add_stream(
        self,
        stream_id: str,
        rtsp_url: str,
        recording_enabled: bool = True,
        segment_seconds: int = VST_DEFAULT_SEGMENT_SECONDS,
        retention_days: int = VST_DEFAULT_RETENTION_DAYS,
    ) -> VSTStream:
        """Register a camera with VST. Idempotent — same stream_id replaces config."""
        if self.mock_mode:
            logger.info("[VST mock] add_stream %s -> %s", stream_id, rtsp_url)
            return VSTStream(stream_id, rtsp_url, recording_enabled,
                             segment_seconds, retention_days, VST_STORAGE_BACKEND)

        body = {
            "id": stream_id,
            "rtsp_url": rtsp_url,
            "recording": {
                "enabled": recording_enabled,
                "segment_seconds": segment_seconds,
                "retention_days": retention_days,
                "storage_backend": VST_STORAGE_BACKEND,
            },
        }
        client = await self._http()
        resp = await client.put(f"/api/v1/streams/{stream_id}", json=body)
        resp.raise_for_status()
        return VSTStream(stream_id, rtsp_url, recording_enabled,
                         segment_seconds, retention_days, VST_STORAGE_BACKEND)

    async def remove_stream(self, stream_id: str) -> None:
        if self.mock_mode:
            logger.info("[VST mock] remove_stream %s", stream_id)
            return
        client = await self._http()
        resp = await client.delete(f"/api/v1/streams/{stream_id}")
        resp.raise_for_status()

    async def get_stream(self, stream_id: str) -> Optional[VSTStream]:
        if self.mock_mode:
            return None
        client = await self._http()
        resp = await client.get(f"/api/v1/streams/{stream_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        rec = data.get("recording", {})
        return VSTStream(
            stream_id=data["id"],
            rtsp_url=data["rtsp_url"],
            recording_enabled=rec.get("enabled", False),
            segment_seconds=rec.get("segment_seconds", VST_DEFAULT_SEGMENT_SECONDS),
            retention_days=rec.get("retention_days", VST_DEFAULT_RETENTION_DAYS),
            storage_backend=rec.get("storage_backend", VST_STORAGE_BACKEND),
        )

    # ── Playback ────────────────────────────────────────────────────────

    async def list_segments(
        self,
        stream_id: str,
        start: datetime,
        end: datetime,
    ) -> list[VSTSegment]:
        if self.mock_mode:
            logger.info("[VST mock] list_segments %s [%s, %s]", stream_id, start, end)
            return []
        client = await self._http()
        resp = await client.get(
            f"/api/v1/streams/{stream_id}/segments",
            params={"start": start.isoformat(), "end": end.isoformat()},
        )
        resp.raise_for_status()
        return [
            VSTSegment(
                stream_id=stream_id,
                started_at=datetime.fromisoformat(s["started_at"]),
                duration_seconds=s["duration_seconds"],
                path=s["path"],
                bytes=s.get("bytes", 0),
                has_motion=s.get("has_motion", False),
            )
            for s in resp.json().get("segments", [])
        ]

    async def hls_playback_url(
        self, stream_id: str, start: datetime, end: datetime
    ) -> str:
        """Returns an HLS manifest URL the frontend can hand to hls.js."""
        if self.mock_mode:
            return f"about:blank?mock=true&stream={stream_id}"
        # VST exposes HLS at /api/v1/streams/{id}/hls?start=…&end=…
        return (
            f"{self.base_url}/api/v1/streams/{stream_id}/hls"
            f"?start={start.isoformat()}&end={end.isoformat()}"
        )

    async def snapshot(self, stream_id: str, at: Optional[datetime] = None) -> bytes:
        """Returns JPEG bytes for a frame at the given timestamp (latest if None)."""
        if self.mock_mode:
            return b""
        client = await self._http()
        params = {}
        if at is not None:
            params["at"] = at.isoformat()
        resp = await client.get(
            f"/api/v1/streams/{stream_id}/snapshot",
            params=params,
        )
        resp.raise_for_status()
        return resp.content

    # ── Health ─────────────────────────────────────────────────────────

    async def is_healthy(self) -> bool:
        if self.mock_mode:
            return True
        try:
            client = await self._http()
            resp = await client.get("/api/v1/health", timeout=3.0)
            return resp.status_code == 200
        except Exception:
            return False


# Singleton for backend use
_vst_singleton: Optional[VSTClient] = None


def get_vst_client() -> VSTClient:
    global _vst_singleton
    if _vst_singleton is None:
        _vst_singleton = VSTClient()
        if _vst_singleton.mock_mode:
            logger.info("VST client running in MOCK mode (VST_URL not set)")
        else:
            logger.info("VST client connecting to %s", _vst_singleton.base_url)
    return _vst_singleton
