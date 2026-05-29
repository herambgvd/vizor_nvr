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

import asyncio
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

    async def add_stream(
        self,
        stream_id: str,
        source_url: str,
        max_retries: int = 3,
        dewarp_config: Optional[dict] = None,
    ) -> bool:
        """Register a source URL with go2rtc under the given stream ID.
        Retries on transient errors (connect errors, 503s).
        If dewarp_config is provided and enabled, pipes through FFmpeg v360.
        """
        safe_url = self._encode_rtsp_url(source_url)

        # Apply fisheye dewarp via FFmpeg if configured
        if dewarp_config and dewarp_config.get("enabled"):
            from app.services.dewarp_service import dewarp_service
            filter_str = dewarp_service.build_v360_filter(
                camera_id=stream_id,
                mount_mode=dewarp_config.get("mount_mode", "ceiling"),
                view_mode=dewarp_config.get("view_mode", "panoramic"),
                fov_x=dewarp_config.get("fov_x", 90.0),
                fov_y=dewarp_config.get("fov_y", 60.0),
                pan=dewarp_config.get("pan", 0.0),
                tilt=dewarp_config.get("tilt", 0.0),
                roll=dewarp_config.get("roll", 0.0),
            )
            if filter_str:
                safe_url = f"ffmpeg:{safe_url}#video=h264#raw=-vf {filter_str}"
                logger.info(f"[go2rtc] Dewarp filter applied for {stream_id}")

        last_err = None
        for attempt in range(1, max_retries + 1):
            try:
                # go2rtc v1.9.x API: PUT /api/streams?name=ID&src=SOURCE
                resp = await self.client.put(
                    "/api/streams",
                    params={"name": stream_id, "src": safe_url},
                )
                if resp.status_code < 400:
                    if attempt > 1:
                        logger.info(f"go2rtc stream registered on retry {attempt}: {stream_id}")
                    else:
                        logger.info(f"go2rtc stream registered: {stream_id}")
                    return True

                # go2rtc 1.9.x returns a spurious 400 ("yaml: line 1: did not
                # find expected key") on the query-param add form even though
                # the stream IS registered. Trust the registry state, not the
                # misleading status code: confirm via GET before failing.
                if await self.is_registered(stream_id):
                    logger.info(
                        f"go2rtc stream registered (ignoring spurious "
                        f"{resp.status_code} from add endpoint): {stream_id}"
                    )
                    return True

                logger.warning(f"go2rtc add_stream attempt {attempt} failed: {resp.status_code} {resp.text}")
                if resp.status_code >= 500 and attempt < max_retries:
                    await asyncio.sleep(0.5 * attempt)
                    continue
                return False
            except Exception as e:
                last_err = e
                logger.warning(f"go2rtc add_stream attempt {attempt} error: {e}")
                if attempt < max_retries:
                    await asyncio.sleep(0.5 * attempt)
        logger.error(f"go2rtc add_stream failed after {max_retries} attempts: {last_err}")
        return False

    async def is_registered(self, stream_id: str) -> bool:
        """Return True if go2rtc currently has a stream registered under
        ``stream_id``. Used to distinguish a genuine add failure from
        go2rtc 1.9.x's spurious 400 on the query-param add endpoint
        (GET /api/streams?src=ID → 200 when registered, 404 when not)."""
        try:
            resp = await self.client.get("/api/streams", params={"src": stream_id})
            return resp.status_code == 200
        except Exception:
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
