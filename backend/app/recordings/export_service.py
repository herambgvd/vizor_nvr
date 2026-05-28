# =============================================================================
# Export Service — real FFmpeg clip export (concat + trim)
# =============================================================================
#
# Flow:
#   1. User requests: camera_id + start_time + end_time + format
#   2. Find all overlapping recording segments
#   3. Create FFmpeg concat list
#   4. ffmpeg -f concat -safe 0 -i list.txt -ss <offset> -to <duration> -c copy out.mp4
#   5. Return export file path
#
# Exports are stored in {EXPORT_PATH}/{export_id}.{format}
# Large exports run async — caller polls status via export_id
# =============================================================================

import asyncio
import os
import logging
import uuid
import tempfile
from typing import Optional, Dict
from datetime import datetime, timezone, timedelta

from app.config import settings

logger = logging.getLogger(__name__)


class ExportJob:
    __slots__ = ("id", "camera_id", "start_time", "end_time", "format",
                 "status", "progress", "file_path", "file_size", "error")

    def __init__(self, camera_id: str, start_time: datetime, end_time: datetime, fmt: str):
        self.id = str(uuid.uuid4())
        self.camera_id = camera_id
        self.start_time = start_time
        self.end_time = end_time
        self.format = fmt
        self.status = "queued"
        self.progress = 0.0
        self.file_path: Optional[str] = None
        self.file_size: Optional[int] = None
        self.error: Optional[str] = None


