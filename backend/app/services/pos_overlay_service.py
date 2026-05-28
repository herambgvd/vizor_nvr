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
#
# POS PROTOCOL (TCP listener)
# ───────────────────────────
# Text-line protocol: each transaction is a plain UTF-8 text line terminated
# by LF (\n) or CRLF (\r\n).  Additionally, ESC d (\x1b\x64) — the standard
# ESC/POS paper-cut command emitted by receipt printers — also acts as a line
# terminator.  Messages larger than POS_MAX_MESSAGE_BYTES (default 4096 bytes)
# trigger connection close to prevent memory exhaustion.
#
# LATE-BIND BUFFERING
# ───────────────────
# If a TCP client connects from an IP that has not yet been mapped to a camera,
# the last POS_BUFFER_LAST_N (default 20) messages are buffered in memory,
# keyed by source IP.  When an operator later assigns that IP to a camera
# (e.g. by setting POS_CAM_<IP>= env var), the next incoming message will
# drain the buffer to the camera's overlay file.
#
# ENV MAPPING
# ───────────
# POS_CAM_192_168_1_50=<camera-uuid>  (dots → underscores)
# =============================================================================

import asyncio
import collections
import logging
import os
from datetime import datetime, timezone
from typing import Dict, Optional, Deque

from app.config import settings

logger = logging.getLogger(__name__)

DATA_DIR: str = getattr(settings, "DATA_PATH", "/data")
POS_DIR: str = os.path.join(DATA_DIR, "pos_overlay")
os.makedirs(POS_DIR, exist_ok=True)

_MAX_BYTES: int = settings.POS_MAX_MESSAGE_BYTES
_BUFFER_N: int = settings.POS_BUFFER_LAST_N


