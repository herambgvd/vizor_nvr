# =============================================================================
# FFmpeg Snapshot helpers — test_rtsp_connection + capture_snapshot
# Extracted from ffmpeg_manager.py for maintainability.
# =============================================================================

import asyncio
import logging
import os
from typing import Optional, Tuple

from app.config import settings

logger = logging.getLogger(__name__)


async def test_rtsp_connection(rtsp_url: str) -> Tuple[bool, Optional[dict]]:
    """Test if an RTSP URL is reachable. Returns (success, stream_info)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error",
            "-rtsp_transport", "tcp",
            "-show_entries",
            "stream=width,height,r_frame_rate,codec_name,bit_rate:format=bit_rate",
            "-of", "json",
            rtsp_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)

        if proc.returncode != 0:
            return False, None

        import json
        data = json.loads(stdout.decode())
        streams = data.get("streams", [])
        video = next((s for s in streams if s.get("codec_name") in
                     ("h264", "h265", "hevc", "mpeg4", "mjpeg")), None)
        if not video:
            return True, None

        fps = None
        if video.get("r_frame_rate"):
            parts = video["r_frame_rate"].split("/")
            if len(parts) == 2 and int(parts[1]) > 0:
                fps = round(int(parts[0]) / int(parts[1]))

        bitrate = video.get("bit_rate") or (data.get("format") or {}).get("bit_rate")

        info = {
            "resolution": f"{video.get('width', '?')}x{video.get('height', '?')}",
            "fps": fps,
            "codec": video.get("codec_name"),
            "bitrate": bitrate,
        }
        return True, info

    except asyncio.TimeoutError:
        return False, None
    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        return False, None


async def capture_snapshot(rtsp_url: str, camera_id: str) -> Optional[str]:
    """Capture a single frame from the stream."""
    thumb_dir = (
        str(settings.THUMBNAIL_PATH / camera_id)
        if hasattr(settings.THUMBNAIL_PATH, "__truediv__")
        else os.path.join(str(settings.THUMBNAIL_PATH), camera_id)
    )
    os.makedirs(thumb_dir, exist_ok=True)
    path = os.path.join(thumb_dir, "latest.jpg")

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-rtsp_transport", "tcp",
            "-i", rtsp_url,
            "-frames:v", "1",
            "-q:v", "2",
            path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=15)
        if proc.returncode == 0 and os.path.exists(path):
            return path
    except asyncio.TimeoutError:
        logger.warning(f"Snapshot timeout for {camera_id}")
    except Exception as e:
        logger.warning(f"Snapshot failed for {camera_id}: {e}")
    return None
