# =============================================================================
# POS / ATM Text Overlay Service
# =============================================================================
# Receives transaction text from POS/ATM devices and makes it available to
# FFmpeg drawtext filters for real-time burn-in on recordings.
#
# Two input methods:
#   1. HTTP POST /api/pos-overlay/{camera_id}  — push from POS software
#   2. TCP socket listener  — legacy serial-over-IP devices
#
# FFmpeg drawtext uses: textfile=/data/pos/cam_id.txt:reload=1
# The file is rewritten on every new transaction. FFmpeg polls it every frame.
# =============================================================================

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Dict, Optional

from app.config import settings

logger = logging.getLogger(__name__)

DATA_DIR = getattr(settings, "DATA_PATH", "/data")
POS_DIR = os.path.join(DATA_DIR, "pos_overlay")
os.makedirs(POS_DIR, exist_ok=True)


class POSOverlayService:
    """Manages POS/ATM text overlay state per camera."""

    def __init__(self):
        self._texts: Dict[str, str] = {}  # camera_id → current text
        self._tcp_server: Optional[asyncio.Server] = None

    def _file_path(self, camera_id: str) -> str:
        return os.path.join(POS_DIR, f"{camera_id}.txt")

    def set_text(self, camera_id: str, text: str):
        """Set overlay text for a camera. Writes to file for FFmpeg drawtext."""
        self._texts[camera_id] = text
        path = self._file_path(camera_id)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as e:
            logger.warning(f"[POS] Failed to write overlay file for {camera_id}: {e}")

    def clear_text(self, camera_id: str):
        """Clear overlay text for a camera."""
        self._texts.pop(camera_id, None)
        path = self._file_path(camera_id)
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as e:
            logger.warning(f"[POS] Failed to remove overlay file for {camera_id}: {e}")

    def get_text(self, camera_id: str) -> Optional[str]:
        return self._texts.get(camera_id)

    def has_overlay(self, camera_id: str) -> bool:
        return camera_id in self._texts and os.path.exists(self._file_path(camera_id))

    # ------------------------------------------------------------------
    # TCP listener for legacy POS devices (serial-over-IP)
    # ------------------------------------------------------------------

    async def start_tcp_listener(self, host: str = "0.0.0.0", port: int = 9100):
        """Start a TCP server that receives raw text lines from POS printers."""
        if self._tcp_server:
            return

        async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            peer = writer.get_extra_info("peername")
            logger.info(f"[POS] TCP client connected: {peer}")
            buffer = b""
            try:
                while True:
                    data = await reader.read(1024)
                    if not data:
                        break
                    buffer += data
                    # Split on newlines / ESC sequences common in receipt printers
                    while b"\n" in buffer or b"\x1b\x64" in buffer:  # LF or ESC d (cut)
                        idx = buffer.find(b"\n")
                        cut_idx = buffer.find(b"\x1b\x64")
                        if cut_idx >= 0 and (idx < 0 or cut_idx < idx):
                            line = buffer[:cut_idx]
                            buffer = buffer[cut_idx + 2:]
                        else:
                            line = buffer[:idx]
                            buffer = buffer[idx + 1:]
                        text = line.decode("utf-8", errors="replace").strip()
                        if text:
                            # Map by source IP → camera_id via config lookup
                            camera_id = self._resolve_camera_by_ip(peer[0])
                            if camera_id:
                                self.set_text(camera_id, text)
                                logger.debug(f"[POS] Text from {peer}: {text[:60]}")
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"[POS] TCP handler error: {e}")
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

        self._tcp_server = await asyncio.start_server(handle_client, host, port)
        logger.info(f"[POS] TCP listener started on {host}:{port}")

    async def stop_tcp_listener(self):
        if self._tcp_server:
            self._tcp_server.close()
            await self._tcp_server.wait_closed()
            self._tcp_server = None
            logger.info("[POS] TCP listener stopped")

    def _resolve_camera_by_ip(self, ip: str) -> Optional[str]:
        """Map a POS device IP to a camera_id via environment or settings."""
        # Simple env-based mapping: POS_CAM_192_168_1_50=camera-uuid
        env_key = f"POS_CAM_{ip.replace('.', '_')}"
        return os.environ.get(env_key)


# Module singleton
pos_overlay_service = POSOverlayService()
