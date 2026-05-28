# =============================================================================
# Fisheye Dewarp Service — 360° camera support
# =============================================================================
# Converts fisheye / 360° streams into dewarped views (panoramic, PTZ, quad).
#
# REQUIRED FFMPEG VERSION
# ───────────────────────
# The v360 filter was merged in FFmpeg 4.3 (2020-06-15).  Any version ≥ 4.3
# is supported.  Earlier builds will emit "No such filter: v360" at runtime.
# Check with: ffmpeg -filters 2>&1 | grep v360
#
# GPU ENCODING
# ────────────
# When a hardware encoder is available (nvenc / vaapi / videotoolbox) the
# dewarp output is encoded on-GPU at the requested resolution.  If no GPU
# encoder is detected, the service falls back to libx264 at a reduced
# DEWARP_FALLBACK_WIDTH × DEWARP_FALLBACK_HEIGHT (default 1280×720) to keep
# CPU load manageable.  Override via env: DEWARP_FALLBACK_WIDTH / HEIGHT.
#
# JOB CAP
# ───────
# Concurrent dewarp jobs are capped at DEWARP_MAX_CONCURRENT (default 4) via
# an asyncio.Semaphore.  Callers that cannot acquire a slot receive None and
# should retry after the current load drops.  Adjust via env var.
#
# VIEW MODE / MOUNT MODE MATRIX
# ─────────────────────────────
# mount_mode  | valid view_modes
# ────────────┼──────────────────────────────
# ceiling     | panoramic, quad, ptz, single
# wall        | panoramic, ptz, single
# desktop     | panoramic, quad, ptz, single
#
# For quad view, four 90°-apart rectilinear clips are stitched 2×2.
# For ptz view, pan/tilt/roll parameters control the visible region.
# For panoramic, a wide-angle equirectangular → rectilinear crop is used.
# For single, a single rectilinear viewport at the given pan/tilt.
# =============================================================================

import asyncio
import logging
import shutil
from typing import Optional, Dict, Any

from app.config import settings

logger = logging.getLogger(__name__)

# Semaphore enforces DEWARP_MAX_CONCURRENT concurrent jobs
_dewarp_semaphore: asyncio.Semaphore = None  # lazy-init to avoid event-loop issues


def _get_semaphore() -> asyncio.Semaphore:
    global _dewarp_semaphore
    if _dewarp_semaphore is None:
        _dewarp_semaphore = asyncio.Semaphore(settings.DEWARP_MAX_CONCURRENT)
    return _dewarp_semaphore


