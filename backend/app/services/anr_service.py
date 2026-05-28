# =============================================================================
# ANR Service — Automatic Network Replenishment
# =============================================================================
# When a camera goes offline and later recovers, this service attempts to
# backfill the missing recording gap from the camera's local storage (SD card
# or onboard NAS).  It tries multiple methods:
#
#   1. RTSP range playback  (most compatible — Hikvision, Dahua, Axis, Uniview)
#   2. ONVIF Profile G Search + Replay  (standards-compliant cameras)
#   3. HTTP vendor APIs  (fallback for specific OEMs)
#
# Downloaded segments are written to the camera's normal recording directory
# and registered in the DB with trigger_type="anr" so they appear in playback
# and timeline.
# =============================================================================

import asyncio
import os
import re
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Tuple
from pathlib import Path

from app.database import async_session_maker
from app.config import settings

logger = logging.getLogger(__name__)


class ANRService:
    """Orchestrates backfill of recording gaps after camera recovery."""

    # Segment size for ANR downloads (seconds)
    SEGMENT_DURATION = 600  # 10 min chunks — safe for interrupted downloads

    async def on_camera_recovered(self, camera_id: str):
        """Entry point called by CameraMonitor when a camera comes back online."""
        async with async_session_maker() as db:
            from sqlalchemy import select
            from app.cameras.models import Camera, AnrJob

            result = await db.execute(select(Camera).where(Camera.id == camera_id))
            camera = result.scalar_one_or_none()
            if not camera or not camera.anr_enabled:
                return

            # Find the recording gap
            gap_start, gap_end = await self._find_gap(db, camera_id)
            if not gap_start or not gap_end:
                logger.debug(f"[{camera_id}] No recording gap found — ANR not needed")
                return

            gap_hours = (gap_end - gap_start).total_seconds() / 3600
            if gap_hours > camera.anr_max_gap_hours:
                logger.info(
                    f"[{camera_id}] Gap {gap_hours:.1f}h exceeds ANR max "
                    f"({camera.anr_max_gap_hours}h) — skipping"
                )
                camera.anr_status = "failed"
                camera.anr_last_run_at = datetime.now(timezone.utc)
                await db.commit()
                return

            # Check if an active job already exists for this gap
            existing = await db.execute(
                select(AnrJob).where(
                    AnrJob.camera_id == camera_id,
                    AnrJob.status.in_(["pending", "searching", "downloading"]),
                )
            )
            if existing.scalars().first():
                logger.debug(f"[{camera_id}] ANR job already active — skipping duplicate")
                return

            # Create job record
            job = AnrJob(
                camera_id=camera_id,
                gap_start=gap_start,
                gap_end=gap_end,
                status="pending",
            )
            db.add(job)
            camera.anr_status = "pending"
            camera.anr_last_run_at = datetime.now(timezone.utc)
            await db.commit()

            # Spawn background backfill
            asyncio.create_task(self._backfill_camera(camera_id, job.id))

    async def _find_gap(
        self, db, camera_id: str
    ) -> Tuple[Optional[datetime], Optional[datetime]]:
        """Return (gap_start, gap_end) for the most recent outage."""
        from sqlalchemy import select
        from app.recordings.models import Recording
        from app.cameras.models import Camera

        # Find the last recording before the most recent online recovery
        camera_result = await db.execute(
            select(Camera).where(Camera.id == camera_id)
        )
        camera = camera_result.scalar_one_or_none()
        if not camera or not camera.last_online_at:
            return None, None

        # The gap is from the last recording end_time up to when camera came back
        rec_result = await db.execute(
            select(Recording)
            .where(
                Recording.camera_id == camera_id,
                Recording.end_time.isnot(None),
            )
            .order_by(Recording.end_time.desc())
            .limit(1)
        )
        last_rec = rec_result.scalar_one_or_none()

        gap_start = last_rec.end_time if last_rec else camera.last_online_at - timedelta(hours=1)
        gap_end = datetime.now(timezone.utc)

        # Sanity: don't backfill if gap is tiny (< 2 minutes)
        if (gap_end - gap_start).total_seconds() < 120:
            return None, None

        return gap_start, gap_end

    async def _backfill_camera(self, camera_id: str, job_id: str):
        """Background task: attempt to backfill a single camera's gap."""
        from sqlalchemy import select
        from app.cameras.models import Camera, AnrJob
        from app.storage.service import StorageService

        async with async_session_maker() as db:
            job_result = await db.execute(select(AnrJob).where(AnrJob.id == job_id))
            job = job_result.scalar_one_or_none()
            if not job:
                return

            cam_result = await db.execute(select(Camera).where(Camera.id == camera_id))
            camera = cam_result.scalar_one_or_none()
            if not camera:
                return

            job.status = "searching"
            camera.anr_status = "searching"
            await db.commit()

            storage_path = await StorageService.resolve_recording_path(db, camera)

        # ── Try methods in order of preference ────────────────────────────
        methods = [
            ("rtsp_range", self._backfill_rtsp_range),
            ("onvif_profile_g", self._backfill_onvif_profile_g),
        ]

        for method_name, method_fn in methods:
            try:
                logger.info(f"[{camera_id}] ANR trying method: {method_name}")
                found, downloaded, failed = await method_fn(
                    camera, storage_path, job.gap_start, job.gap_end
                )
                async with async_session_maker() as db:
                    job_result = await db.execute(select(AnrJob).where(AnrJob.id == job_id))
                    job = job_result.scalar_one_or_none()
                    cam_result = await db.execute(select(Camera).where(Camera.id == camera_id))
                    camera = cam_result.scalar_one_or_none()

                    job.segments_found += found
                    job.segments_downloaded += downloaded
                    job.segments_failed += failed

                    if downloaded > 0:
                        job.status = "completed"
                        camera.anr_status = "completed"
                        job.completed_at = datetime.now(timezone.utc)
                        await db.commit()
                        logger.info(
                            f"[{camera_id}] ANR completed via {method_name}: "
                            f"{downloaded} segments downloaded"
                        )
                        return

                    # Method found nothing — continue to next method
            except Exception as e:
                logger.warning(f"[{camera_id}] ANR method {method_name} failed: {e}")
                continue

        # All methods exhausted
        async with async_session_maker() as db:
            job_result = await db.execute(select(AnrJob).where(AnrJob.id == job_id))
            job = job_result.scalar_one_or_none()
            cam_result = await db.execute(select(Camera).where(Camera.id == camera_id))
            camera = cam_result.scalar_one_or_none()

            job.status = "failed"
            camera.anr_status = "failed"
            job.error_message = "All ANR methods exhausted without downloading segments"
            job.completed_at = datetime.now(timezone.utc)
            await db.commit()
            logger.warning(f"[{camera_id}] ANR failed — no segments recovered")

    # ------------------------------------------------------------------
    # Method 1: RTSP range playback (most compatible)
    # ------------------------------------------------------------------

    async def _backfill_rtsp_range(
        self,
        camera,
        storage_path: str,
        gap_start: datetime,
        gap_end: datetime,
    ) -> Tuple[int, int, int]:
        """
        Try to pull recordings via RTSP with starttime/endtime parameters.
        Supports Hikvision, Dahua, Axis, Uniview, and many others.
        Returns (segments_found, segments_downloaded, segments_failed).
        """
        found = 0
        downloaded = 0
        failed = 0

        rtsp_url = camera.main_stream_url
        if not rtsp_url:
            return found, downloaded, failed

        # Build range URL — try ISO8601 Zulu format first
        start_str = gap_start.strftime("%Y%m%dT%H%M%SZ")
        end_str = gap_end.strftime("%Y%m%dT%H%M%SZ")

        # Some vendors want different formats; we try the most common
        range_urls = [
            f"{rtsp_url}{'&' if '?' in rtsp_url else '?'}starttime={start_str}&endtime={end_str}",
            f"{rtsp_url}{'&' if '?' in rtsp_url else '?'}startTime={start_str}&endTime={end_str}",
            f"{rtsp_url}{'&' if '?' in rtsp_url else '?'}begin={start_str}&end={end_str}",
        ]

        # Also try playback=1 mode (some cameras expose recorded stream this way)
        range_urls.append(
            f"{rtsp_url}{'&' if '?' in rtsp_url else '?'}playback=1"
        )

        for url in range_urls:
            try:
                result = await self._ffmpeg_download_range(
                    url, storage_path, gap_start, gap_end, camera.id
                )
                if result > 0:
                    found += result
                    downloaded += result
                    return found, downloaded, failed
            except Exception as e:
                logger.debug(f"[{camera.id}] RTSP range URL failed: {e}")
                continue

        return found, downloaded, failed

    async def _ffmpeg_download_range(
        self,
        rtsp_url: str,
        storage_path: str,
        gap_start: datetime,
        gap_end: datetime,
        camera_id: str,
    ) -> int:
        """Use FFmpeg to download a time-range RTSP stream into segmented MP4s."""
        import shutil

        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg not found")

        total_seconds = int((gap_end - gap_start).total_seconds())
        if total_seconds <= 0:
            return 0

        downloaded = 0
        cursor = gap_start

        while cursor < gap_end:
            chunk_end = min(cursor + timedelta(seconds=self.SEGMENT_DURATION), gap_end)
            chunk_seconds = int((chunk_end - cursor).total_seconds())

            filename = cursor.strftime("%Y%m%d_%H%M%S_anr.mp4")
            output_path = os.path.join(storage_path, filename)

            # Skip if already exists
            if os.path.exists(output_path) and os.path.getsize(output_path) > 10240:
                downloaded += 1
                cursor = chunk_end
                continue

            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-rtsp_transport", "tcp",
                "-stimeout", "30000000",  # 30s socket timeout
                "-i", rtsp_url,
                "-t", str(chunk_seconds),
                "-c", "copy",
                "-movflags", "+faststart",
                "-n",  # do not overwrite output files
                output_path,
            ]

            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)

                if proc.returncode == 0 and os.path.exists(output_path):
                    file_size = os.path.getsize(output_path)
                    if file_size > 10240:
                        # Register in DB
                        await self._register_anr_segment(
                            camera_id, output_path, cursor, chunk_end, file_size
                        )
                        downloaded += 1
                        logger.debug(f"[{camera_id}] ANR segment downloaded: {filename}")
                    else:
                        os.remove(output_path)
                else:
                    if os.path.exists(output_path):
                        os.remove(output_path)
                    # If stderr mentions "404" or "not found", this URL format is wrong
                    stderr_text = (stderr or b"").decode(errors="ignore").lower()
                    if any(x in stderr_text for x in ("404", "not found", "unauthorized", "invalid")):
                        raise RuntimeError(f"RTSP range rejected: {stderr_text[:200]}")
            except asyncio.TimeoutError:
                logger.debug(f"[{camera_id}] ANR segment timeout: {filename}")
                if os.path.exists(output_path):
                    os.remove(output_path)
            except Exception as e:
                logger.debug(f"[{camera_id}] ANR segment error: {e}")
                if os.path.exists(output_path):
                    os.remove(output_path)
                raise  # Bubble up so caller tries next URL format

            cursor = chunk_end

        return downloaded

    # ------------------------------------------------------------------
    # Method 2: ONVIF Profile G (Search + Replay)
    # ------------------------------------------------------------------

    async def _backfill_onvif_profile_g(
        self,
        camera,
        storage_path: str,
        gap_start: datetime,
        gap_end: datetime,
    ) -> Tuple[int, int, int]:
        """
        Try ONVIF Profile G Recording Search and Replay.
        Returns (segments_found, segments_downloaded, segments_failed).
        """
        found = 0
        downloaded = 0
        failed = 0

        if not camera.onvif_host:
            return found, downloaded, failed

        try:
            from app.cameras.onvif_service import onvif_service
            from app.core.crypto import decrypt_value

            username = decrypt_value(camera.onvif_username) if camera.onvif_username else "admin"
            password = decrypt_value(camera.onvif_password) if camera.onvif_password else "admin"

            # 1. Search for recordings on the camera's local storage
            recordings = await onvif_service.search_recordings(
                camera.onvif_host,
                camera.onvif_port or 80,
                username,
                password,
                gap_start,
                gap_end,
            )

            if not recordings:
                return found, downloaded, failed

            found = len(recordings)

            for rec in recordings:
                try:
                    replay_uri = await onvif_service.get_replay_uri(
                        camera.onvif_host,
                        camera.onvif_port or 80,
                        username,
                        password,
                        rec["recording_token"],
                    )
                    if not replay_uri:
                        failed += 1
                        continue

                    # Download via RTSP replay URI
                    result = await self._ffmpeg_download_range(
                        replay_uri,
                        storage_path,
                        rec["start_time"],
                        rec["end_time"],
                        camera.id,
                    )
                    downloaded += result
                except Exception as e:
                    logger.debug(f"[{camera.id}] ANR ONVIF download failed: {e}")
                    failed += 1

        except Exception as e:
            logger.debug(f"[{camera.id}] ANR ONVIF Profile G failed: {e}")

        return found, downloaded, failed

    # ------------------------------------------------------------------
    # Segment registration
    # ------------------------------------------------------------------

    async def _register_anr_segment(
        self,
        camera_id: str,
        file_path: str,
        start_time: datetime,
        end_time: datetime,
        file_size: int,
    ):
        """Register a downloaded ANR segment in the recordings table."""
        from app.recordings.service import RecordingService
        from app.database import async_session_maker

        duration = int((end_time - start_time).total_seconds())

        async with async_session_maker() as db:
            await RecordingService.register_segment(
                db,
                camera_id=camera_id,
                file_path=file_path,
                start_time=start_time,
                end_time=end_time,
                duration=duration,
                file_size=file_size,
                stream_type="main",
                trigger_type="anr",
            )

    # ------------------------------------------------------------------
    # Public status API
    # ------------------------------------------------------------------

    async def get_job_status(self, camera_id: str) -> Optional[dict]:
        """Return the latest ANR job for a camera."""
        from sqlalchemy import select
        from app.cameras.models import AnrJob

        async with async_session_maker() as db:
            result = await db.execute(
                select(AnrJob)
                .where(AnrJob.camera_id == camera_id)
                .order_by(AnrJob.created_at.desc())
                .limit(1)
            )
            job = result.scalar_one_or_none()
            if not job:
                return None
            return {
                "id": job.id,
                "status": job.status,
                "gap_start": job.gap_start.isoformat() if job.gap_start else None,
                "gap_end": job.gap_end.isoformat() if job.gap_end else None,
                "segments_found": job.segments_found,
                "segments_downloaded": job.segments_downloaded,
                "segments_failed": job.segments_failed,
                "error_message": job.error_message,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            }


# Module singleton
anr_service = ANRService()
