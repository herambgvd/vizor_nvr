# =============================================================================
# Pre-Buffer Service — circular pre-recording buffer for motion-triggered cameras
# =============================================================================
#
# For cameras in "motion" recording mode, this service maintains a rolling
# buffer of short MPEG-TS segments in RAM (/tmp). When motion is detected,
# the buffered pre-event footage is flushed to the recording directory,
# followed by a post-event recording.
#
# Architecture:
#   - One lightweight FFmpeg per motion-camera writes 5-second MPEG-TS
#     segments to /tmp/gvd_prebuffer/{camera_id}/
#   - A janitor task deletes segments older than pre_buffer_seconds
#   - On motion trigger: copy valid prebuffer segments → recording dir,
#     then start post-buffer recording via ffmpeg_manager
# =============================================================================

import asyncio
import os
import shutil
import signal
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, List

from app.config import settings

logger = logging.getLogger(__name__)


class PrebufferProcess:
    """Tracks a single pre-buffer FFmpeg process."""

    __slots__ = (
        "camera_id", "process", "pid", "rtsp_url", "buffer_dir",
        "segment_duration", "pre_buffer_seconds", "stderr_task",
    )

    def __init__(
        self,
        camera_id: str,
        process: asyncio.subprocess.Process,
        rtsp_url: str,
        buffer_dir: str,
        segment_duration: int = 5,
        pre_buffer_seconds: int = 10,
    ):
        self.camera_id = camera_id
        self.process = process
        self.pid = process.pid
        self.rtsp_url = rtsp_url
        self.buffer_dir = buffer_dir
        self.segment_duration = segment_duration
        self.pre_buffer_seconds = pre_buffer_seconds
        self.stderr_task: Optional[asyncio.Task] = None


