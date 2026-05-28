# =============================================================================
# FFmpeg Manager — process lifecycle, segment tracking, recovery, snapshots
# =============================================================================
#
# Each recording camera gets an FFmpeg process:
#   ffmpeg -rtsp_transport tcp -i <rtsp_url>
#          -c copy -f segment -segment_time <duration>
#          -segment_format mp4 -reset_timestamps 1
#          -strftime 1 "<storage>/%Y%m%d_%H%M%S.mp4"
#
# The manager tracks:
#   - Active processes by camera_id
#   - Segment completions (detected via filesystem watch or log parsing)
#   - Process health (restart on crash)
# =============================================================================

import asyncio
import os
import re
import shutil
import signal
import logging
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple, List

from app.config import settings

logger = logging.getLogger(__name__)


class FFmpegProcess:
    __slots__ = (
        "camera_id", "pid", "process", "rtsp_url", "storage_path",
        "started_at", "segment_duration", "recording_fps", "last_health",
        "restart_count", "stderr_task",
        # Failover
        "main_stream_url", "sub_stream_url", "failover_active",
        # Privacy masks for re-encoding
        "privacy_masks",
        # Track the segment currently being written
        "current_segment",
    )

    def __init__(self, camera_id: str, process: asyncio.subprocess.Process,
                 rtsp_url: str, storage_path: str, segment_duration: int,
                 recording_fps: Optional[int],
                 sub_stream_url: Optional[str] = None,
                 privacy_masks: Optional[list] = None,
                 pos_overlay_config: Optional[dict] = None):
        self.camera_id = camera_id
        self.process = process
        self.pid = process.pid
        self.rtsp_url = rtsp_url
        self.main_stream_url = rtsp_url  # always keep original main URL
        self.sub_stream_url = sub_stream_url
        self.failover_active = False     # True when recording sub stream
        self.storage_path = storage_path
        self.segment_duration = segment_duration
        self.recording_fps = recording_fps
        self.privacy_masks = privacy_masks
        self.pos_overlay_config = pos_overlay_config
        self.started_at = datetime.now(timezone.utc)
        self.last_health = time.time()
        self.restart_count = 0
        self.current_segment: Optional[str] = None
        self.stderr_task: Optional[asyncio.Task] = None


