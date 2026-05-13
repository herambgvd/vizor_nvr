# =============================================================================
# Two-Way Audio Service — Intercom / Speak-back to Camera
# =============================================================================
#
# Receives audio from the frontend (WebRTC data channel or WebSocket)
# and forwards it to the camera's ONVIF AudioOutput or RTSP backchannel.
#
# Current implementation:
#   - Frontend sends PCM audio via WebSocket to /api/ws/audio/{camera_id}
#   - Backend buffers audio and forwards via FFmpeg to camera's
#     RTSP backchannel URL (if supported) or ONVIF AudioOutput.
#
# Future: Native WebRTC audio track forwarding.
# =============================================================================

import asyncio
import logging
import os
import tempfile
import time
from typing import Dict, Optional
from datetime import datetime, timezone

from app.config import settings

logger = logging.getLogger(__name__)


class TwoWayAudioSession:
    """Manages an active two-way audio session for a single camera."""

    def __init__(self, camera_id: str):
        self.camera_id = camera_id
        self.created_at = datetime.now(timezone.utc)
        self.last_packet_at = time.time()
        self._buffer: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._ffmpeg_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self, rtsp_backchannel_url: str):
        """Start FFmpeg process to stream audio to camera."""
        self._running = True
        self._ffmpeg_task = asyncio.create_task(
            self._ffmpeg_forward_loop(rtsp_backchannel_url)
        )
        logger.info(f"[{self.camera_id}] Two-way audio session started")

    async def stop(self):
        self._running = False
        if self._ffmpeg_task:
            self._ffmpeg_task.cancel()
            try:
                await self._ffmpeg_task
            except asyncio.CancelledError:
                pass
        logger.info(f"[{self.camera_id}] Two-way audio session stopped")

    async def feed_pcm(self, pcm_data: bytes):
        """Receive PCM audio data from frontend."""
        self.last_packet_at = time.time()
        try:
            self._buffer.put_nowait(pcm_data)
        except asyncio.QueueFull:
            # Drop oldest packet
            try:
                self._buffer.get_nowait()
                self._buffer.put_nowait(pcm_data)
            except asyncio.QueueEmpty:
                pass

    async def _ffmpeg_forward_loop(self, target_url: str):
        """
        Read PCM from queue and pipe to FFmpeg which encodes to G.711/u-law
        and sends to the camera's RTSP backchannel.
        """
        # Create a temporary named pipe (FIFO) for FFmpeg input
        with tempfile.TemporaryDirectory() as tmpdir:
            fifo_path = os.path.join(tmpdir, "audio_in.pcm")
            os.mkfifo(fifo_path)

            cmd = [
                "ffmpeg", "-hide_banner", "-y",
                "-f", "s16le",          # Raw PCM 16-bit little-endian
                "-ar", "8000",          # 8 kHz (standard for G.711)
                "-ac", "1",             # Mono
                "-i", fifo_path,        # Input from FIFO
                "-c:a", "pcm_mulaw",    # G.711 u-law
                "-ar", "8000",
                "-ac", "1",
                "-f", "rtsp",
                "-rtsp_transport", "tcp",
                target_url,
            ]

            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
            except Exception as e:
                logger.error(f"[{self.camera_id}] FFmpeg audio forward failed: {e}")
                return

            # Open FIFO for writing
            fifo_fd = os.open(fifo_path, os.O_WRONLY)

            try:
                while self._running:
                    try:
                        packet = await asyncio.wait_for(self._buffer.get(), timeout=0.5)
                        os.write(fifo_fd, packet)
                    except asyncio.TimeoutError:
                        # Timeout is OK — check if session expired
                        if time.time() - self.last_packet_at > 10:
                            logger.debug(f"[{self.camera_id}] Audio session idle — stopping")
                            break
                    except Exception as e:
                        logger.debug(f"[{self.camera_id}] Audio write error: {e}")
                        break
            finally:
                os.close(fifo_fd)
                try:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), timeout=3)
                except asyncio.TimeoutError:
                    proc.kill()


class TwoWayAudioService:
    """Global manager for all two-way audio sessions."""

    def __init__(self):
        self._sessions: Dict[str, TwoWayAudioSession] = {}
        self._lock = asyncio.Lock()

    async def start_session(self, camera_id: str, backchannel_url: str) -> bool:
        """Start a two-way audio session for a camera."""
        async with self._lock:
            if camera_id in self._sessions:
                await self._sessions[camera_id].stop()
                del self._sessions[camera_id]

            session = TwoWayAudioSession(camera_id)
            await session.start(backchannel_url)
            self._sessions[camera_id] = session
            return True

    async def stop_session(self, camera_id: str):
        """Stop a two-way audio session."""
        async with self._lock:
            session = self._sessions.pop(camera_id, None)
        if session:
            await session.stop()

    async def feed_audio(self, camera_id: str, pcm_data: bytes):
        """Feed PCM audio data to an active session."""
        session = self._sessions.get(camera_id)
        if session:
            await session.feed_pcm(pcm_data)

    def is_active(self, camera_id: str) -> bool:
        session = self._sessions.get(camera_id)
        return session is not None and session._running

    async def cleanup_idle(self):
        """Stop sessions idle for more than 30 seconds."""
        now = time.time()
        to_stop = []
        async with self._lock:
            for cid, sess in list(self._sessions.items()):
                if now - sess.last_packet_at > 30:
                    to_stop.append(cid)
                    del self._sessions[cid]
        for cid in to_stop:
            logger.info(f"[{cid}] Cleaning up idle two-way audio session")


# Module singleton
twoway_audio_service = TwoWayAudioService()
