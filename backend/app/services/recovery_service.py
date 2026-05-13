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


class RecoveryService:
    """Recover FFmpeg recording processes after server restart."""

    async def recover(self):
        """
        Scan DB for cameras with is_recording=True and restart their FFmpeg processes.
        Called during application startup (lifespan).
        """
        from app.cameras.service import CameraService
        from app.services.ffmpeg_manager import ffmpeg_manager
        from app.services.go2rtc_manager import go2rtc_manager
        from app.storage.service import StorageService
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
                for camera in cameras:
                    try:
                        # Register streams with go2rtc
                        await go2rtc_manager.add_stream(camera.id, camera.main_stream_url)
                        if camera.sub_stream_url:
                            await go2rtc_manager.add_stream(f"{camera.id}_sub", camera.sub_stream_url)

                        rtsp_url = go2rtc_manager.get_rtsp_output_url(camera.id)
                        storage_path = await StorageService.resolve_recording_path(db, camera)

                        success, _ = await ffmpeg_manager.start_recording(
                            camera.id, rtsp_url, storage_path, camera.recording_fps,
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
                logger.info(f"Recovery complete: {recovered}/{len(cameras)} cameras restored")

        except Exception as e:
            logger.error(f"Recovery failed: {e}")


# Module singleton
recovery_service = RecoveryService()