class FFmpegManager:
    """Manages FFmpeg recording processes for all cameras."""

    def __init__(self):
        self._processes: Dict[str, FFmpegProcess] = {}
        self._stopped: set = set()  # camera_ids explicitly stopped — blocks auto_restart
        self._segment_duration: int = settings.DEFAULT_SEGMENT_DURATION
        self._lock = asyncio.Lock()
        self._shutting_down: bool = False  # set during cleanup() to block auto_restart for all
        # Sliding 60-second restart window per camera (deque of unix timestamps).
        # If 3+ restarts land inside this window, camera is marked failed and an
        # operator alert fires instead of restarting again.
        self._restart_history: Dict[str, list] = {}
        self._failed_cameras: set = set()  # camera_ids that hit the restart-storm limit
        self._watchdog_task: Optional[asyncio.Task] = None
        # Watchdog polls every WATCHDOG_INTERVAL seconds. Stall = process alive
        # but no new segment opened in STALL_FACTOR * segment_duration seconds.
        self._watchdog_interval: int = 5
        self._stall_factor: float = 4.0
        self._restart_window: float = 60.0
        self._restart_storm_limit: int = 3

    @property
    def active_count(self) -> int:
        return len(self._processes)

    def is_recording(self, camera_id: str) -> bool:
        proc = self._processes.get(camera_id)
        if proc and proc.process.returncode is None:
            return True
        return False

    def get_active_cameras(self) -> List[str]:
        return [cid for cid, p in self._processes.items() if p.process.returncode is None]

    # ------------------------------------------------------------------
    # Start / stop recording
    # ------------------------------------------------------------------

    async def start_recording(
        self,
        camera_id: str,
        rtsp_url: str,
        storage_path: str,
        recording_fps: Optional[int] = None,
        segment_duration: Optional[int] = None,
        sub_stream_url: Optional[str] = None,
        privacy_masks: Optional[list] = None,
        pos_overlay_config: Optional[dict] = None,
    ) -> Tuple[bool, str]:
        """Start FFmpeg recording for a camera. Returns (success, message)."""
        self._stopped.discard(camera_id)
        # Operator-initiated start clears watchdog state so a previously failed
        # camera can recover after the underlying issue is fixed.
        self._failed_cameras.discard(camera_id)
        self._restart_history.pop(camera_id, None)
        async with self._lock:
            if camera_id in self._processes:
                existing = self._processes[camera_id]
                if existing.process.returncode is None:
                    return True, "Already recording"
                # Dead process → clean up
                del self._processes[camera_id]

            os.makedirs(storage_path, exist_ok=True)

            # Pre-flight disk space check: ensure at least 2 segments can fit
            # (estimates 8 Mbps = 1 MB/s as a safe conservative bitrate)
            seg_dur = segment_duration or self._segment_duration
            try:
                required_bytes = seg_dur * 2 * 1_000_000  # ~2 segments @ 1 MB/s
                disk = shutil.disk_usage(storage_path)
                if disk.free < required_bytes:
                    logger.error(
                        f"[{camera_id}] Insufficient disk space: {disk.free} bytes free, "
                        f"{required_bytes} required"
                    )
                    return False, "Insufficient disk space"
            except Exception:
                pass  # If we can't check, proceed anyway

            # Build command
            cmd = self._build_ffmpeg_cmd(
                rtsp_url, storage_path, seg_dur, recording_fps,
                privacy_masks=privacy_masks,
                pos_overlay_config=pos_overlay_config,
            )
            logger.info(f"[{camera_id}] Starting FFmpeg: {' '.join(cmd)}")

            # Acquire global FFmpeg process slot
            from app.services.ffmpeg_governor import ffmpeg_governor
            if not await ffmpeg_governor.acquire(camera_id, "recording"):
                return False, "Global FFmpeg process cap reached — cannot start recording"

            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
            except Exception as e:
                ffmpeg_governor.release(camera_id, "recording")
                logger.error(f"[{camera_id}] FFmpeg launch failed: {e}")
                return False, str(e)

            ff = FFmpegProcess(
                camera_id, proc, rtsp_url, storage_path, seg_dur, recording_fps,
                sub_stream_url=sub_stream_url,
                privacy_masks=privacy_masks,
                pos_overlay_config=pos_overlay_config,
            )
            ff.stderr_task = asyncio.create_task(self._read_stderr(ff))
            self._processes[camera_id] = ff

            logger.info(f"[{camera_id}] FFmpeg started (PID {proc.pid})")
            return True, storage_path

    async def stop_recording(self, camera_id: str) -> bool:
        self._stopped.add(camera_id)
        async with self._lock:
            ff = self._processes.pop(camera_id, None)
            if not ff:
                return False
            return await self._kill_process(ff)

    async def _kill_process(self, ff: FFmpegProcess, graceful: bool = True) -> bool:
        # Release global FFmpeg process slot
        from app.services.ffmpeg_governor import ffmpeg_governor
        ffmpeg_governor.release(ff.camera_id, "recording")
        """Stop an FFmpeg process.

        graceful=True (default): send SIGINT so FFmpeg flushes the moov atom
        of the current MP4 segment before exiting — prevents file corruption
        on SIGTERM mid-segment. Falls back to SIGTERM then SIGKILL on timeout.
        Awaits the stderr reader so the final segment is registered in DB.
        """
        if ff.process.returncode is not None:
            # Still drain stderr reader if it's pending so any in-flight
            # _on_segment_complete writes finish before we return.
            if ff.stderr_task and not ff.stderr_task.done():
                try:
                    await asyncio.wait_for(ff.stderr_task, timeout=10)
                except asyncio.TimeoutError:
                    ff.stderr_task.cancel()
            return True

        # Graceful budget = 2x segment_duration + 5s buffer for moov flush,
        # capped at 60s to keep shutdown bounded.
        graceful_timeout = min(60, max(15, ff.segment_duration * 2 + 5))

        try:
            if graceful:
                try:
                    ff.process.send_signal(signal.SIGINT)
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(ff.process.wait(), timeout=graceful_timeout)
                    logger.info(f"[{ff.camera_id}] FFmpeg stopped gracefully (PID {ff.pid})")
                except asyncio.TimeoutError:
                    logger.warning(
                        f"[{ff.camera_id}] FFmpeg did not finalize within {graceful_timeout}s, "
                        f"escalating to SIGTERM"
                    )
                    ff.process.terminate()
                    try:
                        await asyncio.wait_for(ff.process.wait(), timeout=10)
                    except asyncio.TimeoutError:
                        ff.process.kill()
                        await ff.process.wait()
                    logger.info(f"[{ff.camera_id}] FFmpeg force-killed (PID {ff.pid})")
            else:
                ff.process.terminate()
                try:
                    await asyncio.wait_for(ff.process.wait(), timeout=10)
                except asyncio.TimeoutError:
                    ff.process.kill()
                    await ff.process.wait()
                logger.info(f"[{ff.camera_id}] FFmpeg stopped (PID {ff.pid})")
        except Exception as e:
            logger.error(f"[{ff.camera_id}] Error stopping FFmpeg: {e}")

        # Wait for stderr reader to finalize last segment in DB.
        # Don't cancel — let _on_segment_complete write the partial segment.
        if ff.stderr_task and not ff.stderr_task.done():
            try:
                await asyncio.wait_for(ff.stderr_task, timeout=15)
            except asyncio.TimeoutError:
                logger.warning(
                    f"[{ff.camera_id}] stderr reader did not finish in 15s — cancelling"
                )
                ff.stderr_task.cancel()
        return True

    # ------------------------------------------------------------------
    # Build FFmpeg command
    # ------------------------------------------------------------------

    # ── Hardware acceleration ─────────────────────────────────────────
    _hwaccel_choice: Optional[str] = None   # memoized one-shot detection

    @classmethod
    def _detect_hwaccel(cls) -> Optional[str]:
        """Probe FFmpeg encoders once. Returns the codec name to use when
        re-encoding (privacy mask / fps re-encode) or None for libx264.
        Order: explicit env var → NVENC → VAAPI → VideoToolbox → none."""
        if cls._hwaccel_choice is not None:
            return cls._hwaccel_choice or None
        forced = (getattr(settings, "HARDWARE_TRANSCODING", "auto") or "auto").lower()
        if forced in ("software", "libx264", "off"):
            cls._hwaccel_choice = ""
            return None
        try:
            import subprocess
            out = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                capture_output=True, timeout=5, text=True,
            ).stdout
        except Exception:
            cls._hwaccel_choice = ""
            return None

        def has(name: str) -> bool:
            return f" {name} " in out or f" {name}\n" in out

        candidates = {
            "nvenc": "h264_nvenc",
            "vaapi": "h264_vaapi",
            "videotoolbox": "h264_videotoolbox",
        }
        if forced in candidates and has(candidates[forced]):
            cls._hwaccel_choice = candidates[forced]
        else:
            for c in ("nvenc", "vaapi", "videotoolbox"):
                if has(candidates[c]):
                    cls._hwaccel_choice = candidates[c]
                    break
            else:
                cls._hwaccel_choice = ""
        if cls._hwaccel_choice:
            logger.info(f"FFmpeg hardware encoder selected: {cls._hwaccel_choice}")
        return cls._hwaccel_choice or None

    @staticmethod
    def _build_ffmpeg_cmd(
        rtsp_url: str, storage_path: str,
        segment_duration: int, recording_fps: Optional[int],
        privacy_masks: Optional[list] = None,
        pos_overlay_config: Optional[dict] = None,
    ) -> List[str]:
        cmd = [
            "ffmpeg", "-hide_banner",
            "-loglevel", "info",
            "-rtsp_transport", "tcp",
            "-use_wallclock_as_timestamps", "1",
            "-i", rtsp_url,
        ]

        if recording_fps and recording_fps > 0:
            cmd.extend(["-r", str(recording_fps)])

        # Apply privacy masks as drawbox filters (black rectangles)
        # Masks use normalised coords (0.0-1.0); FFmpeg drawbox uses iw/ih
        vf_parts = []
        if privacy_masks:
            for mask in privacy_masks:
                x = mask.get("x", 0)
                y = mask.get("y", 0)
                w = mask.get("width", 0)
                h = mask.get("height", 0)
                vf_parts.append(
                    f"drawbox=x=trunc(iw*{x}):y=trunc(ih*{y}):w=trunc(iw*{w}):h=trunc(ih*{h})"
                    f":color=black:t=fill"
                )

        # POS / ATM text overlay
        if pos_overlay_config and pos_overlay_config.get("enabled"):
            from app.services.pos_overlay_service import pos_overlay_service
            text_file = pos_overlay_service._file_path(
                pos_overlay_config.get("camera_id", "unknown")
            )
            style = pos_overlay_config.get("text_style", "fontsize=24:fontcolor=white@0.9:box=1:boxcolor=black@0.5")
            position = pos_overlay_config.get("position", "x=10:y=10")
            if os.path.exists(text_file):
                vf_parts.append(
                    f"drawtext=textfile={text_file}:reload=1:{style}:{position}"
                )

        # Append milliseconds to avoid overwriting if clock jumps backward
        output_pattern = os.path.join(storage_path, "%Y%m%d_%H%M%S_%f.mp4")

        if vf_parts:
            cmd.extend(["-vf", ",".join(vf_parts)])
            from app.services.hwaccel_probe import pick_encoder
            cmd.extend(pick_encoder("h264"))
        else:
            cmd.extend(["-c:v", "copy"])

        # Audio: MP4 doesn't support pcm_mulaw/pcm_alaw (G.711).
        # Use AAC transcode as safe default for MP4 container.
        cmd.extend(["-c:a", "aac", "-b:a", "64k"])

        cmd.extend([
            "-f", "segment",
            "-segment_time", str(segment_duration),
            "-segment_format", "mp4",
            "-segment_atclocktime", "1",
            "-reset_timestamps", "1",
            "-strftime", "1",
            output_pattern,
        ])
        return cmd

    # ------------------------------------------------------------------
    # Stderr reader — detect segment completions + errors
    # ------------------------------------------------------------------

    async def _read_stderr(self, ff: FFmpegProcess):
        """Read FFmpeg stderr to detect segment completions and errors."""
        try:
            while True:
                try:
                    line = await ff.process.stderr.readline()
                except asyncio.LimitOverrunError as e:
                    # Line exceeds buffer limit (64KB) - skip it and consume the rest
                    logger.debug(f"[{ff.camera_id}] Skipping oversized FFmpeg output line")
                    await ff.process.stderr.read(e.consumed)
                    continue
                
                if not line:
                    break
                text = line.decode(errors="replace").strip()
                if not text:
                    continue

                # Detect segment output:
                # "Opening 'X.mp4'" means FFmpeg is STARTING to write X.
                # The PREVIOUS segment is now complete.
                if "Opening '" in text and ".mp4'" in text:
                    m = re.search(r"Opening '(.+\.mp4)'", text)
                    if m:
                        new_segment = m.group(1)
                        # Register the PREVIOUS segment (now finalized)
                        if ff.current_segment:
                            task = asyncio.create_task(
                                self._on_segment_complete(ff.camera_id, ff.current_segment)
                            )
                            # Shield from cancellation so DB write completes
                            asyncio.shield(task)
                        ff.current_segment = new_segment
                    ff.last_health = time.time()

                # Log errors
                if any(w in text.lower() for w in ("error", "fatal", "broken pipe", "connection refused")):
                    logger.warning(f"[{ff.camera_id}] FFmpeg: {text}")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[{ff.camera_id}] stderr reader error: {e}")

        # Process ended — register the last segment that was being written
        # Only register if the file is non-empty (SIGKILL mid-segment = corrupt)
        if ff.current_segment:
            try:
                if os.path.exists(ff.current_segment) and os.path.getsize(ff.current_segment) >= 10240:
                    await self._on_segment_complete(ff.camera_id, ff.current_segment)
            except OSError:
                pass
            ff.current_segment = None

        rc = ff.process.returncode
        # Restart on ANY unexpected exit (rc==0 included — RTSP server closing
        # the connection cleanly still leaves the camera offline). Only skip
        # when the camera was explicitly stopped or the manager is shutting down.
        if (
            rc is not None
            and ff.camera_id in self._processes
            and ff.camera_id not in self._stopped
            and not self._shutting_down
        ):
            logger.warning(f"[{ff.camera_id}] FFmpeg exited with code {rc}")
            if settings.FFMPEG_RECOVERY_ENABLED:
                asyncio.create_task(self._auto_restart(ff))

    async def _on_segment_complete(self, camera_id: str, segment_path: str):
        """Register a completed segment in the database."""
        try:
            # Give FFmpeg a moment to fully flush the file to disk
            await asyncio.sleep(0.2)
            
            if not os.path.exists(segment_path):
                return

            file_size = os.path.getsize(segment_path)

            # Skip and delete empty/corrupt segments (< 10KB means no real video)
            if file_size < 10240:
                logger.debug(f"[{camera_id}] Discarding empty segment: {os.path.basename(segment_path)} ({file_size} bytes)")
                try:
                    os.remove(segment_path)
                except OSError:
                    pass
                return

            basename = os.path.basename(segment_path)

            # Parse timestamp from filename: 20240101_120000.mp4
            # Treat the filename as UTC to avoid timezone skew.
            try:
                ts_str = basename.replace(".mp4", "").replace(".mkv", "")
                start_time = datetime.strptime(ts_str, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
            except ValueError:
                start_time = datetime.now(timezone.utc)

            # Probe duration with ffprobe
            duration = await self._probe_duration(segment_path)
            
            # Calculate end_time
            if duration:
                end_time = start_time + __import__("datetime").timedelta(seconds=duration)
            else:
                # Fallback: estimate duration from file modification time if ffprobe fails
                logger.warning(f"[{camera_id}] Could not probe duration for {basename}, using file mtime")
                try:
                    mtime = datetime.fromtimestamp(os.path.getmtime(segment_path))
                    estimated_duration = int((mtime - start_time).total_seconds())
                    if 0 < estimated_duration < 7200:  # Sanity check: 0-120 minutes
                        duration = estimated_duration
                        end_time = mtime
                    else:
                        # Last resort: use default segment duration (180 seconds)
                        duration = 180
                        end_time = start_time + __import__("datetime").timedelta(seconds=180)
                except Exception:
                    duration = 180
                    end_time = start_time + __import__("datetime").timedelta(seconds=180)

            from app.database import async_session_maker
            from app.recordings.service import RecordingService

            # SHA-256 checksum for evidence integrity (run in a worker thread —
            # hashing a 100 MB segment can take ~1s and would block the event loop).
            try:
                checksum = await asyncio.to_thread(
                    RecordingService.compute_sha256, segment_path
                )
            except Exception as _hash_err:
                logger.warning(f"[{camera_id}] checksum compute failed: {_hash_err}")
                checksum = None

            async with async_session_maker() as session:
                # Resolve storage pool
                from app.cameras.service import CameraService
                camera = await CameraService.get_by_id(session, camera_id)
                pool_id = camera.storage_pool_id if camera else None

                # ── Mirror copy (Phase 4.4) ───────────────────────────────
                # When camera.redundancy_enabled is set, copy the finalized
                # segment to a secondary pool. Failures here are logged but
                # don't fail the primary write — that's the whole point.
                redundant_path = None
                if camera and getattr(camera, "redundancy_enabled", False):
                    try:
                        from app.storage.service import StorageService
                        mirror_pool = await StorageService.select_mirror_pool(session, pool_id)
                        if mirror_pool:
                            import shutil as _sh
                            mirror_dir = os.path.join(mirror_pool.path, camera_id)
                            os.makedirs(mirror_dir, exist_ok=True)
                            mirror_path = os.path.join(mirror_dir, basename)
                            await asyncio.to_thread(_sh.copy2, segment_path, mirror_path)
                            redundant_path = mirror_path
                            logger.debug(
                                f"[{camera_id}] Mirrored segment to pool "
                                f"{mirror_pool.id} ({mirror_pool.name})"
                            )
                    except Exception as mirror_err:
                        logger.warning(f"[{camera_id}] mirror copy failed: {mirror_err}")

                # Determine actual stream type from process state
                ff_proc = self._processes.get(camera_id)
                stream_type = "sub" if (ff_proc and ff_proc.failover_active) else "main"

                await RecordingService.register_segment(
                    session,
                    camera_id=camera_id,
                    file_path=segment_path,
                    start_time=start_time,
                    end_time=end_time,
                    duration=duration,
                    file_size=file_size,
                    stream_type=stream_type,
                    storage_pool_id=pool_id,
                    checksum=checksum,
                )
                if redundant_path:
                    from sqlalchemy import text as _text
                    # register_segment uses raw SQL — patch the just-inserted row.
                    await session.execute(_text("""
                        UPDATE recordings SET redundant_path = :rp
                        WHERE camera_id = :cid AND file_path = :fp
                    """), {"rp": redundant_path, "cid": camera_id, "fp": segment_path})
                    await session.commit()
                logger.debug(f"[{camera_id}] Segment registered: {basename} ({file_size / 1_048_576:.1f} MB)")

        except Exception as e:
            logger.error(f"[{camera_id}] Failed to register segment: {e}")

    @staticmethod
    async def _probe_duration(path: str) -> Optional[int]:
        """Probe video duration with retry logic for files that may still be flushing."""
        for attempt in range(3):
            try:
                # Wait a moment for file system to flush if this is first attempt
                if attempt > 0:
                    await asyncio.sleep(0.5)
                
                proc = await asyncio.create_subprocess_exec(
                    "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", path,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
                duration_str = stdout.decode().strip()
                if duration_str and duration_str != "N/A":
                    return int(float(duration_str))
            except Exception:
                if attempt == 2:  # Last attempt
                    logger.debug(f"ffprobe failed for {os.path.basename(path)} after 3 attempts")
        return None

    # ------------------------------------------------------------------
    # Auto-restart
    # ------------------------------------------------------------------

    def _record_restart_attempt(self, camera_id: str) -> int:
        """Append now() to the camera's restart-history deque, prune entries
        older than the sliding window, and return the count inside the window."""
        now = time.time()
        history = self._restart_history.setdefault(camera_id, [])
        cutoff = now - self._restart_window
        history[:] = [t for t in history if t >= cutoff]
        history.append(now)
        return len(history)

    async def _mark_camera_failed(self, camera_id: str, reason: str):
        """Storm guard tripped — stop attempting restarts and alert operator."""
        if camera_id in self._failed_cameras:
            return
        self._failed_cameras.add(camera_id)
        self._processes.pop(camera_id, None)
        logger.error(f"[{camera_id}] FFmpeg restart storm — marking camera FAILED ({reason})")
        asyncio.create_task(self._mark_recording_stopped(camera_id))
        # Fire video_loss event + notification so operator sees it immediately
        try:
            from app.events.linkage_service import linkage_engine
            from app.notifications.service import notification_service
            from app.notifications.models import NotificationEvent
            asyncio.create_task(linkage_engine.fire_event(
                camera_id=camera_id,
                event_type="video_loss",
                severity="critical",
                title=f"Camera failed — {camera_id}",
                description=reason,
                metadata={"reason": reason},
            ))
            asyncio.create_task(notification_service.notify(
                NotificationEvent.CAMERA_ERROR,
                {"camera_id": camera_id, "message": reason},
                camera_id=camera_id,
            ))
        except Exception as e:
            logger.debug(f"[{camera_id}] failed-state alert dispatch error: {e}")

    async def _auto_restart(self, ff: FFmpegProcess, delay: int = 5):
        """
        Wait and restart a crashed FFmpeg process with exponential backoff.
        Storm guard: if ≥3 restarts land inside a rolling 60-second window the
        camera is marked FAILED, no further restarts attempted, video_loss event
        fired so the operator sees the problem instead of a silent retry loop.
        Failover strategy:
          - Attempts 1-3: retry main stream
          - Attempt 4+:   switch to sub stream (if configured)
          - After 30 min on sub: try main again automatically
        """
        if ff.camera_id in self._failed_cameras:
            return

        attempts_in_window = self._record_restart_attempt(ff.camera_id)
        if attempts_in_window >= self._restart_storm_limit:
            await self._mark_camera_failed(
                ff.camera_id,
                f"{attempts_in_window} restarts within {int(self._restart_window)}s",
            )
            return

        # Exponential backoff: 5s, 10s, 20s, 40s, 80s, max 300s (5 min)
        backoff_delay = min(300, delay * (2 ** ff.restart_count))
        logger.info(f"[{ff.camera_id}] Waiting {backoff_delay}s before restart (attempt {ff.restart_count + 1})")
        
        await asyncio.sleep(backoff_delay)

        # Check if recording was explicitly stopped, system is shutting down,
        # or process has been replaced by another start_recording
        if self._shutting_down or ff.camera_id in self._stopped:
            return
        current = self._processes.get(ff.camera_id)
        if current is not ff:
            return  # another start_recording replaced this process

        next_count = ff.restart_count + 1

        # Decide which stream URL to try next
        use_url = ff.rtsp_url
        going_failover = False

        if ff.sub_stream_url and not ff.failover_active and next_count >= 4:
            # Switch to sub stream after 3 failed main stream attempts
            use_url = ff.sub_stream_url
            going_failover = True
            logger.warning(
                f"[{ff.camera_id}] Main stream failed {next_count - 1}x — "
                f"switching to sub-stream failover: {ff.sub_stream_url}"
            )
            # Broadcast failover event via WebSocket
            asyncio.create_task(self._broadcast_failover(ff.camera_id, True))
        elif ff.failover_active:
            use_url = ff.sub_stream_url  # stay on sub

        logger.info(f"[{ff.camera_id}] Auto-restarting FFmpeg (attempt {next_count}, "
                    f"{'SUB' if going_failover or ff.failover_active else 'MAIN'} stream)")

        ok, _ = await self.start_recording(
            ff.camera_id, use_url, ff.storage_path,
            ff.recording_fps, ff.segment_duration,
            sub_stream_url=ff.sub_stream_url,
            privacy_masks=ff.privacy_masks,
            pos_overlay_config=ff.pos_overlay_config,
        )
        if ok and ff.camera_id in self._processes:
            new_ff = self._processes[ff.camera_id]
            new_ff.restart_count = next_count
            new_ff.main_stream_url = ff.main_stream_url
            new_ff.sub_stream_url = ff.sub_stream_url
            new_ff.failover_active = going_failover or ff.failover_active

            # Schedule recovery attempt back to main after 30 min on sub
            if new_ff.failover_active and ff.main_stream_url:
                asyncio.create_task(self._try_recover_main(ff.camera_id, delay=1800))

    # ------------------------------------------------------------------
    # Mark recording stopped in DB
    # ------------------------------------------------------------------

    async def _mark_recording_stopped(self, camera_id: str):
        """Set camera.is_recording = False when max retries exhausted."""
        try:
            from app.database import async_session_maker
            from app.cameras.service import CameraService
            async with async_session_maker() as session:
                camera = await CameraService.get_by_id(session, camera_id)
                if camera:
                    camera.is_recording = False
                    camera.status = "error"
                    await session.commit()
                    logger.info(f"[{camera_id}] Marked camera as not recording (max retries)")
            # Broadcast via WebSocket
            from app.core.websocket import ws_manager as connection_manager
            await connection_manager.broadcast_camera_status(
                camera_id, "error", False,
                error_message="Recording stopped after 3 failed attempts"
            )
        except Exception as e:
            logger.error(f"[{camera_id}] Failed to mark recording stopped: {e}")

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def health_check(self) -> Dict[str, dict]:
        """Check all active processes. Returns dict of camera_id → status."""
        result = {}
        for camera_id, ff in list(self._processes.items()):
            alive = ff.process.returncode is None
            result[camera_id] = {
                "alive": alive,
                "pid": ff.pid,
                "uptime_seconds": int((datetime.now(timezone.utc) - ff.started_at).total_seconds()),
                "restart_count": ff.restart_count,
                "last_health": ff.last_health,
                "failover_active": ff.failover_active,
                "stream": "sub" if ff.failover_active else "main",
            }
        return result

    async def _try_recover_main(self, camera_id: str, delay: int = 1800):
        """
        After `delay` seconds on sub-stream, attempt to reconnect to main stream.
        If main stream recovers, switch back automatically.
        """
        await asyncio.sleep(delay)
        ff = self._processes.get(camera_id)
        if not ff or not ff.failover_active or not ff.main_stream_url:
            return

        logger.info(f"[{camera_id}] Attempting main-stream recovery after failover...")
        # Test the go2rtc proxy URL, not the camera directly, because the proxy
        # may have dropped the upstream while the camera is still reachable.
        proxy_url = go2rtc_manager.get_rtsp_output_url(camera_id)
        ok, info = await self.test_rtsp_connection(proxy_url)
        if ok:
            logger.info(f"[{camera_id}] Main stream recovered — switching back from sub-stream")
            await self.stop_recording(camera_id)
            await asyncio.sleep(2)
            await self.start_recording(
                camera_id, ff.main_stream_url, ff.storage_path,
                ff.recording_fps, ff.segment_duration,
                pos_overlay_config=ff.pos_overlay_config,
                sub_stream_url=ff.sub_stream_url,
            )
            if camera_id in self._processes:
                self._processes[camera_id].main_stream_url = ff.main_stream_url
                self._processes[camera_id].sub_stream_url = ff.sub_stream_url
                self._processes[camera_id].failover_active = False
                # Broadcast recovery event via WebSocket
                asyncio.create_task(self._broadcast_failover(camera_id, False))
        else:
            logger.warning(f"[{camera_id}] Main stream still down — staying on sub-stream")
            # Try again later
            asyncio.create_task(self._try_recover_main(camera_id, delay=1800))

    async def _broadcast_failover(self, camera_id: str, failover_active: bool):
        """Broadcast stream failover status change via WebSocket."""
        try:
            from app.core.websocket import ws_manager as connection_manager
            await connection_manager.broadcast(
                "cameras",
                {
                    "type": "stream_failover",
                    "camera_id": camera_id,
                    "failover_active": failover_active,
                    "stream": "sub" if failover_active else "main",
                    "message": "Switched to sub-stream" if failover_active else "Recovered to main stream",
                },
            )
        except Exception as e:
            logger.debug(f"[{camera_id}] Failed to broadcast failover status: {e}")

    # ------------------------------------------------------------------
    # Test connection
    # ------------------------------------------------------------------

    @staticmethod
    async def test_rtsp_connection(rtsp_url: str) -> Tuple[bool, Optional[dict]]:
        """Test if an RTSP URL is reachable. Returns (success, stream_info)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error",
                "-rtsp_transport", "tcp",
                # Also probe format-level fields (bit_rate is often only
                # set on the container, not the per-stream entry).
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

            # Many ONVIF cameras leave per-stream bit_rate=N/A and only
            # populate format.bit_rate. Fall back when needed.
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

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    @staticmethod
    async def capture_snapshot(rtsp_url: str, camera_id: str) -> Optional[str]:
        """Capture a single frame from the stream."""
        thumb_dir = str(settings.THUMBNAIL_PATH / camera_id) if hasattr(settings.THUMBNAIL_PATH, '__truediv__') else os.path.join(str(settings.THUMBNAIL_PATH), camera_id)
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
            return path if os.path.exists(path) else None
        except Exception as e:
            logger.error(f"Snapshot failed for {camera_id}: {e}")
            return None

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Watchdog — detect hung / dead FFmpeg processes between segment cycles
    # ------------------------------------------------------------------

    async def start_watchdog(self):
        """Start the per-process health watchdog. Idempotent."""
        if self._watchdog_task and not self._watchdog_task.done():
            return
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())
        logger.info(f"FFmpeg watchdog started (interval={self._watchdog_interval}s)")

    async def stop_watchdog(self):
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass

    async def _watchdog_loop(self):
        """Poll every _watchdog_interval seconds. Two failure modes:
        1. Dead PID — stderr reader should already fire restart, but if it
           somehow missed (e.g. cancelled), the watchdog kicks one off.
        2. Hung PID — process alive but `last_health` (updated on every new
           segment opened in stderr) older than stall_factor * segment_duration.
           Force-kill so stderr-reader → _auto_restart path fires.
        """
        while not self._shutting_down:
            try:
                await asyncio.sleep(self._watchdog_interval)
                if self._shutting_down:
                    break
                now = time.time()
                for camera_id, ff in list(self._processes.items()):
                    if camera_id in self._stopped or camera_id in self._failed_cameras:
                        continue
                    rc = ff.process.returncode
                    if rc is not None:
                        # Process is dead. stderr reader normally handles this,
                        # but if its task already finished without scheduling a
                        # restart (and we're not shutting down), retry here.
                        if (
                            settings.FFMPEG_RECOVERY_ENABLED
                            and ff.stderr_task
                            and ff.stderr_task.done()
                        ):
                            logger.warning(
                                f"[{camera_id}] Watchdog detected dead PID {ff.pid} "
                                f"(rc={rc}) — scheduling restart"
                            )
                            asyncio.create_task(self._auto_restart(ff))
                        continue
                    # Stall check — no new segment in stall_threshold seconds
                    stall_threshold = max(60, ff.segment_duration * self._stall_factor)
                    if now - ff.last_health > stall_threshold:
                        stall_age = int(now - ff.last_health)
                        logger.warning(
                            f"[{camera_id}] Watchdog: FFmpeg hung "
                            f"(no segment for {stall_age}s, PID {ff.pid}) — force-killing"
                        )
                        # Force-kill (not graceful — process is hung). The
                        # stderr-reader loop will then exit and schedule a restart.
                        try:
                            ff.process.kill()
                        except ProcessLookupError:
                            pass
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Watchdog loop error: {e}")

    async def cleanup(self):
        """Stop all FFmpeg processes gracefully — called on shutdown.

        Sets the shutdown flag (blocks auto_restart for all processes),
        then stops every FFmpeg in parallel via SIGINT so each can flush
        its current MP4 segment's moov atom. Each stderr reader is awaited
        so the final segment is registered in the DB before we return.
        """
        self._shutting_down = True
        count = len(self._processes)
        if count == 0:
            return
        logger.info(f"Graceful shutdown: stopping {count} FFmpeg process(es)...")
        # Drain in parallel — each call has its own bounded timeout.
        await asyncio.gather(
            *(self.stop_recording(cid) for cid in list(self._processes.keys())),
            return_exceptions=True,
        )
        logger.info("All FFmpeg processes stopped")

    # ------------------------------------------------------------------
    # Pre/post event buffer recording
    # ------------------------------------------------------------------

    async def start_buffer_recording(
        self,
        camera_id: str,
        rtsp_url: str,
        storage_path: str,
        pre_seconds: int = 30,
        post_seconds: int = 30,
        trigger_type: str = "manual",
        recording_fps: Optional[int] = None,
    ) -> Tuple[bool, str]:
        """
        Start a short event-triggered recording that captures *pre_seconds*
        before and *post_seconds* after the trigger.

        The circular pre-buffer is achieved by running FFmpeg in segment mode
        with very short segments (5 s).  The last ``pre_seconds / 5`` segment
        files are treated as the pre-buffer; after the trigger we continue
        recording for ``post_seconds`` then stop.

        If a continuous recording is already active for this camera, we simply
        mark the current point as an event instead of starting a new process.
        """
        buf_key = f"{camera_id}_buffer"

        # If already recording continuously, tag the event only
        if self.is_recording(camera_id):
            logger.info(
                f"[{camera_id}] Buffer recording requested but continuous "
                f"recording active — tagging event ({trigger_type})"
            )
            return True, "event_tagged"

        # Clean up any previous buffer process
        if buf_key in self._processes:
            existing = self._processes[buf_key]
            if existing.process.returncode is None:
                await self._kill_process(existing)
            del self._processes[buf_key]

        buf_dir = os.path.join(storage_path, "_buffer")
        os.makedirs(buf_dir, exist_ok=True)

        total_seconds = pre_seconds + post_seconds
        seg_dur = 5  # small segments for buffer granularity

        cmd = self._build_ffmpeg_cmd(rtsp_url, buf_dir, seg_dur, recording_fps)
        # Append a time limit so FFmpeg exits automatically
        cmd = cmd[:-1] + ["-t", str(total_seconds), cmd[-1]]

        logger.info(
            f"[{camera_id}] Starting buffer recording "
            f"({pre_seconds}s pre + {post_seconds}s post, trigger={trigger_type})"
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as e:
            logger.error(f"[{camera_id}] Buffer FFmpeg launch failed: {e}")
            return False, str(e)

        ff = FFmpegProcess(
            buf_key, proc, rtsp_url, buf_dir, seg_dur, recording_fps,
        )
        ff.stderr_task = asyncio.create_task(self._read_stderr(ff))
        self._processes[buf_key] = ff

        # Schedule auto-stop after total_seconds
        asyncio.create_task(self._stop_buffer_after(buf_key, total_seconds))

        return True, buf_dir

    async def _stop_buffer_after(self, buf_key: str, delay: int):
        """Auto-stop the buffer process after *delay* seconds."""
        await asyncio.sleep(delay + 2)
        async with self._lock:
            ff = self._processes.pop(buf_key, None)
        if ff and ff.process.returncode is None:
            await self._kill_process(ff)
            logger.info(f"[{buf_key}] Buffer recording auto-stopped")


# Module singleton
ffmpeg_manager = FFmpegManager()
