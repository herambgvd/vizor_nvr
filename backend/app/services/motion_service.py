# =============================================================================
# Motion Detection Service — FFmpeg-based motion detection per camera
# =============================================================================
#
# Runs a lightweight FFmpeg process per camera that analyses the detect stream
# (or sub-stream) and fires motion events through the linkage engine.
#
# Detection approach:
#   ffmpeg -i <stream> -vf "select=not(mod(n\,5)),framestep=1,
#           crop=<zone>,mestimate,metadata=print" -f null -
#   → parse stdout for lavfi.motion metadata
#   → if motion score > sensitivity threshold → fire event
#
# A simpler production-ready approach: use the scene change filter and
# frame difference detection via FFmpeg.
# =============================================================================

import asyncio
import logging
import subprocess
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class MotionDetector:
    """Per-camera motion detection via FFmpeg scene-change filter."""

    def __init__(self):
        # camera_id → asyncio.subprocess.Process
        self._processes: Dict[str, asyncio.subprocess.Process] = {}
        # camera_id → asyncio.Task (output reader)
        self._tasks: Dict[str, asyncio.Task] = {}
        # camera_id → last motion event timestamp (for debounce)
        self._last_motion: Dict[str, float] = {}
        # camera_id → motion config cache
        self._configs: Dict[str, dict] = {}

    async def start_detection(
        self,
        camera_id: str,
        stream_url: str,
        motion_config: Optional[dict] = None,
    ):
        """Start motion detection for a camera."""
        if camera_id in self._processes:
            await self.stop_detection(camera_id)

        config = motion_config or {}
        sensitivity = config.get("sensitivity", 5)  # 1-10
        # Convert sensitivity 1-10 to scene change threshold 0.01-0.5
        # Higher sensitivity = lower threshold (more sensitive)
        threshold = max(0.01, 0.5 - (sensitivity * 0.05))
        debounce = config.get("debounce_seconds", 5)
        self._configs[camera_id] = {
            "sensitivity": sensitivity,
            "threshold": threshold,
            "debounce": debounce,
            "zones": config.get("zones", []),
        }

        # FFmpeg scene change detection
        # -an = no audio, select frames with scene change above threshold
        cmd = [
            "ffmpeg",
            "-hide_banner", "-loglevel", "info",
            "-rtsp_transport", "tcp",
            "-i", stream_url,
            "-an",
            "-vf", f"fps=2,select='gt(scene\\,{threshold})',metadata=print",
            "-f", "null", "-",
        ]

        # Acquire global FFmpeg process slot
        from app.services.ffmpeg_governor import ffmpeg_governor
        if not await ffmpeg_governor.acquire(camera_id, "motion"):
            logger.warning(f"[{camera_id}] Motion detection skipped — global FFmpeg cap reached")
            return

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._processes[camera_id] = process
            self._tasks[camera_id] = asyncio.create_task(
                self._read_output(camera_id, process)
            )
            logger.info(
                f"[{camera_id}] Motion detection started "
                f"(sensitivity={sensitivity}, threshold={threshold:.3f})"
            )
        except Exception as e:
            ffmpeg_governor.release(camera_id, "motion")
            logger.error(f"[{camera_id}] Failed to start motion detection: {e}")

    async def stop_detection(self, camera_id: str):
        """Stop motion detection for a camera."""
        task = self._tasks.pop(camera_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        process = self._processes.pop(camera_id, None)
        if process:
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=5)
            except (asyncio.TimeoutError, ProcessLookupError):
                process.kill()

        from app.services.ffmpeg_governor import ffmpeg_governor
        ffmpeg_governor.release(camera_id, "motion")

        self._configs.pop(camera_id, None)
        self._last_motion.pop(camera_id, None)
        logger.info(f"[{camera_id}] Motion detection stopped")

    async def stop_all(self):
        """Stop all motion detection processes."""
        camera_ids = list(self._processes.keys())
        for camera_id in camera_ids:
            await self.stop_detection(camera_id)

    def is_detecting(self, camera_id: str) -> bool:
        """Check if motion detection is active for a camera."""
        proc = self._processes.get(camera_id)
        return proc is not None and proc.returncode is None

    async def _read_output(self, camera_id: str, process: asyncio.subprocess.Process):
        """Read FFmpeg stderr for scene change metadata and fire events."""
        try:
            while True:
                line = await process.stderr.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").strip()

                # FFmpeg scene change detection outputs:
                # lavfi.scene_score=0.XXXX
                if "lavfi.scene_score=" in decoded:
                    try:
                        score_str = decoded.split("lavfi.scene_score=")[1].split()[0]
                        score = float(score_str)
                        config = self._configs.get(camera_id, {})
                        threshold = config.get("threshold", 0.25)

                        if score > threshold:
                            await self._on_motion_detected(camera_id, score)
                    except (ValueError, IndexError):
                        pass

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[{camera_id}] Motion reader error: {e}")
        finally:
            # Clean up if process ended unexpectedly
            if camera_id in self._processes:
                self._processes.pop(camera_id, None)
                logger.warning(f"[{camera_id}] Motion detection process ended")

    async def _on_motion_detected(self, camera_id: str, score: float):
        """Handle a motion detection event with debounce."""
        config = self._configs.get(camera_id, {})
        debounce = config.get("debounce", 5)

        now = time.time()
        last = self._last_motion.get(camera_id, 0)
        if (now - last) < debounce:
            return  # Debounce

        self._last_motion[camera_id] = now

        logger.info(f"[{camera_id}] Motion detected (score={score:.4f})")

        # Mark current recording segment(s) with motion
        await self._mark_recording_motion(camera_id, score)

        # Fire event through linkage engine
        from app.events.linkage_service import linkage_engine
        await linkage_engine.fire_event(
            camera_id=camera_id,
            event_type="motion_detected",
            severity="warning",
            title=f"Motion detected",
            description=f"Scene change score: {score:.4f}",
            metadata={"score": round(score, 4), "sensitivity": config.get("sensitivity", 5)},
        )

    async def _mark_recording_motion(self, camera_id: str, score: float):
        """Mark the most recent recording segment(s) for this camera as having motion."""
        try:
            from app.database import async_session_maker
            from app.recordings.service import RecordingService
            from sqlalchemy import select, text
            from datetime import datetime, timedelta

            async with async_session_maker() as db:
                # Find recordings from the last 2 minutes that don't have motion yet
                since = datetime.utcnow() - timedelta(minutes=2)
                result = await db.execute(
                    select(__import__("app.recordings.models", fromlist=["Recording"]).Recording)
                    .where(
                        __import__("app.recordings.models", fromlist=["Recording"]).Recording.camera_id == camera_id,
                        __import__("app.recordings.models", fromlist=["Recording"]).Recording.start_time >= since,
                        __import__("app.recordings.models", fromlist=["Recording"]).Recording.has_motion.is_(False),
                    )
                    .order_by(__import__("app.recordings.models", fromlist=["Recording"]).Recording.start_time.desc())
                    .limit(2)
                )
                recordings = result.scalars().all()
                for rec in recordings:
                    rec.has_motion = True
                    # Add event marker
                    markers = rec.event_markers or []
                    # Calculate approximate offset in segment
                    offset = int((datetime.utcnow() - rec.start_time).total_seconds())
                    markers.append({
                        "type": "motion",
                        "offset_seconds": max(0, offset),
                        "score": round(score, 4),
                        "timestamp": datetime.utcnow().isoformat(),
                    })
                    rec.event_markers = markers
                if recordings:
                    await db.commit()
                    logger.debug(f"[{camera_id}] Marked {len(recordings)} recording(s) with motion")
        except Exception as e:
            logger.debug(f"[{camera_id}] Failed to mark recording motion: {e}")


# Module singleton
motion_detector = MotionDetector()
