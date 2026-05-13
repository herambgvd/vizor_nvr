# =============================================================================
# Camera Monitor — background health checks, retry logic, schedule enforcement
# =============================================================================

import asyncio
import logging
from datetime import datetime, timezone

from app.config import settings
from app.database import async_session_maker

logger = logging.getLogger(__name__)


class CameraMonitor:
    """
    Periodically checks camera health:
    - Tests if FFmpeg processes are alive
    - Retries offline cameras that should be recording
    - Enforces recording schedules
    - Updates camera status
    - Triggers bandwidth monitoring per camera
    - Detects recording gaps (no new segment in 2× segment_duration)
    """

    def __init__(self, interval: int = 30):
        self._interval = interval
        self._running = False
        self._task = None
        # camera_id → last time a segment was registered (epoch seconds)
        self._last_segment_time: dict = {}
        # camera_id → whether a gap alert was already sent (avoid spam)
        self._gap_alerted: dict = {}

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"Camera monitor started (interval={self._interval}s)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Stop all motion detectors
        from app.services.motion_service import motion_detector
        await motion_detector.stop_all()
        # Stop all prebuffers
        from app.services.prebuffer_service import prebuffer_service
        await prebuffer_service.stop()
        logger.info("Camera monitor stopped")

    async def _capture_periodic_snapshot(self, camera):
        """Capture a periodic snapshot and persist to DB."""
        try:
            from app.services.ffmpeg_manager import ffmpeg_manager
            from app.cameras.models import CameraSnapshot
            import os, uuid as _uuid
            from app.config import settings as _settings

            path = await ffmpeg_manager.capture_snapshot(camera.main_stream_url, camera.id)
            if not path:
                return

            file_size = None
            try:
                file_size = os.path.getsize(path)
            except Exception:
                pass

            snap = CameraSnapshot(
                id=str(_uuid.uuid4()),
                camera_id=camera.id,
                file_path=path,
                file_size=file_size,
                trigger="periodic",
            )
            async with async_session_maker() as db:
                db.add(snap)
                await db.commit()
        except Exception as e:
            logger.debug(f"[{camera.id}] Periodic snapshot failed: {e}")

    async def _loop(self):
        # Wait a bit before first check to let everything initialize
        await asyncio.sleep(10)

        while self._running:
            try:
                await self._check_cameras()
            except Exception as e:
                logger.error(f"Camera monitor error: {e}")
            await asyncio.sleep(self._interval)

    async def _check_cameras(self):
        from app.cameras.service import CameraService
        from app.cameras.models import Camera
        from app.services.ffmpeg_manager import ffmpeg_manager
        from app.services.go2rtc_manager import go2rtc_manager
        from app.monitoring.service import monitoring_service
        from app.notifications.service import notification_service
        from app.notifications.models import NotificationEvent
        from app.core.websocket import ws_manager as connection_manager
        from app.cameras.onvif_event_service import onvif_event_service
        from app.core.crypto import decrypt_value

        async with async_session_maker() as db:
            from sqlalchemy import select
            result = await db.execute(
                select(Camera).where(Camera.is_enabled.is_(True))
            )
            cameras = result.scalars().all()

            for camera in cameras:
                try:
                    is_live = ffmpeg_manager.is_recording(camera.id)
                    prev_status = camera.status

                    # Update bandwidth tracking
                    if is_live:
                        from app.storage.service import StorageService
                        storage_path = await StorageService.resolve_recording_path(db, camera)
                        monitoring_service.update_camera_bandwidth(camera.id, storage_path)

                        # ── Recording gap detection ──────────────────────────
                        # Check if any new segment has been written recently.
                        # We compare last DB segment time against now.
                        import time as _time
                        try:
                            from app.recordings.service import RecordingService
                            latest_seg = await RecordingService.get_latest_segment(db, camera.id)
                            seg_dur = 900  # default 15 min; use camera recording fps later
                            if latest_seg and latest_seg.end_time:
                                import calendar
                                last_ts = calendar.timegm(latest_seg.end_time.timetuple())
                                gap_threshold = seg_dur * 2
                                now_ts = _time.time()
                                if camera.is_recording and (now_ts - last_ts) > gap_threshold:
                                    if not self._gap_alerted.get(camera.id):
                                        self._gap_alerted[camera.id] = True
                                        gap_min = int((now_ts - last_ts) / 60)
                                        logger.warning(
                                            f"[{camera.id}] Recording gap detected: "
                                            f"no new segment for {gap_min} min"
                                        )
                                        await notification_service.notify(
                                            NotificationEvent.RECORDING_GAP,
                                            {
                                                "camera_id": camera.id,
                                                "camera_name": camera.name,
                                                "gap_minutes": gap_min,
                                                "last_segment": latest_seg.end_time.isoformat(),
                                            },
                                            camera_id=camera.id,
                                        )
                                        await connection_manager.broadcast(
                                            "system",
                                            {
                                                "type": "recording_gap",
                                                "camera_id": camera.id,
                                                "gap_minutes": gap_min,
                                            },
                                        )
                                else:
                                    # Gap resolved
                                    self._gap_alerted[camera.id] = False
                        except Exception as _ge:
                            logger.debug(f"[{camera.id}] Gap check error: {_ge}")

                    # Camera should be recording but isn't
                    if camera.is_recording and not is_live:
                        if camera.retry_count < camera.max_retries:
                            logger.info(
                                f"[{camera.id}] Recording expected but FFmpeg not running. "
                                f"Retry {camera.retry_count + 1}/{camera.max_retries}"
                            )
                            await self._start_camera_recording(db, camera)
                        else:
                            camera.status = "error"
                            # Notify camera error
                            if prev_status != "error":
                                await notification_service.notify(
                                    NotificationEvent.CAMERA_ERROR,
                                    {"camera_id": camera.id, "camera_name": camera.name, 
                                     "message": "Max retries exceeded"},
                                    camera_id=camera.id
                                )
                                # Broadcast status change via WebSocket
                                await connection_manager.broadcast_camera_status(
                                    camera.id, "error", camera.is_recording,
                                    error_message="Max retries exceeded"
                                )
                                # Fire video_loss event through linkage engine
                                from app.events.linkage_service import linkage_engine
                                await linkage_engine.fire_event(
                                    camera_id=camera.id,
                                    event_type="video_loss",
                                    severity="critical",
                                    title=f"Video loss — {camera.name}",
                                    description="Recording process lost after max retries",
                                    metadata={"retries": camera.retry_count},
                                )

                    # Camera is live → update status
                    elif is_live:
                        if camera.status != "online":
                            # Notify camera came online
                            if prev_status in ("offline", "error"):
                                await notification_service.notify(
                                    NotificationEvent.CAMERA_ONLINE,
                                    {"camera_id": camera.id, "camera_name": camera.name},
                                    camera_id=camera.id
                                )
                                # Broadcast status change via WebSocket
                                await connection_manager.broadcast_camera_status(
                                    camera.id, "online", camera.is_recording
                                )
                                # Fire camera_online event through linkage engine
                                from app.events.linkage_service import linkage_engine
                                await linkage_engine.fire_event(
                                    camera_id=camera.id,
                                    event_type="camera_online",
                                    severity="info",
                                    title=f"Camera online — {camera.name}",
                                    description=f"Recovered from {prev_status}",
                                )
                            camera.status = "online"
                            camera.retry_count = 0

                            # Start ONVIF event pull if enabled
                            if camera.onvif_events_enabled and camera.onvif_host:
                                if not onvif_event_service.is_active(camera.id):
                                    await onvif_event_service.start_camera(
                                        camera_id=camera.id,
                                        host=camera.onvif_host,
                                        port=camera.onvif_port,
                                        username=decrypt_value(camera.onvif_username) or "admin",
                                        password=decrypt_value(camera.onvif_password) if camera.onvif_password else "admin",
                                        topics=camera.onvif_event_topics or [],
                                    )
                        camera.last_online_at = datetime.utcnow()

                        # ── Prebuffer management for motion-triggered cameras ──
                        from app.services.prebuffer_service import prebuffer_service
                        if camera.recording_mode == "motion":
                            if not prebuffer_service.is_running(camera.id):
                                asyncio.create_task(prebuffer_service.start_prebuffer(
                                    camera.id, camera.main_stream_url,
                                    pre_buffer_seconds=camera.pre_buffer_seconds or 10,
                                ))
                        else:
                            if prebuffer_service.is_running(camera.id):
                                asyncio.create_task(prebuffer_service.stop_prebuffer(camera.id))

                    # Camera went offline → stop ONVIF event pull and prebuffer
                    if not is_live and camera.status in ("offline", "error"):
                        if onvif_event_service.is_active(camera.id):
                            await onvif_event_service.stop_camera(camera.id)
                        from app.services.prebuffer_service import prebuffer_service
                        if prebuffer_service.is_running(camera.id):
                            asyncio.create_task(prebuffer_service.stop_prebuffer(camera.id))

                    # Periodic snapshot (every ~5 minutes, on the 10th check = 10 × 30s = 300s)
                    import time as _t
                    snap_key = f"_snap_{camera.id}"
                    last_snap = getattr(self, snap_key, 0)
                    if is_live and (_t.time() - last_snap) >= 300:
                        setattr(self, snap_key, _t.time())
                        asyncio.create_task(self._capture_periodic_snapshot(camera))

                    # ── Health probe (bitrate, packet loss) every 60s ──────
                    health_key = f"_health_{camera.id}"
                    last_health = getattr(self, health_key, 0)
                    if is_live and (_t.time() - last_health) >= 60:
                        setattr(self, health_key, _t.time())
                        asyncio.create_task(self._probe_camera_health(camera))

                    # ── Schedule enforcement ─────────────────────────────────────
                    if camera.recording_schedule:
                        should_record = self._should_record_now(camera.recording_schedule)
                        
                        # Schedule says record, but not recording → start
                        if should_record and not is_live:
                            logger.info(f"[{camera.id}] Schedule triggered: starting recording")
                            camera.is_recording = True
                            await self._start_camera_recording(db, camera)
                            await notification_service.notify(
                                NotificationEvent.RECORDING_STARTED,
                                {"camera_id": camera.id, "camera_name": camera.name, 
                                 "trigger": "schedule"},
                                camera_id=camera.id
                            )
                            # Broadcast recording started via WebSocket
                            await connection_manager.broadcast_camera_status(
                                camera.id, camera.status, True
                            )
                        
                        # Schedule says don't record, but we're recording → stop
                        elif not should_record and is_live:
                            logger.info(f"[{camera.id}] Schedule ended: stopping recording")
                            await ffmpeg_manager.stop_recording(camera.id)
                            camera.is_recording = False
                            camera.status = "online"  # Keep online but not recording
                            await notification_service.notify(
                                NotificationEvent.RECORDING_STOPPED,
                                {"camera_id": camera.id, "camera_name": camera.name,
                                 "trigger": "schedule"},
                                camera_id=camera.id
                            )
                            # Broadcast recording stopped via WebSocket
                            await connection_manager.broadcast_camera_status(
                                camera.id, "online", False
                            )

                except Exception as e:
                    logger.error(f"[{camera.id}] Monitor check error: {e}")

            await db.commit()

    @staticmethod
    def _should_record_now(schedule: dict) -> bool:
        """
        Check if the current time falls within the recording schedule.
        Schedule format: {"monday": [{"start": "08:00", "end": "18:00"}], ...}
        Empty schedule or no matching day → record 24/7.
        """
        if not schedule:
            return True

        now = datetime.now()
        day_name = now.strftime("%A").lower()
        day_rules = schedule.get(day_name, schedule.get("everyday", []))

        if not day_rules:
            return True  # No rule for this day → always record

        current_time = now.strftime("%H:%M")
        for rule in day_rules:
            start = rule.get("start", "00:00")
            end = rule.get("end", "23:59")
            
            # Handle overnight schedules (e.g., 22:00 to 06:00)
            if start > end:
                if current_time >= start or current_time <= end:
                    return True
            else:
                if start <= current_time <= end:
                    return True
        return False

    async def _probe_camera_health(self, camera):
        """Probe camera stream health (bitrate, packet loss, fps) via ffprobe."""
        try:
            from app.services.ffmpeg_manager import ffmpeg_manager
            from app.database import async_session_maker
            from app.cameras.models import CameraHealthSnapshot
            import uuid as _uuid

            info = await ffmpeg_manager.test_rtsp_connection(camera.main_stream_url)
            if not info or not info[0]:
                return

            stream_info = info[1] or {}
            async with async_session_maker() as db:
                snap = CameraHealthSnapshot(
                    id=str(_uuid.uuid4()),
                    camera_id=camera.id,
                    bitrate_kbps=int(stream_info.get("bitrate", 0)) // 1000 if stream_info.get("bitrate") else None,
                    fps_actual=stream_info.get("fps"),
                    status="online",
                )
                db.add(snap)
                # Keep only last 1000 snapshots per camera
                await db.execute(
                    __import__("sqlalchemy").text(
                        """DELETE FROM camera_health_snapshots
                           WHERE camera_id = :cid AND id NOT IN (
                               SELECT id FROM camera_health_snapshots
                               WHERE camera_id = :cid
                               ORDER BY captured_at DESC LIMIT 1000
                           )"""
                    ), {"cid": camera.id}
                )
                await db.commit()
        except Exception as e:
            logger.debug(f"[{camera.id}] Health probe failed: {e}")

    async def _start_camera_recording(self, db, camera):
        """Helper to start recording for a camera with proper setup."""
        from app.services.ffmpeg_manager import ffmpeg_manager
        from app.services.go2rtc_manager import go2rtc_manager
        from app.storage.service import StorageService

        # Register streams with go2rtc and wait for ready
        await go2rtc_manager.add_stream(camera.id, camera.main_stream_url)
        if camera.sub_stream_url:
            await go2rtc_manager.add_stream(f"{camera.id}_sub", camera.sub_stream_url)

        # Wait for go2rtc to establish the RTSP pull before starting FFmpeg
        await go2rtc_manager.wait_for_stream_ready(camera.id)

        rtsp_url = go2rtc_manager.get_rtsp_output_url(camera.id)
        sub_rtsp_url = go2rtc_manager.get_rtsp_output_url(f"{camera.id}_sub") if camera.sub_stream_url else None
        storage_path = await StorageService.resolve_recording_path(db, camera)

        success, _ = await ffmpeg_manager.start_recording(
            camera.id, rtsp_url, storage_path, camera.recording_fps,
            sub_stream_url=sub_rtsp_url,
            privacy_masks=camera.privacy_masks,
        )
        
        camera.retry_count += 1
        camera.last_retry_at = datetime.utcnow()

        if success:
            camera.status = "online"
            camera.retry_count = 0
            logger.info(f"[{camera.id}] Recording started successfully")
        else:
            camera.status = "error"
            logger.warning(f"[{camera.id}] Failed to start recording")


# Module singleton
camera_monitor = CameraMonitor()
