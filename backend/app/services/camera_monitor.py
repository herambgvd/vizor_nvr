# =============================================================================
# Camera Monitor — background health checks, retry logic, schedule enforcement
# =============================================================================

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

from app.config import settings
from app.core.db_retry import with_db_retry
from app.database import async_session_maker

# Consecutive failed probes before flipping status to offline
OFFLINE_FAIL_THRESHOLD = 2
# Per-probe TCP connect timeout
PROBE_TIMEOUT_SEC = 2.5

logger = logging.getLogger(__name__)


BANDWIDTH_ALERT_CONSECUTIVE = 3    # Must exceed threshold for this many samples
BANDWIDTH_ALERT_COOLDOWN_SECS = 600  # 10 minutes between repeated alerts


CRED_PROBE_INTERVAL_SEC = 300   # 5 minutes between credential probes per camera

# Minimum seconds between camera_online ("recovered") events for the same
# camera. Prevents notification/event spam when a camera flaps repeatedly.
ONLINE_EVENT_COOLDOWN_SEC = 300


class CameraMonitor:
    """
    Periodically checks camera health:
    - Tests if FFmpeg processes are alive
    - Retries offline cameras that should be recording
    - Enforces recording schedules
    - Updates camera status
    - Triggers bandwidth monitoring per camera
    - Detects recording gaps (no new segment in 2× segment_duration)
    - Detects bandwidth budget overages and fires bandwidth_alert events
    - Probes ONVIF credential validity every 5 minutes
    """

    def __init__(self, interval: int = 30):
        self._interval = interval
        self._running = False
        self._task = None
        # camera_id → last time a segment was registered (epoch seconds)
        self._last_segment_time: dict = {}
        # camera_id → whether a gap alert was already sent (avoid spam)
        self._gap_alerted: dict = {}
        # camera_id → consecutive reachability probe failures
        self._probe_fails: dict = {}
        # Bandwidth alert state
        # camera_id → number of consecutive samples over threshold
        self._bw_over_count: dict = {}
        # camera_id → monotonic time of last alert fired (0 = never)
        self._bw_alert_fired_at: dict = {}
        # camera_id → monotonic time of last credential probe
        self._cred_probed_at: dict = {}
        # camera_id → monotonic time a camera_online event was last fired.
        # Suppresses duplicate "recovered" events when a camera flaps
        # (recover→online→recording-fail→error→recover) every monitor cycle.
        self._online_event_fired_at: dict = {}

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

    @staticmethod
    def _extract_host_port(camera) -> tuple:
        """Return (host, port) for a TCP reachability probe.

        Prefer ONVIF host (the device IP) over the RTSP URL because the
        RTSP URL may contain credentials and an unusual port. Falls back
        to parsing main_stream_url.
        """
        if camera.onvif_host:
            try:
                port = int(camera.onvif_port) if camera.onvif_port else 80
            except (TypeError, ValueError):
                port = 80
            return camera.onvif_host, port

        try:
            parsed = urlparse(camera.main_stream_url)
            host = parsed.hostname
            port = parsed.port or (554 if parsed.scheme == "rtsp" else 80)
            if host:
                return host, port
        except Exception:
            pass
        return None, None

    async def _probe_reachable(self, camera) -> bool:
        """Lightweight TCP connect probe — true if port is open."""
        host, port = self._extract_host_port(camera)
        if not host:
            return False
        try:
            fut = asyncio.open_connection(host, port)
            reader, writer = await asyncio.wait_for(fut, timeout=PROBE_TIMEOUT_SEC)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return True
        except (asyncio.TimeoutError, OSError):
            return False
        except Exception as e:
            logger.debug(f"[{camera.id}] Probe error: {e}")
            return False

    async def _loop(self):
        # Wait a bit before first check to let everything initialize
        await asyncio.sleep(10)

        _transient_sleep = self._interval
        _transient_count = 0
        while self._running:
            try:
                await self._check_cameras()
                _transient_sleep = self._interval
                _transient_count = 0
            except (OperationalError, InterfaceError, DBAPIError) as e:
                _transient_count += 1
                _transient_sleep = min(_transient_sleep * 2, 120)
                if _transient_count == 1:
                    logger.warning(
                        "Camera monitor: transient DB error (%s); "
                        "backing off to %.0fs poll",
                        type(e).__name__, _transient_sleep,
                    )
            except Exception as e:
                logger.error(f"Camera monitor error: {e}")
            await asyncio.sleep(_transient_sleep)

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

                    # Active reachability probe — short TCP connect to the
                    # camera. Authoritative source of truth for status.
                    # `is_live` (= ffmpeg running) is not enough: ffmpeg can
                    # be stuck on a buffered stream while the device is
                    # actually unreachable, and ONVIF event pull / manual
                    # snapshot also need a real device, not a stale flag.
                    reachable = await self._probe_reachable(camera)

                    if reachable:
                        self._probe_fails[camera.id] = 0
                        camera.last_online_at = datetime.utcnow()
                        # Recover from offline → online
                        if prev_status in ("offline", "error"):
                            camera.status = "online"
                            camera.retry_count = 0
                            # Camera recovery is normal state telemetry, not an
                            # operator event. Keep status/ANR/notifications, but
                            # do not write camera_online rows into Event Log.
                            now_mono = time.monotonic()
                            last_fired = self._online_event_fired_at.get(camera.id, 0.0)
                            recovered_recently = (now_mono - last_fired) < ONLINE_EVENT_COOLDOWN_SEC
                            await connection_manager.broadcast_camera_status(
                                camera.id, "online", camera.is_recording
                            )
                            # ── ANR: backfill missing recordings from camera SD card ──
                            if camera.anr_enabled:
                                from app.services.anr_service import anr_service
                                asyncio.create_task(anr_service.on_camera_recovered(camera.id))
                            if recovered_recently:
                                logger.debug(
                                    f"[{camera.id}] {camera.name} recovered from "
                                    f"{prev_status} (suppressing camera_online — "
                                    f"within {ONLINE_EVENT_COOLDOWN_SEC}s cooldown)"
                                )
                            else:
                                self._online_event_fired_at[camera.id] = now_mono
                                await notification_service.notify(
                                    NotificationEvent.CAMERA_ONLINE,
                                    {"camera_id": camera.id, "camera_name": camera.name},
                                    camera_id=camera.id,
                                )
                        elif camera.status != "online":
                            camera.status = "online"
                    else:
                        fails = self._probe_fails.get(camera.id, 0) + 1
                        self._probe_fails[camera.id] = fails
                        if fails >= OFFLINE_FAIL_THRESHOLD and prev_status != "offline":
                            camera.status = "offline"
                            # Reset retry_count so recovery path retries
                            # recording immediately once camera reappears.
                            camera.retry_count = 0
                            logger.warning(
                                f"[{camera.id}] {camera.name} unreachable "
                                f"({fails} consecutive probe failures) — marking offline"
                            )
                            await notification_service.notify(
                                NotificationEvent.CAMERA_OFFLINE,
                                {"camera_id": camera.id, "camera_name": camera.name,
                                 "message": "Camera unreachable"},
                                camera_id=camera.id,
                            )
                            await connection_manager.broadcast_camera_status(
                                camera.id, "offline", camera.is_recording,
                                error_message="Camera unreachable",
                            )
                            from app.events.linkage_service import linkage_engine
                            await linkage_engine.fire_event(
                                camera_id=camera.id,
                                event_type="camera_offline",
                                severity="warning",
                                title=f"Camera offline — {camera.name}",
                                description="No TCP response from device",
                                metadata={"consecutive_failures": fails},
                            )

                    # Update bandwidth tracking
                    if is_live:
                        from app.storage.service import StorageService
                        storage_path = await StorageService.resolve_recording_path(db, camera)
                        monitoring_service.update_camera_bandwidth(camera.id, storage_path)

                        # ── Bandwidth budget alert ───────────────────────────
                        import time as _time2
                        limit_kbps = camera.bandwidth_limit_kbps or 0
                        if limit_kbps > 0:
                            threshold_pct = camera.bandwidth_alert_threshold_pct or 80
                            trigger_kbps = limit_kbps * threshold_pct / 100
                            bw_data = monitoring_service.get_camera_bandwidth(camera.id)
                            current_kbps = bw_data.get("kbps", 0) if bw_data else 0
                            if current_kbps > trigger_kbps:
                                self._bw_over_count[camera.id] = self._bw_over_count.get(camera.id, 0) + 1
                            else:
                                self._bw_over_count[camera.id] = 0
                            consecutive = self._bw_over_count.get(camera.id, 0)
                            last_fired = self._bw_alert_fired_at.get(camera.id, 0.0)
                            cooldown_ok = (_time2.monotonic() - last_fired) >= BANDWIDTH_ALERT_COOLDOWN_SECS
                            if consecutive >= BANDWIDTH_ALERT_CONSECUTIVE and cooldown_ok:
                                self._bw_alert_fired_at[camera.id] = _time2.monotonic()
                                try:
                                    from app.events.service import EventService
                                    async with async_session_maker() as _adb:
                                        await EventService.create_event_direct(
                                            db=_adb,
                                            camera_id=camera.id,
                                            event_type="bandwidth_alert",
                                            severity="warning",
                                            title=f"Bandwidth budget exceeded — {camera.name}",
                                            description=(
                                                f"Camera {camera.name} using {current_kbps} kbps "
                                                f"(limit {limit_kbps} kbps, threshold {threshold_pct}%)"
                                            ),
                                            metadata={
                                                "current_kbps": current_kbps,
                                                "limit_kbps": limit_kbps,
                                                "threshold_pct": threshold_pct,
                                                "camera_name": camera.name,
                                            },
                                        )
                                    logger.warning(
                                        "[%s] Bandwidth alert: %s kbps > %s%% of %s kbps",
                                        camera.id, current_kbps, threshold_pct, limit_kbps,
                                    )
                                except Exception as _bwe:
                                    logger.debug("[%s] Bandwidth alert create failed: %s", camera.id, _bwe)

                        # ── Recording gap detection ──────────────────────────
                        # Check if any new segment has been written recently.
                        # We compare last DB segment time against now.
                        import time as _time
                        try:
                            from app.recordings.service import RecordingService
                            latest_seg = await RecordingService.get_latest_segment(db, camera.id)
                            seg_dur = getattr(camera, "segment_duration", None) or settings.DEFAULT_SEGMENT_DURATION or 900
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

                    # Camera should be recording but isn't.
                    # Motion and manual cameras never run a persistent FFmpeg process —
                    # skip the restart path for those modes entirely.
                    _mode = (camera.recording_mode or "continuous").lower()
                    if camera.is_recording and not is_live and _mode in ("continuous", "schedule"):
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

                    # ── Side-effects when recording is live and camera reachable ──
                    if is_live and reachable:
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

                    # ── Motion-mode reconciliation (no live FFmpeg) ──────────
                    # Motion cameras never run a persistent recording process, so
                    # this MUST run on `reachable` alone — not `is_live` — or the
                    # prebuffer + detector would never start. The motion detector
                    # is what fires motion_detected → flushes the prebuffer and
                    # starts the post-event recording; without it motion mode
                    # captures nothing. Reconciled here so a mode switch (e.g.
                    # continuous → motion) takes effect without a separate toggle.
                    if reachable and _mode == "motion":
                        from app.services.prebuffer_service import prebuffer_service
                        from app.services.motion_service import motion_detector
                        from app.services.go2rtc_manager import go2rtc_manager
                        if not prebuffer_service.is_running(camera.id):
                            asyncio.create_task(prebuffer_service.start_prebuffer(
                                camera.id, camera.main_stream_url,
                                pre_buffer_seconds=getattr(camera, "pre_buffer_seconds", None) or 10,
                            ))
                        if not motion_detector.is_detecting(camera.id):
                            mcfg = camera.motion_config or {}
                            detect_url = (
                                camera.detect_stream_url
                                or camera.sub_stream_url
                                or camera.main_stream_url
                            )
                            asyncio.create_task(self._start_motion_detection(
                                camera.id, detect_url, mcfg, camera.dewarp_config,
                            ))

                    # ── Side-effects when recording is live and camera reachable ──
                    if is_live and reachable:
                        # Motion detector / prebuffer must not run alongside a
                        # continuous/schedule live recording — stop any leftover.
                        from app.services.prebuffer_service import prebuffer_service
                        from app.services.motion_service import motion_detector
                        if prebuffer_service.is_running(camera.id):
                            asyncio.create_task(prebuffer_service.stop_prebuffer(camera.id))
                        if _mode != "motion" and motion_detector.is_detecting(camera.id):
                            asyncio.create_task(motion_detector.stop_detection(camera.id))

                    # Camera went offline → stop ONVIF event pull, prebuffer,
                    # and motion detection (they all need a reachable device).
                    if not is_live and camera.status in ("offline", "error"):
                        if onvif_event_service.is_active(camera.id):
                            await onvif_event_service.stop_camera(camera.id)
                        from app.services.prebuffer_service import prebuffer_service
                        from app.services.motion_service import motion_detector
                        if prebuffer_service.is_running(camera.id):
                            asyncio.create_task(prebuffer_service.stop_prebuffer(camera.id))
                        if motion_detector.is_detecting(camera.id):
                            asyncio.create_task(motion_detector.stop_detection(camera.id))

                    import time as _t

                    # ── Health probe (bitrate, packet loss) every 60s ──────
                    # Run whenever the camera is reachable, not only while
                    # recording. Operators need health metrics in the
                    # Cameras table before they hit Start.
                    health_key = f"_health_{camera.id}"
                    last_health = getattr(self, health_key, 0)
                    if reachable and (_t.time() - last_health) >= 60:
                        setattr(self, health_key, _t.time())
                        asyncio.create_task(self._probe_camera_health(camera))

                    # ── Credential health probe every 5 min (ONVIF only) ──────
                    if camera.onvif_host:
                        last_cred = self._cred_probed_at.get(camera.id, 0.0)
                        if (_t.time() - last_cred) >= CRED_PROBE_INTERVAL_SEC:
                            self._cred_probed_at[camera.id] = _t.time()
                            asyncio.create_task(
                                self._probe_credentials(camera.id, camera.onvif_host,
                                                        camera.onvif_port or 80,
                                                        camera.onvif_username,
                                                        camera.onvif_password)
                            )

                    # ── Schedule enforcement (only in 'schedule' mode) ───────────
                    # A camera in manual/motion/continuous mode may still carry a
                    # saved schedule grid from a previous mode. Enforcing it here
                    # would auto-restart recording the operator just stopped (e.g.
                    # a manual camera that bounces back ON seconds after Stop).
                    # The schedule must only drive cameras whose mode IS schedule.
                    if _mode == "schedule" and camera.recording_schedule:
                        should_record = self._should_record_now(camera.recording_schedule)
                        
                        # Schedule says record, but not recording → start
                        if should_record and not is_live:
                            logger.info(f"[{camera.id}] Schedule triggered: starting recording")
                            await self._start_camera_recording(db, camera)
                            if camera.status == "online":
                                camera.is_recording = True
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
                            stopped = await ffmpeg_manager.stop_recording(camera.id)
                            if stopped:
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

    # Map the grid's 3-letter day keys to weekday() index (Mon=0 … Sun=6).
    _GRID_DAY_KEYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    # Map full lowercase day names (legacy range format) for completeness.
    _FULL_DAY_KEYS = [
        "monday", "tuesday", "wednesday", "thursday",
        "friday", "saturday", "sunday",
    ]

    @staticmethod
    def _should_record_now(schedule: dict) -> bool:
        """
        Check if the current time falls within the recording schedule.

        Supports the two shapes the system actually produces:

        1. GRID (what RecordingScheduleGrid + schedule templates save):
             {"grid": {"Mon": ["continuous","off",... 24 entries], ...}}
           or the bare grid {"Mon": [...24], ...}. Each entry is the recording
           mode for that hour: "continuous"/"motion" = record, "off" = don't.

        2. RANGE (legacy): {"monday": [{"start": "08:00", "end": "18:00"}], ...}

        Empty / missing schedule or no rule for the current day → record 24/7.
        """
        if not schedule:
            return True

        # Unwrap the {enabled, grid} envelope the UI saves.
        if isinstance(schedule.get("grid"), dict):
            if schedule.get("enabled") is False:
                return True  # schedule disabled → behave like always-on
            schedule = schedule["grid"]

        if not isinstance(schedule, dict) or not schedule:
            return True

        # Evaluate against the SITE/LOCAL timezone — an operator who sets
        # "record 09:00–17:00" means local wall-clock, not UTC. RECORDING_TIMEZONE
        # (IANA name, e.g. "Asia/Kolkata") configures it; defaults to UTC.
        import os
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(os.getenv("RECORDING_TIMEZONE", "UTC"))
        except Exception:
            tz = timezone.utc
        now = datetime.now(tz)
        weekday = now.weekday()  # Mon=0 … Sun=6

        # ── Grid format (per-hour modes) ──────────────────────────────────
        grid_key = CameraMonitor._GRID_DAY_KEYS[weekday]
        day_grid = schedule.get(grid_key)
        if isinstance(day_grid, list) and day_grid and all(
            isinstance(v, str) for v in day_grid
        ):
            idx = now.hour if now.hour < len(day_grid) else len(day_grid) - 1
            return str(day_grid[idx]).lower() != "off"

        # ── Range format (legacy {start,end}) ─────────────────────────────
        day_name = CameraMonitor._FULL_DAY_KEYS[weekday]
        day_rules = schedule.get(day_name, schedule.get("everyday", []))

        if not day_rules:
            return True  # No rule for this day → always record

        current_time = now.strftime("%H:%M")
        for rule in day_rules:
            if not isinstance(rule, dict):
                continue
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

    @staticmethod
    async def _measure_bitrate_kbps(rtsp_url: str) -> Optional[int]:
        """Run ffmpeg copy for ~3s; derive bitrate from the byte total
        ffmpeg prints at end (`video:NKiB audio:MKiB`). Many cameras
        report bitrate=N/A in ffmpeg's running stats, so calculate
        from actual bytes received."""
        import re
        try:
            duration_sec = 3
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "info",
                "-stats",
                "-rtsp_transport", "tcp",
                "-i", rtsp_url,
                "-t", str(duration_sec),
                "-c", "copy",
                "-f", "null",
                "-",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            except asyncio.TimeoutError:
                proc.kill()
                return None
            text = (stderr or b"").decode("utf-8", errors="ignore")

            # Preferred — ffmpeg reports a usable bitrate=NNkbits/s
            for m in reversed(re.findall(r"bitrate=\s*([\d.]+)\s*kbits/s", text)):
                return int(float(m))

            # Fallback — sum video+audio KiB totals printed at the end
            kib_total = 0.0
            for label in ("video", "audio"):
                m = re.search(rf"{label}:\s*([\d.]+)KiB", text)
                if m:
                    kib_total += float(m.group(1))
            if kib_total > 0:
                bits = kib_total * 1024 * 8
                return int(bits / 1000 / duration_sec)
            return None
        except Exception:
            return None

    async def _probe_camera_health(self, camera):
        """Probe camera stream health (bitrate, packet loss, fps).

        Many cameras don't expose a `bit_rate` value via ffprobe. As a
        fallback, run a short ffmpeg copy and parse the `bitrate=N kbits/s`
        line from stderr — that's a real measurement of the live stream.
        """
        try:
            from app.services.ffmpeg_manager import ffmpeg_manager
            from app.database import async_session_maker
            from app.cameras.models import CameraHealthSnapshot
            import uuid as _uuid

            info = await ffmpeg_manager.test_rtsp_connection(camera.main_stream_url)
            if not info or not info[0]:
                return

            stream_info = info[1] or {}
            bitrate_raw = stream_info.get("bitrate")
            kbps = int(bitrate_raw) // 1000 if bitrate_raw else None

            # Fallback — measure live bitrate via short ffmpeg copy
            if kbps is None:
                kbps = await self._measure_bitrate_kbps(camera.main_stream_url)

            async with async_session_maker() as db:
                snap = CameraHealthSnapshot(
                    id=str(_uuid.uuid4()),
                    camera_id=camera.id,
                    bitrate_kbps=kbps,
                    fps_actual=stream_info.get("fps"),
                    status="online",
                )
                db.add(snap)

                # Persist stream metadata onto the camera row so the UI shows
                # resolution/fps without requiring a manual test-connection.
                from app.cameras.models import Camera as _Camera
                row = await db.get(_Camera, camera.id)
                if row is not None:
                    res = stream_info.get("resolution")
                    fps = stream_info.get("fps")
                    bitrate = stream_info.get("bitrate")
                    if res and row.resolution != res:
                        row.resolution = res
                    if fps:
                        fps_int = int(float(fps))
                        if row.fps != fps_int:
                            row.fps = fps_int
                    if bitrate is not None and str(row.bitrate or "") != str(bitrate):
                        row.bitrate = str(bitrate)
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

    async def _probe_credentials(
        self,
        camera_id: str,
        onvif_host: str,
        onvif_port: int,
        onvif_username_enc: Optional[str],
        onvif_password_enc: Optional[str],
    ):
        """
        Probe ONVIF credentials by calling GetProfiles (requires auth).
        Updates Camera.credentials_status: "ok" | "unauthorized" | "unreachable".
        Fires a camera_credentials_invalid event on ok → unauthorized transition.
        """
        try:
            from app.core.crypto import decrypt_value
            from app.cameras.models import Camera
            from sqlalchemy import select

            username = decrypt_value(onvif_username_enc) if onvif_username_enc else "admin"
            password = decrypt_value(onvif_password_enc) if onvif_password_enc else ""

            import onvif as _onvif_module

            def _do_probe():
                try:
                    cam = _onvif_module.ONVIFCamera(
                        onvif_host, onvif_port, username, password,
                        no_cache=True,
                    )
                    # Lightweight: does not require auth
                    cam.devicemgmt.GetSystemDateAndTime()
                    # Requires auth — will raise if credentials are wrong
                    media = cam.create_media_service()
                    media.GetProfiles()
                    return "ok"
                except Exception as exc:
                    msg = str(exc).lower()
                    if "not authorized" in msg or "401" in msg or "sender" in msg:
                        return "unauthorized"
                    return "unreachable"

            new_status = await asyncio.to_thread(_do_probe)

            async with async_session_maker() as db:
                result = await db.execute(select(Camera).where(Camera.id == camera_id))
                cam_row = result.scalar_one_or_none()
                if cam_row is None:
                    return

                prev_status = cam_row.credentials_status
                cam_row.credentials_status = new_status
                cam_row.credentials_checked_at = datetime.utcnow()

                # Fire event on ok → unauthorized transition
                if new_status == "unauthorized" and prev_status != "unauthorized":
                    logger.warning(
                        "[%s] ONVIF credentials invalid (unauthorized). "
                        "Previous status: %s", camera_id, prev_status
                    )
                    try:
                        from app.events.linkage_service import linkage_engine
                        await linkage_engine.fire_event(
                            camera_id=camera_id,
                            event_type="camera_credentials_invalid",
                            severity="warning",
                            title=f"Credentials invalid — {cam_row.name}",
                            description=(
                                "ONVIF GetProfiles returned 401 Unauthorized. "
                                "Rotate the camera password to restore service."
                            ),
                        )
                    except Exception as _ee:
                        logger.debug("[%s] Event fire failed: %s", camera_id, _ee)

                await db.commit()
                logger.debug("[%s] Credential probe: %s", camera_id, new_status)

        except Exception as exc:
            logger.debug("[%s] _probe_credentials error: %s", camera_id, exc)

    async def _start_motion_detection(self, camera_id, detect_url, motion_config, dewarp_config):
        """Register the detect stream with go2rtc and start the motion detector.

        Used by the monitor to auto-enable motion detection for cameras whose
        recording_mode is 'motion' (so a mode switch alone is enough — the
        operator doesn't have to separately toggle the motion-config switch).
        """
        try:
            from app.services.go2rtc_manager import go2rtc_manager
            from app.services.motion_service import motion_detector
            await go2rtc_manager.add_stream(
                f"{camera_id}_detect", detect_url, dewarp_config=dewarp_config,
            )
            rtsp_url = go2rtc_manager.get_rtsp_output_url(f"{camera_id}_detect")
            await motion_detector.start_detection(camera_id, rtsp_url, motion_config or {})
        except Exception as e:
            logger.warning(f"[{camera_id}] Motion detection auto-start failed: {e}")

    async def _start_camera_recording(self, db, camera):
        """Helper to start recording for a camera with proper setup."""
        from app.license.service import get_license_service

        if not get_license_service().has_feature("recording"):
            logger.info("[%s] Recording auto-start skipped: feature not licensed", camera.id)
            camera.is_recording = False
            camera.status = "online"
            return

        from app.services.ffmpeg_manager import ffmpeg_manager
        from app.services.go2rtc_manager import go2rtc_manager
        from app.storage.service import StorageService

        camera.retry_count += 1
        camera.last_retry_at = datetime.utcnow()

        try:
            # Register streams with go2rtc and wait for ready
            ok = await go2rtc_manager.add_stream(camera.id, camera.main_stream_url, dewarp_config=camera.dewarp_config)
            if not ok:
                raise RuntimeError("go2rtc add_stream failed for main stream")
            if camera.sub_stream_url:
                ok_sub = await go2rtc_manager.add_stream(f"{camera.id}_sub", camera.sub_stream_url, dewarp_config=camera.dewarp_config)
                if not ok_sub:
                    logger.warning(f"[{camera.id}] go2rtc sub-stream registration failed — continuing without failover")

            # Wait for go2rtc to establish the RTSP pull before starting FFmpeg
            ready = await go2rtc_manager.wait_for_stream_ready(camera.id)
            if not ready:
                raise RuntimeError("go2rtc stream not ready")

            rtsp_url = go2rtc_manager.get_rtsp_output_url(camera.id)
            sub_rtsp_url = go2rtc_manager.get_rtsp_output_url(f"{camera.id}_sub") if camera.sub_stream_url else None
            storage_path = await StorageService.resolve_recording_path(db, camera)

            # N5: record from sub-stream when operator opts in and sub is available
            record_url = rtsp_url
            if getattr(camera, "record_substream", False) and sub_rtsp_url:
                record_url = sub_rtsp_url
                logger.info(f"[{camera.id}] Recording from sub-stream (record_substream=True)")

            success, _ = await ffmpeg_manager.start_recording(
                camera.id, record_url, storage_path, camera.recording_fps,
                sub_stream_url=sub_rtsp_url,
                privacy_masks=camera.privacy_masks,
                pos_overlay_config=camera.pos_overlay_config,
            )

            if success:
                camera.status = "online"
                camera.retry_count = 0
                logger.info(f"[{camera.id}] Recording started successfully")
            else:
                camera.status = "error"
                logger.warning(f"[{camera.id}] Failed to start recording")
        except Exception as e:
            camera.status = "error"
            logger.warning(f"[{camera.id}] Recording setup failed: {e}")


# Module singleton
camera_monitor = CameraMonitor()