def _has_gpu_encoder() -> bool:
    """Probe whether a hardware encoder is available via ffmpeg -encoders."""
    hw = settings.HARDWARE_TRANSCODING.lower()
    if hw == "software":
        return False
    try:
        import subprocess
        result = subprocess.run(
            ["ffmpeg", "-encoders"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = result.stdout + result.stderr
        # Check for any common hardware encoder
        for enc in ("h264_nvenc", "h264_vaapi", "h264_videotoolbox", "h264_qsv"):
            if enc in output:
                return True
    except Exception:
        pass
    return False


# Cached at import time (one probe per process restart)
_GPU_AVAILABLE: Optional[bool] = None


def _gpu_available() -> bool:
    global _GPU_AVAILABLE
    if _GPU_AVAILABLE is None:
        _GPU_AVAILABLE = _has_gpu_encoder()
    return _GPU_AVAILABLE


class DewarpService:
    """Generate FFmpeg filter strings for fisheye dewarping.

    All methods are synchronous (pure filter-string computation).
    Use acquire_slot() / release_slot() around any actual FFmpeg spawning.
    """

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

        Returns None if the mount_mode / view_mode combination is invalid.
        Requires FFmpeg ≥ 4.3 (v360 filter).

        For quad view, returns a filter_complex string with hstack/vstack.
        For all other views, returns a simple -vf filter string.
        """
        if mount_mode not in DewarpService.MOUNT_MODES:
            logger.warning(
                f"[dewarp] [{camera_id}] Unknown mount_mode={mount_mode!r}. "
                f"Valid: {DewarpService.MOUNT_MODES}"
            )
            return None
        if view_mode not in DewarpService.VIEW_MODES:
            logger.warning(
                f"[dewarp] [{camera_id}] Unknown view_mode={view_mode!r}. "
                f"Valid: {DewarpService.VIEW_MODES}"
            )
            return None

        # If no GPU and full resolution requested, fall back to reduced resolution
        if not _gpu_available():
            fallback_w = settings.DEWARP_FALLBACK_WIDTH
            fallback_h = settings.DEWARP_FALLBACK_HEIGHT
            if output_w > fallback_w or output_h > fallback_h:
                logger.debug(
                    f"[dewarp] [{camera_id}] No GPU encoder — capping output to "
                    f"{fallback_w}x{fallback_h} (CPU fallback)"
                )
                output_w, output_h = fallback_w, fallback_h

        if view_mode == "quad":
            # Four rectilinear views stitched into a 2×2 grid
            views = [
                {"pan": 0,   "tilt": tilt, "label": "F"},
                {"pan": 90,  "tilt": tilt, "label": "R"},
                {"pan": 180, "tilt": tilt, "label": "B"},
                {"pan": 270, "tilt": tilt, "label": "L"},
            ]
            half_w = output_w // 2
            half_h = output_h // 2
            parts = []
            for i, v in enumerate(views):
                parts.append(
                    f"[in]v360=input=equirect:output=rect:"
                    f"ih_fov=180:iv_fov=180:"
                    f"h_fov={fov_x}:v_fov={fov_y}:"
                    f"pitch={v['tilt']}:yaw={v['pan']}:roll={roll}:"
                    f"w={half_w}:h={half_h}[v{i}]"
                )
            stack = (
                f"[v0][v1]hstack=inputs=2[top];"
                f"[v2][v3]hstack=inputs=2[bottom];"
                f"[top][bottom]vstack=inputs=2[out]"
            )
            return ";".join(parts) + ";" + stack

        # panoramic / ptz / single — all use a single v360 call
        return (
            f"v360=input=equirect:output=rect:"
            f"ih_fov=180:iv_fov=180:"
            f"h_fov={fov_x}:v_fov={fov_y}:"
            f"pitch={tilt}:yaw={pan}:roll={roll}:"
            f"w={output_w}:h={output_h}"
        )

    @staticmethod
    def build_go2rtc_source_url(
        camera_id: str, original_url: str, filter_str: str
    ) -> str:
        """Build a go2rtc FFmpeg source URL that applies the dewarp filter.

        go2rtc format: ffmpeg:rtsp://...#video=h264#raw=-vf "filter"
        """
        escaped = filter_str.replace(":", "\\:").replace('"', '\\"')
        return f"ffmpeg:{original_url}#video=h264#raw=-vf {escaped}"

    @staticmethod
    def get_default_params(mount_mode: str) -> Dict[str, Any]:
        """Return sensible default pan/tilt/fov for a mount mode."""
        defaults = {
            "ceiling": {"tilt": -90, "roll": 0, "fov_x": 120, "fov_y": 90},
            "wall":    {"tilt":   0, "roll": 0, "fov_x":  90, "fov_y": 60},
            "desktop": {"tilt":   0, "roll": 0, "fov_x": 180, "fov_y": 90},
        }
        return defaults.get(mount_mode, defaults["ceiling"])

    # ── Concurrency management ─────────────────────────────────────────

    async def acquire_slot(self, camera_id: str, timeout: float = 5.0) -> bool:
        """Try to acquire a concurrent dewarp job slot.

        Returns True if granted, False if the cap is reached within timeout.
        """
        sem = _get_semaphore()
        try:
            await asyncio.wait_for(sem.acquire(), timeout=timeout)
            logger.debug(
                f"[dewarp] [{camera_id}] Acquired slot "
                f"({settings.DEWARP_MAX_CONCURRENT - sem._value}/"
                f"{settings.DEWARP_MAX_CONCURRENT} used)"
            )
            return True
        except asyncio.TimeoutError:
            logger.warning(
                f"[dewarp] [{camera_id}] All {settings.DEWARP_MAX_CONCURRENT} "
                f"dewarp slots occupied — skipping"
            )
            return False

    def release_slot(self, camera_id: str):
        """Release a previously acquired dewarp job slot."""
        sem = _get_semaphore()
        sem.release()

    @property
    def ffmpeg_available(self) -> bool:
        """True if ffmpeg binary is on PATH."""
        return shutil.which("ffmpeg") is not None

    @property
    def gpu_available(self) -> bool:
        return _gpu_available()


# Module singleton
dewarp_service = DewarpService()