class POSOverlayService:
    """Manages POS/ATM text overlay state per camera.

    Thread-safety: all mutations are from the asyncio event loop thread only.
    """

    def __init__(self):
        self._texts: Dict[str, str] = {}  # camera_id → current text
        self._tcp_server: Optional[asyncio.Server] = None
        # Late-bind buffer: source_ip → deque of (timestamp, text)
        self._pending: Dict[str, Deque] = {}

    # ── Per-camera text management ─────────────────────────────────────

    def _file_path(self, camera_id: str) -> str:
        return os.path.join(POS_DIR, f"{camera_id}.txt")

    def set_text(self, camera_id: str, text: str):
        """Set overlay text for a camera. Writes to file for FFmpeg drawtext."""
        self._texts[camera_id] = text
        path = self._file_path(camera_id)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as exc:
            logger.warning(f"[POS] Failed to write overlay file for {camera_id}: {exc}")

    def clear_text(self, camera_id: str):
        """Clear overlay text for a camera."""
        self._texts.pop(camera_id, None)
        path = self._file_path(camera_id)
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as exc:
            logger.warning(f"[POS] Failed to remove overlay file for {camera_id}: {exc}")

    def get_text(self, camera_id: str) -> Optional[str]:
        return self._texts.get(camera_id)

    def has_overlay(self, camera_id: str) -> bool:
        return camera_id in self._texts and os.path.exists(self._file_path(camera_id))

    def list_all(self) -> Dict[str, str]:
        """Return {camera_id: text} for all cameras with an active overlay."""
        return dict(self._texts)

    # ── Late-bind buffer ───────────────────────────────────────────────

    def _buffer_message(self, source_ip: str, text: str):
        """Buffer a message from an unmapped IP for later assignment."""
        if source_ip not in self._pending:
            self._pending[source_ip] = collections.deque(maxlen=_BUFFER_N)
        self._pending[source_ip].append(
            {"ts": datetime.now(timezone.utc).isoformat(), "text": text}
        )
        logger.debug(
            f"[POS] Buffered message from {source_ip} (no camera mapping yet). "
            f"Set POS_CAM_{source_ip.replace('.', '_')}=<camera_id> to assign."
        )

    def get_pending_buffer(self, source_ip: str) -> list:
        """Return buffered messages for an unmapped source IP."""
        return list(self._pending.get(source_ip, []))

    def flush_pending(self, source_ip: str, camera_id: str):
        """Drain the pending buffer for source_ip to camera_id's overlay file."""
        messages = self._pending.pop(source_ip, [])
        for entry in messages:
            self.set_text(camera_id, entry["text"])
        if messages:
            logger.info(
                f"[POS] Flushed {len(messages)} buffered messages from "
                f"{source_ip} to camera {camera_id}"
            )

    # ── TCP listener ───────────────────────────────────────────────────

    async def start_tcp_listener(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
    ):
        """Start the TCP server for legacy POS serial-over-IP devices (idempotent)."""
        if self._tcp_server is not None:
            logger.debug("[POS] TCP listener already running — start is a no-op")
            return

        _host = host or settings.POS_OVERLAY_HOST
        _port = port or settings.POS_OVERLAY_PORT

        async def handle_client(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ):
            peer = writer.get_extra_info("peername")
            peer_ip = peer[0] if peer else "unknown"
            logger.info(f"[POS] TCP client connected: {peer_ip}:{peer[1] if peer else '?'}")
            buffer = b""
            total_received = 0

            try:
                while True:
                    chunk = await reader.read(1024)
                    if not chunk:
                        break

                    total_received += len(chunk)
                    if total_received > _MAX_BYTES:
                        logger.warning(
                            f"[POS] Client {peer_ip} exceeded max message size "
                            f"({_MAX_BYTES} bytes) — closing connection"
                        )
                        break

                    buffer += chunk
                    # Process lines: split on LF or ESC d (paper cut)
                    while b"\n" in buffer or b"\x1b\x64" in buffer:
                        idx_lf = buffer.find(b"\n")
                        idx_cut = buffer.find(b"\x1b\x64")

                        if idx_cut >= 0 and (idx_lf < 0 or idx_cut < idx_lf):
                            line, buffer = buffer[:idx_cut], buffer[idx_cut + 2:]
                        else:
                            line, buffer = buffer[:idx_lf], buffer[idx_lf + 1:]

                        # Strip CR if CRLF
                        line = line.rstrip(b"\r")
                        text = line.decode("utf-8", errors="replace").strip()
                        if not text:
                            continue

                        camera_id = self._resolve_camera_by_ip(peer_ip)
                        if camera_id:
                            # Drain any buffered messages first
                            if peer_ip in self._pending:
                                self.flush_pending(peer_ip, camera_id)
                            self.set_text(camera_id, text)
                            logger.debug(f"[POS] [{camera_id}] from {peer_ip}: {text[:60]}")
                        else:
                            self._buffer_message(peer_ip, text)

                        # Reset per-message counter (only guard oversized single chunks)
                        total_received = 0

            except asyncio.CancelledError:
                pass
            except ConnectionResetError:
                logger.debug(f"[POS] Client {peer_ip} disconnected (reset)")
            except Exception as exc:
                logger.warning(f"[POS] TCP handler error from {peer_ip}: {exc}")
            finally:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass

        try:
            self._tcp_server = await asyncio.start_server(handle_client, _host, _port)
            logger.info(f"[POS] TCP listener started on {_host}:{_port}")
        except OSError as exc:
            logger.error(
                f"[POS] Failed to start TCP listener on {_host}:{_port}: {exc}. "
                f"Change POS_OVERLAY_PORT env var if port is in use."
            )
            self._tcp_server = None

    async def stop_tcp_listener(self):
        """Stop the TCP listener (idempotent)."""
        if self._tcp_server is None:
            return
        self._tcp_server.close()
        try:
            await self._tcp_server.wait_closed()
        except Exception:
            pass
        self._tcp_server = None
        logger.info("[POS] TCP listener stopped")

    def _resolve_camera_by_ip(self, ip: str) -> Optional[str]:
        """Map a POS device IP to a camera_id via environment variable.

        Convention: POS_CAM_<IP_WITH_UNDERSCORES>=<camera-uuid>
        Example:    POS_CAM_192_168_1_50=3a4f9d2c-...
        """
        env_key = f"POS_CAM_{ip.replace('.', '_')}"
        return os.environ.get(env_key)


# Module singleton
pos_overlay_service = POSOverlayService()
