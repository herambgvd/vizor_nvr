# =============================================================================
# Fisheye Dewarp Service — 360° camera support
# =============================================================================
# Converts fisheye / 360° streams into dewarped views (panoramic, PTZ, quad).
#
# Uses FFmpeg v360 filter for equirectangular → rectilinear conversion.
# Mount modes: ceiling, wall, desktop (affects roll/pitch/yaw defaults).
# View modes: panoramic, quad, ptz (interactive region).
#
# Integration: go2rtc streams can be piped through FFmpeg with v360 filter
# before being served to clients.  Alternatively, the filter can be applied
# at the recording level (less common — usually record raw, dewarp on playback).
#
# We apply dewarping at the LIVE STREAM level via go2rtc + FFmpeg pipeline,
# so the UI sees a normal rectilinear feed while the raw fisheye is still
# recorded for evidence integrity.
# =============================================================================

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class DewarpService:
    """Generate FFmpeg filter strings for fisheye dewarping."""

    # Valid combinations
    MOUNT_MODES = ("ceiling", "wall", "desktop")
    VIEW_MODES = ("panoramic", "quad", "ptz", "single")

    @staticmethod
    def build_v360_filter(
        camera_id: str,
        mount_mode: str = "ceiling",
        view_mode: str = "panoramic",
        fov_x: float = 90.0,
        fov_y: float = 60.0,
        pan: float = 0.0,
        tilt: float = 0.0,
        roll: float = 0.0,
        output_w: int = 1920,
        output_h: int = 1080,
    ) -> Optional[str]:
        """Build an FFmpeg v360 filter string for a dewarped view.

        Returns None if dewarp is not applicable.
        """
        if mount_mode not in DewarpService.MOUNT_MODES:
            return None
        if view_mode not in DewarpService.VIEW_MODES:
            return None

        # Input is always fisheye / equirectangular from 360° camera
        # Common 360° cameras output equirectangular (equirect) or fisheye
        # We assume equirect input and use v360 to convert to rectilinear (rect)

        base = (
            f"v360=input=equirect:output=rect:"
            f"ih_fov=180:iv_fov=180:"
            f"h_fov={fov_x}:v_fov={fov_y}:"
            f"pitch={tilt}:yaw={pan}:roll={roll}:"
            f"w={output_w}:h={output_h}"
        )

        if view_mode == "quad":
            # Four rectilinear views stitched into a 2x2 grid
            # Each quadrant sees a different direction
            views = [
                {"pan": 0,   "tilt": 0,   "label": "F"},
                {"pan": 90,  "tilt": 0,   "label": "R"},
                {"pan": 180, "tilt": 0,   "label": "B"},
                {"pan": 270, "tilt": 0,   "label": "L"},
            ]
            half_w = output_w // 2
            half_h = output_h // 2
            filters = []
            for i, v in enumerate(views):
                f = (
                    f"[in]v360=input=equirect:output=rect:"
                    f"ih_fov=180:iv_fov=180:"
                    f"h_fov={fov_x}:v_fov={fov_y}:"
                    f"pitch={v['tilt']}:yaw={v['pan']}:roll={roll}:"
                    f"w={half_w}:h={half_h}[v{i}]"
                )
                filters.append(f)
            # Stack 2x2
            stack = (
                f"[v0][v1]hstack=inputs=2[top];"
                f"[v2][v3]hstack=inputs=2[bottom];"
                f"[top][bottom]vstack=inputs=2[out]"
            )
            return ";".join(filters) + ";" + stack

        return base

    @staticmethod
    def build_go2rtc_source_url(camera_id: str, original_url: str, filter_str: str) -> str:
        """Build a go2rtc FFmpeg source URL that applies dewarp filter.

        go2rtc supports: ffmpeg:rtsp://...#video=h264#raw=-vf "filter"
        """
        # Escape filter for URL
        escaped = filter_str.replace(":", "\\:").replace("\"", "\\\"")
        return f"ffmpeg:{original_url}#video=h264#raw=-vf {escaped}"

    @staticmethod
    def get_default_params(mount_mode: str) -> Dict[str, Any]:
        """Return sensible defaults for a mount mode."""
        defaults = {
            "ceiling": {"tilt": -90, "roll": 0, "fov_x": 120, "fov_y": 90},
            "wall":    {"tilt": 0,   "roll": 0, "fov_x": 90,  "fov_y": 60},
            "desktop": {"tilt": 0,   "roll": 0, "fov_x": 180, "fov_y": 90},
        }
        return defaults.get(mount_mode, defaults["ceiling"])


# Module singleton
dewarp_service = DewarpService()