class ExportService:
    """Manages concurrent FFmpeg export jobs."""

    def __init__(self):
        self._jobs: Dict[str, ExportJob] = {}
        self._semaphore = asyncio.Semaphore(8)  # max concurrent exports (64-channel NVR)

    @property
    def jobs(self) -> Dict[str, ExportJob]:
        return self._jobs

    def get_job(self, export_id: str) -> Optional[ExportJob]:
        return self._jobs.get(export_id)

    async def create_export(
        self, camera_id: str, start_time: datetime, end_time: datetime,
        segments: list, fmt: str = "mp4", db=None, user_id: str = None,
        privacy_masks: list = None, pos_overlay_config: dict = None,
    ) -> ExportJob:
        """
        Queue an export. segments is a list of Recording ORM objects
        that overlap the requested time range.
        """
        if not segments:
            raise ValueError("No recording segments found for the requested time range")

        job = ExportJob(camera_id, start_time, end_time, fmt)
        self._jobs[job.id] = job
        
        # Lock all segments to prevent deletion during export
        segment_ids = [seg.id for seg in segments]
        if db and segment_ids:
            await self._lock_segments(db, segment_ids, user_id, job.id)

        # Fetch camera overlay config if not provided
        if privacy_masks is None and pos_overlay_config is None and db:
            from app.cameras.models import Camera
            from sqlalchemy import select
            try:
                result = await db.execute(select(Camera).where(Camera.id == camera_id))
                cam = result.scalar_one_or_none()
                if cam:
                    privacy_masks = cam.privacy_masks
                    pos_overlay_config = cam.pos_overlay_config
            except Exception:
                pass

        # Fire-and-forget the export
        asyncio.create_task(
            self._run_export(job, segments, segment_ids, privacy_masks, pos_overlay_config)
        )
        return job

    async def _lock_segments(self, db, segment_ids: list, user_id: str, export_id: str):
        """Lock recording segments during export to prevent retention deletion."""
        from app.recordings.models import Recording
        from sqlalchemy import update
        
        try:
            await db.execute(
                update(Recording)
                .where(Recording.id.in_(segment_ids))
                .values(
                    locked=True,
                    locked_by=f"export:{export_id}" if not user_id else user_id,
                    locked_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()
            logger.info(f"Locked {len(segment_ids)} segments for export {export_id}")
        except Exception as e:
            logger.warning(f"Failed to lock segments for export {export_id}: {e}")

    async def _unlock_segments(self, segment_ids: list):
        """Unlock recording segments after export completes."""
        if not segment_ids:
            return
        
        from app.database import async_session_maker
        from app.recordings.models import Recording
        from sqlalchemy import update
        
        try:
            async with async_session_maker() as db:
                await db.execute(
                    update(Recording)
                    .where(Recording.id.in_(segment_ids))
                    .values(locked=False, locked_by=None, locked_at=None)
                )
                await db.commit()
            logger.info(f"Unlocked {len(segment_ids)} segments after export")
        except Exception as e:
            logger.warning(f"Failed to unlock segments: {e}")

    async def _run_export(
        self, job: ExportJob, segments: list, segment_ids: list = None,
        privacy_masks: list = None, pos_overlay_config: dict = None,
    ):
        async with self._semaphore:
            job.status = "processing"
            job.progress = 0.1
            concat_file = None

            try:
                # 1. Create concat list
                concat_file = tempfile.NamedTemporaryFile(
                    mode="w", suffix=".txt", delete=False, prefix="nvr_export_"
                )
                for seg in segments:
                    # FFmpeg concat demuxer format
                    path = seg.file_path.replace("'", "'\\''")
                    concat_file.write(f"file '{path}'\n")
                concat_file.close()
                job.progress = 0.2

                # 2. Calculate seek offsets
                first_seg_start = segments[0].start_time
                last_seg_end = segments[-1].end_time or segments[-1].start_time

                # Offset from the first segment start to our desired start
                ss_offset = (job.start_time - first_seg_start).total_seconds()
                ss_offset = max(0, ss_offset)

                # Total duration we want
                duration = (job.end_time - job.start_time).total_seconds()

                # 3. Output path
                os.makedirs(settings.EXPORT_PATH, exist_ok=True)
                output = os.path.join(settings.EXPORT_PATH, f"{job.id}.{job.format}")

                # 4. Build FFmpeg command
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

                if pos_overlay_config and pos_overlay_config.get("enabled"):
                    from app.services.pos_overlay_service import pos_overlay_service
                    text_file = pos_overlay_service._file_path(job.camera_id)
                    style = pos_overlay_config.get("text_style", "fontsize=24:fontcolor=white@0.9:box=1:boxcolor=black@0.5")
                    position = pos_overlay_config.get("position", "x=10:y=10")
                    if os.path.exists(text_file):
                        vf_parts.append(
                            f"drawtext=textfile={text_file}:reload=1:{style}:{position}"
                        )

                cmd = [
                    "ffmpeg", "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", concat_file.name,
                    "-ss", f"{ss_offset:.3f}",
                    "-t", f"{duration:.3f}",
                ]

                if vf_parts:
                    cmd.extend(["-vf", ",".join(vf_parts)])
                    # Select encoder
                    from app.services.ffmpeg_manager import FFmpegManager
                    hw = FFmpegManager._detect_hwaccel()
                    if hw == "h264_nvenc":
                        cmd.extend(["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "23"])
                    elif hw == "h264_vaapi":
                        cmd.extend(["-c:v", "h264_vaapi", "-qp", "23"])
                    elif hw == "h264_videotoolbox":
                        cmd.extend(["-c:v", "h264_videotoolbox", "-b:v", "4M"])
                    else:
                        cmd.extend(["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23"])
                    cmd.extend(["-c:a", "aac", "-b:a", "64k"])
                else:
                    cmd.extend(["-c", "copy"])

                cmd.extend([
                    "-movflags", "+faststart",
                    output,
                ])
                job.progress = 0.3

                # 5. Run FFmpeg
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                # Monitor progress (basic: poll until done)
                _, stderr = await proc.communicate()

                if proc.returncode != 0:
                    err = stderr.decode(errors="replace")[-500:]
                    logger.error(f"Export {job.id} failed: {err}")
                    job.status = "failed"
                    job.error = err
                    return

                # 6. Verify output
                if os.path.exists(output):
                    job.file_path = output
                    job.file_size = os.path.getsize(output)
                    job.status = "done"
                    job.progress = 1.0
                    logger.info(
                        f"Export {job.id} complete: {job.file_size / 1_048_576:.1f} MB"
                    )
                else:
                    job.status = "failed"
                    job.error = "Output file not created"

            except Exception as e:
                logger.exception(f"Export {job.id} error")
                job.status = "failed"
                job.error = str(e)
            finally:
                # Cleanup concat file
                if concat_file and os.path.exists(concat_file.name):
                    try:
                        os.unlink(concat_file.name)
                    except Exception:
                        pass
                # Unlock segments after export (success or failure)
                if segment_ids:
                    await self._unlock_segments(segment_ids)

    async def cancel_export(self, export_id: str) -> bool:
        job = self._jobs.get(export_id)
        if job and job.status in ("queued", "processing"):
            job.status = "failed"
            job.error = "Cancelled"
            return True
        return False

    def cleanup_old_exports(self, max_age_hours: int = 24):
        """Remove old export files from disk and memory."""
        now = datetime.now(timezone.utc)
        to_remove = []
        for eid, job in self._jobs.items():
            if job.status in ("done", "failed"):
                # If file exists and is old, remove it
                if job.file_path and os.path.exists(job.file_path):
                    mtime = datetime.fromtimestamp(os.path.getmtime(job.file_path), tz=timezone.utc)
                    if (now - mtime).total_seconds() > max_age_hours * 3600:
                        try:
                            os.unlink(job.file_path)
                        except Exception:
                            pass
                        to_remove.append(eid)
                else:
                    to_remove.append(eid)

        for eid in to_remove:
            del self._jobs[eid]


# Module singleton
export_service = ExportService()
