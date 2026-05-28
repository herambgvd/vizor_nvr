# =============================================================================
# go2rtc Manager — stream registration, WebRTC, API client
# =============================================================================
#
# go2rtc API v1.9.x (default http://localhost:1984):
#   GET  /api/streams              → list all streams
#   PUT  /api/streams?name=ID&src= → add/update stream source
#   DELETE /api/streams?src=ID     → remove stream
#   POST /api/webrtc?src=ID        → WebRTC signalling
# =============================================================================

import logging
from typing import Optional, Dict, Any
from urllib.parse import urlparse, urlunparse, quote, unquote

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class Go2RTCManager:
    """Async client for the go2rtc API."""

    def __init__(self):
        self._base_url = settings.GO2RTC_URL
        self._rtsp_port = settings.GO2RTC_RTSP_PORT
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(base_url=self._base_url, timeout=10)
        return self._client

    # ------------------------------------------------------------------
    # Stream management
    # ------------------------------------------------------------------

    @staticmethod
    def _encode_rtsp_url(url: str) -> str:
        """Percent-encode userinfo in an RTSP URL.

        Idempotent: unquote first then re-quote so already-encoded
        URLs (e.g. password stored as Gvd%406001) don't double-encode
        to Gvd%25406001 on subsequent passes.
        """
        try:
            parsed = urlparse(url)
            if parsed.username:
                user = quote(unquote(parsed.username), safe="")
                pwd = quote(unquote(parsed.password or ""), safe="")
                host = parsed.hostname
                port = f":{parsed.port}" if parsed.port else ""
                encoded = f"{parsed.scheme}://{user}:{pwd}@{host}{port}{parsed.path}"
                if parsed.query:
                    encoded += f"?{parsed.query}"
                return encoded
        except Exception:
            pass
        return url

    async def add_stream(self, stream_id: str, source_url: str) -> bool:
        """Register a source URL with go2rtc under the given stream ID."""
        try:
            safe_url = self._encode_rtsp_url(source_url)
            # go2rtc v1.9.x API: PUT /api/streams?name=ID&src=SOURCE
            resp = await self.client.put(
                "/api/streams",
                params={"name": stream_id, "src": safe_url},
            )
            ok = resp.status_code < 400
            if ok:
                logger.info(f"go2rtc stream registered: {stream_id}")
            else:
                logger.warning(f"go2rtc add_stream failed: {resp.status_code} {resp.text}")
            return ok
        except Exception as e:
            logger.error(f"go2rtc add_stream error: {e}")
            return False

    async def remove_stream(self, stream_id: str) -> bool:
        try:
            resp = await self.client.delete("/api/streams", params={"src": stream_id})
            ok = resp.status_code < 400
            if ok:
                logger.debug(f"go2rtc stream removed: {stream_id}")
            return ok
        except Exception as e:
            logger.warning(f"go2rtc remove_stream error: {e}")
            return False

    async def list_streams(self) -> Dict[str, Any]:
        try:
            resp = await self.client.get("/api/streams")
            return resp.json() if resp.status_code == 200 else {}
        except Exception as e:
            logger.error(f"go2rtc list_streams error: {e}")
            return {}

    # ------------------------------------------------------------------
    # URL builders
    # ------------------------------------------------------------------

    def get_rtsp_output_url(self, stream_id: str) -> str:
        """Build RTSP URL from go2rtc's restream output (for FFmpeg to consume)."""
        host = self._base_url.replace("http://", "").replace("https://", "").split(":")[0]
        return f"rtsp://{host}:{self._rtsp_port}/{stream_id}"

    def get_webrtc_url(self, stream_id: str) -> str:
        return f"{self._base_url}/api/webrtc?src={stream_id}"

    def get_mse_url(self, stream_id: str) -> str:
        return f"{self._base_url}/api/ws?src={stream_id}"

    def get_snapshot_url(self, stream_id: str) -> str:
        return f"{self._base_url}/api/frame.jpeg?src={stream_id}"

    def get_mp4_url(self, stream_id: str) -> str:
        return f"{self._base_url}/api/stream.mp4?src={stream_id}"

    async def wait_for_stream_ready(self, stream_id: str, timeout: float = 8.0, interval: float = 0.5) -> bool:
        """
        Poll go2rtc until the stream has at least one active producer (RTSP pull established).
        Returns True if ready, False if timed out.
        """
        import asyncio
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                # GET /api/streams?src=ID returns stream info directly (not wrapped in dict)
                resp = await self.client.get("/api/streams", params={"src": stream_id})
                if resp.status_code == 200:
                    data = resp.json()
                    producers = data.get("producers", [])
                    if producers:
                        logger.debug(f"go2rtc stream ready: {stream_id} ({len(producers)} producer(s))")
                        return True
            except Exception:
                pass
            await asyncio.sleep(interval)
        logger.warning(f"go2rtc stream not ready after {timeout}s: {stream_id}")
        return False

    # ------------------------------------------------------------------
    # WebRTC signalling proxy
    # ------------------------------------------------------------------

    async def webrtc_signal(self, stream_id: str, sdp_offer: str) -> Optional[str]:
        """
        Proxy WebRTC SDP offer to go2rtc and return the SDP answer.
        """
        try:
            resp = await self.client.post(
                "/api/webrtc",
                params={"src": stream_id},
                content=sdp_offer,
                headers={"Content-Type": "application/sdp"},
            )
            if resp.status_code in (200, 201):
                return resp.text
            logger.warning(f"WebRTC signal failed: {resp.status_code}")
            return None
        except Exception as e:
            logger.error(f"WebRTC signal error: {e}")
            return None

    async def webrtc_signal_publish(self, stream_id: str, offer_sdp: str) -> Optional[str]:
        """
        Send a WebRTC publish (push) SDP offer to go2rtc.

        go2rtc v1.9.x accepts a push/publish offer via the same
        POST /api/webrtc endpoint but with ``mode=push`` in the query string.
        The browser SDP must include a sendonly (or sendrecv) audio m-line so
        go2rtc knows to open a backchannel toward the camera.

        Returns the SDP answer string, or None on failure.
        """
        try:
            resp = await self.client.post(
                "/api/webrtc",
                params={"src": stream_id, "mode": "push"},
                content=offer_sdp,
                headers={"Content-Type": "application/sdp"},
                timeout=15,
            )
            if resp.status_code in (200, 201):
                logger.info(f"go2rtc WebRTC publish signal OK: {stream_id}")
                return resp.text
            logger.warning(
                f"go2rtc WebRTC publish signal failed: {resp.status_code} {resp.text[:200]}"
            )
            return None
        except Exception as e:
            logger.error(f"go2rtc WebRTC publish signal error: {e}")
            return None

    async def add_stream_with_backchannel(self, stream_id: str, source_url: str) -> bool:
        """
        Register (or re-register) a stream source with ``?backchannel=1``
        appended, which tells go2rtc to negotiate a two-way audio track when
        connecting to the RTSP/ONVIF source.

        Idempotent: safe to call even if the stream is already registered.
        """
        # Append backchannel param if not already present
        sep = "&" if "?" in source_url else "?"
        if "backchannel=1" not in source_url:
            source_url = f"{source_url}{sep}backchannel=1"
        return await self.add_stream(stream_id, source_url)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def is_healthy(self) -> bool:
        try:
            resp = await self.client.get("/api/streams")
            return resp.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # ONVIF source helpers
    # ------------------------------------------------------------------

    def build_onvif_source_url(
        self, host: str, port: int = 80,
        username: str = "admin", password: str = "admin",
        subtype: int = 0,
    ) -> str:
        """Build go2rtc ONVIF source URL. subtype: 0=main, 1=sub."""
        return f"onvif://{username}:{password}@{host}:{port}?subtype={subtype}"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            logger.info("go2rtc client closed")


# Module singleton
go2rtc_manager = Go2RTCManager()
