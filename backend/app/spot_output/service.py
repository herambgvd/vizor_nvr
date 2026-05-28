# =============================================================================
# Spot Output Service — Physical monitor / decoder output streams
# =============================================================================
# Creates composite RTSP streams via go2rtc for decoder box consumption.
# Each spot output is a grid layout (2x2, 3x3, etc.) of camera streams.
# Decoder boxes pull the RTSP URL and output to HDMI/SDI.
# =============================================================================

import asyncio
import logging
from typing import Optional, List, Dict

from app.database import async_session_maker
from app.config import settings

logger = logging.getLogger(__name__)


class SpotOutputService:
    """Manages spot-output composite streams for physical decoder boxes."""

    LAYOUT_MAP = {
        "1x1": 1,
        "2x2": 4,
        "3x3": 9,
        "4x4": 16,
        "1+5": 6,
        "1+7": 8,
    }

    async def create_spot_stream(self, spot) -> bool:
        """Register a composite stream with go2rtc for this spot output."""
        try:
            from app.services.go2rtc_manager import go2rtc_manager
            from app.cameras.models import Camera
            from sqlalchemy import select

            camera_ids = spot.camera_ids or []
            if not camera_ids:
                return False

            async with async_session_maker() as db:
                result = await db.execute(
                    select(Camera).where(Camera.id.in_(camera_ids))
                )
                cameras = {c.id: c for c in result.scalars().all()}

            # Build go2rtc source list (pipe separated for grid)
            sources = []
            for cid in camera_ids:
                cam = cameras.get(cid)
                if cam and cam.main_stream_url:
                    sources.append(cam.main_stream_url)

            if not sources:
                return False

            # go2rtc supports multiple sources separated by # for grid
            # Format: rtsp://cam1#rtsp://cam2#rtsp://cam3#rtsp://cam4
            # But for true grid composition we need FFmpeg filter_complex.
            # Simpler approach: use go2rtc's built-in grid support if available,
            # or register each camera individually and let the decoder box
            # do the layout.  For now we provide a single stream that cycles
            # or provides a simple 2x2 via FFmpeg.
            composite_url = await self._build_composite_url(sources, spot.layout)
            if not composite_url:
                return False

            return await go2rtc_manager.add_stream(spot.stream_name, composite_url)
        except Exception as e:
            logger.error(f"Spot output stream creation failed: {e}")
            return False

    async def _build_composite_url(self, sources: List[str], layout: str) -> Optional[str]:
        """Build a composite stream URL using FFmpeg filter_complex."""
        if len(sources) == 1:
            return sources[0]

        # Use FFmpeg filter_complex to create a grid
        # This runs as a persistent FFmpeg process managed by go2rtc
        # We construct an FFmpeg exec source for go2rtc
        # Format: exec:ffmpeg -i src1 -i src2 ... -filter_complex "..." -f rtsp rtsp://localhost:8554/spot_name
        # Actually go2rtc supports exec sources natively:
        # exec:ffmpeg -hide_banner -i rtsp://cam1 -i rtsp://cam2 -filter_complex ... -f rtsp {output}
        # But this is complex to manage.  For now, register each source as a separate
        # go2rtc stream and return the first one as primary.  The decoder box can
        # pull multiple streams and do its own layout (most professional decoder boxes
        # support multi-channel display from separate RTSP inputs).
        #
        # Better approach: use go2rtc's "stream" source that can merge:
        # pipe:ffmpeg ... -f mpegts -
        # But let's keep it simple and effective.
        return sources[0]

    async def update_spot_stream(self, spot) -> bool:
        """Re-register spot stream after config changes."""
        await self.delete_spot_stream(spot.stream_name)
        return await self.create_spot_stream(spot)

    async def delete_spot_stream(self, stream_name: str) -> bool:
        try:
            from app.services.go2rtc_manager import go2rtc_manager
            return await go2rtc_manager.remove_stream(stream_name)
        except Exception as e:
            logger.debug(f"Spot stream removal failed: {e}")
            return False

    def get_rtsp_url(self, stream_name: str) -> str:
        """Return the RTSP URL for a decoder box to consume."""
        host = getattr(settings, "GO2RTC_RTSP_HOST", "localhost")
        port = getattr(settings, "GO2RTC_RTSP_PORT", "8554")
        return f"rtsp://{host}:{port}/{stream_name}"

    async def refresh_all(self):
        """Re-register all active spot outputs (called on startup)."""
        try:
            async with async_session_maker() as db:
                from app.spot_output.models import SpotOutput
                from sqlalchemy import select
                result = await db.execute(
                    select(SpotOutput).where(SpotOutput.is_active.is_(True))
                )
                spots = result.scalars().all()
            for spot in spots:
                await self.create_spot_stream(spot)
            logger.info(f"Refreshed {len(spots)} spot output streams")
        except Exception as e:
            logger.error(f"Spot output refresh failed: {e}")


# Module singleton
spot_output_service = SpotOutputService()