class PrebufferService:
    """
    Manages circular pre-recording buffers for motion-triggered cameras.
    """

    def __init__(self):
        self._processes: Dict[str, PrebufferProcess] = {}
        self._lock = asyncio.Lock()
        self._janitor_task: Optional[asyncio.Task] = None
        self._running = False
        self._base_dir = "/tmp/gvd_prebuffer"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        """Start the janitor task."""
        if self._running:
            return
        self._running = True
        self._janitor_task = asyncio.create_task(self._janitor_loop())
        logger.info("Prebuffer service started")

    async def stop(self):
        """Stop all prebuffer processes and janitor."""
        self._running = False
        if self._janitor_task:
            self._janitor_task.cancel()
            try:
                await self._janitor_task
            except asyncio.CancelledError:
                pass

        async with self._lock:
            procs = list(self._processes.values())
            self._processes.clear()

        for p in procs:
            await self._kill_process(p)

        logger.info("Prebuffer service stopped")

    # ------------------------------------------------------------------
    # Start / stop per-camera prebuffer
    # ------------------------------------------------------------------

    async def start_prebuffer(
        self,
        camera_id: str,
        rtsp_url: str,
        pre_buffer_seconds: int = 10,
    ) -> bool:
        """Start a circular pre-buffer for a camera."""
        if not rtsp_url:
            return False

        async with self._lock:
            # Already running?
            existing = self._processes.get(camera_id)
            if existing and existing.process.returncode is None:
                return True

            buffer_dir = os.path.join(self._base_dir, camera_id)
            os.makedirs(buffer_dir, exist_ok=True)

            # Clean old junk
            self._cleanup_dir(buffer_dir)

            seg_dur = 5  # 5-second granularity
            cmd = [
                "ffmpeg", "-hide_banner", "-y",
                "-loglevel", "info",
                "-rtsp_transport", "tcp",
                "-use_wallclock_as_timestamps", "1",
                "-i", rtsp_url,
                "-an",  # no audio in prebuffer (saves RAM/disk)
                "-c:v", "copy",
                "-f", "segment",
                "-segment_time", str(seg_dur),
                "-segment_format", "mpegts",
                "-reset_timestamps", "1",
                "-strftime", "1",
                os.path.join(buffer_dir, "%Y%m%d_%H%M%S.ts"),
            ]

            # Acquire global FFmpeg process slot
            from app.services.ffmpeg_governor import ffmpeg_governor
            if not await ffmpeg_governor.acquire(camera_id, "prebuffer"):
                logger.warning(f"[{camera_id}] Prebuffer skipped — global FFmpeg cap reached")
                return False

            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
            except Exception as e:
                ffmpeg_governor.release(camera_id, "prebuffer")
                logger.error(f"[{camera_id}] Prebuffer FFmpeg launch failed: {e}")
                return False

            pb = PrebufferProcess(
                camera_id=camera_id,
                process=proc,
                rtsp_url=rtsp_url,
                buffer_dir=buffer_dir,
                segment_duration=seg_dur,
                pre_buffer_seconds=pre_buffer_seconds,
            )
            pb.stderr_task = asyncio.create_task(self._read_stderr(pb))
            self._processes[camera_id] = pb

            logger.info(
                f"[{camera_id}] Prebuffer started ({pre_buffer_seconds}s, PID {proc.pid})"
            )
            return True

    async def stop_prebuffer(self, camera_id: str):
        """Stop prebuffer for a camera."""
        async with self._lock:
            pb = self._processes.pop(camera_id, None)
        if pb:
            await self._kill_process(pb)
            logger.info(f"[{camera_id}] Prebuffer stopped")

    # ------------------------------------------------------------------
    # Flush prebuffer to recording directory
    # ------------------------------------------------------------------

    async def flush_prebuffer(
        self,
        camera_id: str,
        recording_dir: str,
        max_age_seconds: Optional[int] = None,
    ) -> List[str]:
        """
        Copy the current circular buffer segments into the recording directory.
        Returns list of copied file paths.
        """
        pb = self._processes.get(camera_id)
        if not pb:
            return []

        buffer_dir = pb.buffer_dir
        if not os.path.exists(buffer_dir):
            return []

        max_age = max_age_seconds or pb.pre_buffer_seconds
        cutoff = time.time() - max_age
        os.makedirs(recording_dir, exist_ok=True)

        copied: List[str] = []
        try:
            entries = sorted(
                (e for e in os.scandir(buffer_dir) if e.is_file() and e.name.endswith(".ts")),
                key=lambda e: e.stat().st_mtime,
            )
            for entry in entries:
                mtime = entry.stat().st_mtime
                if mtime < cutoff:
                    continue  # too old
                # Destination uses same basename but in recording dir
                dest = os.path.join(recording_dir, entry.name.replace(".ts", "_pre.mp4"))
                # Remux TS → MP4 for consistency
                ok = await self._remux_to_mp4(entry.path, dest)
                if ok:
                    copied.append(dest)
                    # Register prebuffer segment in DB so it appears in timeline/playback
                    try:
                        from app.database import async_session_maker
                        from app.recordings.service import RecordingService
                        ts_str = entry.name.replace(".ts", "")
                        start_time = datetime.strptime(ts_str, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
                        file_size = os.path.getsize(dest)
                        async with async_session_maker() as db:
                            await RecordingService.register_segment(
                                db,
                                camera_id=camera_id,
                                file_path=dest,
                                start_time=start_time,
                                end_time=start_time,  # exact end unknown; will be updated by ffprobe
                                duration=5,  # nominal prebuffer segment duration
                                file_size=file_size,
                                stream_type="main",
                                trigger_type="motion",
                            )
                    except Exception as reg_err:
                        logger.warning(f"[{camera_id}] Failed to register prebuffer segment {dest}: {reg_err}")
        except Exception as e:
            logger.error(f"[{camera_id}] Prebuffer flush failed: {e}")

        logger.info(f"[{camera_id}] Flushed {len(copied)} prebuffer segments to {recording_dir}")
        return copied

    # ------------------------------------------------------------------
    # Post-event recording
    # ------------------------------------------------------------------

    async def start_post_recording(
        self,
        camera_id: str,
        rtsp_url: str,
        recording_dir: str,
        post_seconds: int = 30,
        recording_fps: Optional[int] = None,
    ) -> bool:
        """
        Start a timed post-event recording. Returns immediately;
        the recording auto-stops after post_seconds.
        """
        from app.services.ffmpeg_manager import ffmpeg_manager

        async def _timed_stop():
            await asyncio.sleep(post_seconds)
            await ffmpeg_manager.stop_recording(camera_id)
            logger.info(f"[{camera_id}] Post-recording auto-stopped after {post_seconds}s")

        ok, _ = await ffmpeg_manager.start_recording(
            camera_id=camera_id,
            rtsp_url=rtsp_url,
            storage_path=recording_dir,
            recording_fps=recording_fps,
            segment_duration=min(15, post_seconds),
        )
        if ok:
            asyncio.create_task(_timed_stop())
        return ok

    # ------------------------------------------------------------------
    # Janitor — delete old buffer segments
    # ------------------------------------------------------------------

    async def _janitor_loop(self):
        """Every 10 seconds, delete prebuffer segments older than the buffer window."""
        while self._running:
            try:
                await asyncio.sleep(10)
                if not self._running:
                    break
                for pb in list(self._processes.values()):
                    self._cleanup_dir(pb.buffer_dir, keep_seconds=pb.pre_buffer_seconds + 5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Prebuffer janitor error: {e}")

    @staticmethod
    def _cleanup_dir(directory: str, keep_seconds: Optional[int] = None):
        """Delete all .ts files in directory older than keep_seconds."""
        if not os.path.exists(directory):
            return
        now = time.time()
        cutoff = now - keep_seconds if keep_seconds else 0
        try:
            for entry in os.scandir(directory):
                if entry.is_file() and entry.name.endswith(".ts"):
                    if keep_seconds is None or entry.stat().st_mtime < cutoff:
                        os.remove(entry.path)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _kill_process(self, pb: PrebufferProcess):
        if pb.process.returncode is not None:
            return
        try:
            pb.process.send_signal(signal.SIGINT)
            await asyncio.wait_for(pb.process.wait(), timeout=5)
        except asyncio.TimeoutError:
            pb.process.kill()
            await pb.process.wait()
        if pb.stderr_task and not pb.stderr_task.done():
            pb.stderr_task.cancel()
        from app.services.ffmpeg_governor import ffmpeg_governor
        ffmpeg_governor.release(pb.camera_id, "prebuffer")

    async def _read_stderr(self, pb: PrebufferProcess):
        """Drain stderr to keep pipe from blocking."""
        try:
            while True:
                line = await pb.process.stderr.readline()
                if not line:
                    break
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    @staticmethod
    async def _remux_to_mp4(ts_path: str, mp4_path: str) -> bool:
        """Remux a MPEG-TS file to MP4 without re-encoding."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-hide_banner", "-y",
                "-i", ts_path,
                "-c", "copy",
                "-movflags", "+faststart",
                mp4_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            rc = await asyncio.wait_for(proc.wait(), timeout=30)
            return rc == 0 and os.path.exists(mp4_path)
        except Exception as e:
            logger.debug(f"Remux failed for {ts_path}: {e}")
            return False

    def is_running(self, camera_id: str) -> bool:
        pb = self._processes.get(camera_id)
        return pb is not None and pb.process.returncode is None


# Module singleton
prebuffer_service = PrebufferService()
