# =============================================================================
# Recovery Service — restore FFmpeg processes after restart
# =============================================================================
#
# On application startup, check for cameras that were recording (is_recording=True)
# and restart their FFmpeg processes.
# =============================================================================

import logging
from app.database import async_session_maker

logger = logging.getLogger(__name__)

# Recording modes that require a persistent FFmpeg process at startup.
# - motion: no idle ffmpeg; prebuffer service handles pre-roll, event triggers burst.
# - manual: operator-initiated only; do not auto-start.
# Schedule cameras: only start if currently inside a scheduled window (checked below).
_ALWAYS_START_MODES = {"continuous"}
_SCHEDULE_MODE = "schedule"


class RecoveryService:
    """Recover FFmpeg recording processes after server restart."""

    async def recover(self):
        """
        Scan DB for cameras with is_recording=True and restart their FFmpeg processes.
        Only continuous and schedule (when inside window) cameras get a live FFmpeg
        process. Motion and manual modes do NOT spawn idle FFmpeg on recovery.
        Called during application startup (lifespan).
        """
        from app.cameras.service import CameraService
        from app.services.ffmpeg_manager import ffmpeg_manager
        from app.services.go2rtc_manager import go2rtc_manager
        from app.storage.service import StorageService
        from app.services.camera_monitor import CameraMonitor
        from sqlalchemy import select
        from app.cameras.models import Camera

        try:
            async with async_session_maker() as db:
                result = await db.execute(
                    select(Camera).where(
                        Camera.is_recording.is_(True),
                        Camera.is_enabled.is_(True),
                    )
                )
                cameras = result.scalars().all()

                if not cameras:
                    logger.info("Recovery: no cameras to recover")
                    return

                logger.info(f"Recovery: restoring {len(cameras)} camera(s)")

                recovered = 0
                skipped = 0
                for camera in cameras:
                    try:
                        mode = (camera.recording_mode or "continuous").lower()

                        # Motion and manual modes: do NOT start a persistent ffmpeg.
                        # Reset is_recording to False so the monitor doesn't try to
                        # restart them either. The prebuffer/event system handles motion;
                        # manual requires explicit operator action.
                        if mode not in _ALWAYS_START_MODES and mode != _SCHEDULE_MODE:
                            logger.info(
                                f"Recovery: {camera.name} ({camera.id}) skipped "
                                f"(mode={mode}, no idle FFmpeg)"
                            )
                            camera.is_recording = False
                            skipped += 1
                            continue

                        # Schedule mode: only start if currently inside window
                        if mode == _SCHEDULE_MODE and camera.recording_schedule:
                            if not CameraMonitor._should_record_now(camera.recording_schedule):
                                logger.info(
                                    f"Recovery: {camera.name} ({camera.id}) skipped "
                                    f"(schedule mode, outside window)"
                                )
                                camera.is_recording = False
                                skipped += 1
                                continue

                        # Register streams with go2rtc
                        await go2rtc_manager.add_stream(camera.id, camera.main_stream_url)
                        if camera.sub_stream_url:
                            await go2rtc_manager.add_stream(f"{camera.id}_sub", camera.sub_stream_url)

                        rtsp_url = go2rtc_manager.get_rtsp_output_url(camera.id)
                        sub_rtsp_url = (
                            go2rtc_manager.get_rtsp_output_url(f"{camera.id}_sub")
                            if camera.sub_stream_url else None
                        )
                        storage_path = await StorageService.resolve_recording_path(db, camera)

                        # N5: record from sub-stream when operator opts in
                        record_url = rtsp_url
                        if getattr(camera, "record_substream", False) and sub_rtsp_url:
                            record_url = sub_rtsp_url
                            logger.info(
                                f"Recovery: {camera.name} recording from sub-stream"
                            )

                        success, _ = await ffmpeg_manager.start_recording(
                            camera.id, record_url, storage_path, camera.recording_fps,
                            sub_stream_url=sub_rtsp_url,
                            privacy_masks=camera.privacy_masks,
                        )
                        if success:
                            camera.status = "online"
                            camera.retry_count = 0
                            recovered += 1
                            logger.info(f"Recovery: {camera.name} ({camera.id}) restored")
                        else:
                            camera.status = "error"
                            logger.warning(f"Recovery: {camera.name} ({camera.id}) failed to start")

                    except Exception as e:
                        camera.status = "error"
                        logger.error(f"Recovery: {camera.name} error: {e}")

                await db.commit()
                logger.info(
                    f"Recovery complete: {recovered}/{len(cameras)} cameras restored, "
                    f"{skipped} skipped (non-continuous mode)"
                )

        except Exception as e:
            logger.error(f"Recovery failed: {e}")


# Module singleton
recovery_service = RecoveryService()
