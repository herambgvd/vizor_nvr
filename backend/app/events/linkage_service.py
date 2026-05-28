# =============================================================================
# Event Linkage Engine — evaluates rules and executes actions on events
# =============================================================================

import asyncio
import logging
import time
from typing import Optional, Dict, Any

from app.database import async_session_maker
from app.events.service import EventService

logger = logging.getLogger(__name__)


class LinkageEngine:
    """
    When an event fires, this engine:
    1. Persists the event to the DB
    2. Broadcasts it via WebSocket
    3. Finds matching linkage rules
    4. Executes each rule's action list (respecting cooldown)
    """

    def __init__(self):
        # rule_id → last fire timestamp (for cooldown)
        self._last_fired: Dict[str, float] = {}

    async def fire_event(
        self,
        camera_id: Optional[str],
        event_type: str,
        severity: str,
        title: str,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        snapshot_path: Optional[str] = None,
        recording_id: Optional[str] = None,
    ):
        """
        Central entry point for all system events.
        Creates the event, broadcasts it, and triggers matching linkage rules.
        """
        try:
            async with async_session_maker() as db:
                # 1. Persist event
                event = await EventService.create_event_direct(
                    db,
                    camera_id=camera_id,
                    event_type=event_type,
                    severity=severity,
                    title=title,
                    description=description,
                    metadata=metadata,
                    snapshot_path=snapshot_path,
                    recording_id=recording_id,
                )

                # 2. Broadcast via WebSocket
                from app.core.websocket import ws_manager
                await ws_manager.broadcast("events", {
                    "type": "new_event",
                    "data": {
                        "id": event.id,
                        "camera_id": event.camera_id,
                        "event_type": event.event_type,
                        "severity": event.severity,
                        "title": event.title,
                        "description": event.description,
                        "triggered_at": event.triggered_at.isoformat() if event.triggered_at else None,
                    },
                })

                # 3. Find and execute matching rules
                rules = await EventService.get_active_rules_for_trigger(
                    db, event_type, camera_id
                )
                for rule in rules:
                    await self._execute_rule(rule, event, camera_id)

                # 4. Push into ONVIF PullPoint subscription queues so VMS clients
                # receive NVR-internal events (motion, tamper, etc.) via ONVIF.
                try:
                    from app.onvif_device.service import inject_nvr_event
                    await inject_nvr_event(
                        camera_id=camera_id,
                        event_type=event_type,
                        severity=severity,
                        title=title,
                        metadata=metadata,
                    )
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"LinkageEngine.fire_event error: {e}", exc_info=True)

    async def _execute_rule(self, rule, event, camera_id: Optional[str]):
        """Execute a single linkage rule's actions if cooldown allows."""
        now = time.time()
        last = self._last_fired.get(rule.id, 0)
        if (now - last) < rule.cooldown_seconds:
            logger.debug(f"Rule '{rule.name}' skipped (cooldown)")
            return

        self._last_fired[rule.id] = now

        actions = rule.actions or []
        for action_cfg in actions:
            action_type = action_cfg.get("action") if isinstance(action_cfg, dict) else None
            config = action_cfg.get("config", {}) if isinstance(action_cfg, dict) else {}
            if not action_type:
                continue

            try:
                await self._execute_action(action_type, config, event, camera_id)
            except Exception as e:
                logger.error(
                    f"Rule '{rule.name}' action '{action_type}' failed: {e}"
                )

    async def _execute_action(
        self, action_type: str, config: dict, event, camera_id: Optional[str]
    ):
        """Execute a single action."""
        if action_type == "start_recording":
            await self._action_start_recording(camera_id, config)
        elif action_type == "send_email":
            await self._action_send_email(event, config)
        elif action_type == "send_webhook":
            await self._action_send_webhook(event, config)
        elif action_type == "notify_channel":
            await self._action_notify_channel(event, config)
        elif action_type == "trigger_alarm_output":
            await self._action_trigger_alarm_output(camera_id, config, event)
        else:
            logger.warning(f"Unknown linkage action: {action_type}")

    async def _action_start_recording(self, camera_id: Optional[str], config: dict):
        """Start buffer recording for the camera using prebuffer + post-recording."""
        if not camera_id:
            return
        from app.services.ffmpeg_manager import ffmpeg_manager
        from app.services.prebuffer_service import prebuffer_service

        pre_seconds = config.get("pre_seconds", 30)
        post_seconds = config.get("post_seconds", 30)
        trigger_type = config.get("trigger_type", "event")

        async with async_session_maker() as db:
            from app.cameras.models import Camera
            from app.services.go2rtc_manager import go2rtc_manager
            from app.storage.service import StorageService
            from sqlalchemy import select

            result = await db.execute(select(Camera).where(Camera.id == camera_id))
            camera = result.scalar_one_or_none()
            if not camera:
                return

            await go2rtc_manager.add_stream(camera.id, camera.main_stream_url, dewarp_config=camera.dewarp_config)
            rtsp_url = go2rtc_manager.get_rtsp_output_url(camera.id)
            storage_path = await StorageService.resolve_recording_path(db, camera)

            # If continuous recording is already active, just tag the event
            if ffmpeg_manager.is_recording(camera_id):
                logger.debug(f"Camera {camera_id} already recording, tagging event")
                # Fire event marker on current segment (handled by motion service)
                return

            # Use prebuffer service for motion-triggered cameras
            if camera.recording_mode == "motion" and prebuffer_service.is_running(camera_id):
                # Flush prebuffer (pre-event footage)
                await prebuffer_service.flush_prebuffer(
                    camera_id, storage_path,
                    max_age_seconds=camera.pre_buffer_seconds or pre_seconds,
                )
                # Start post-event recording
                await prebuffer_service.start_post_recording(
                    camera_id=camera_id,
                    rtsp_url=rtsp_url,
                    recording_dir=storage_path,
                    post_seconds=camera.post_buffer_seconds or post_seconds,
                    recording_fps=camera.recording_fps,
                )
            else:
                # Fallback: standard buffer recording
                await ffmpeg_manager.start_buffer_recording(
                    camera.id, rtsp_url, storage_path,
                    pre_seconds=pre_seconds,
                    post_seconds=post_seconds,
                    trigger_type=trigger_type,
                )

    async def _action_send_email(self, event, config: dict):
        """Send email notification with optional snapshot via the notification service."""
        from app.notifications.service import notification_service
        from app.notifications.models import NotificationEvent as NE

        # Map event type to notification event
        ne_map = {
            "motion_detected": NE.CAMERA_ERROR,
            "video_loss": NE.CAMERA_OFFLINE,
            "camera_tamper": NE.CAMERA_ERROR,
            "camera_offline": NE.CAMERA_OFFLINE,
        }
        ne = ne_map.get(event.event_type, NE.SYSTEM_ERROR)

        # Capture snapshot if camera is online
        snapshot_path = None
        if event.camera_id:
            try:
                from app.services.ffmpeg_manager import ffmpeg_manager
                from app.database import async_session_maker
                from app.cameras.models import Camera
                from sqlalchemy import select
                async with async_session_maker() as db:
                    result = await db.execute(select(Camera).where(Camera.id == event.camera_id))
                    camera = result.scalar_one_or_none()
                    if camera and camera.main_stream_url:
                        snapshot_path = await ffmpeg_manager.capture_snapshot(
                            camera.main_stream_url, event.camera_id
                        )
            except Exception as e:
                logger.debug(f"Snapshot capture for email failed: {e}")

        await notification_service.notify(ne, {
            "camera_id": event.camera_id,
            "event_type": event.event_type,
            "title": event.title,
            "description": event.description or "",
            "snapshot_path": snapshot_path,
        }, camera_id=event.camera_id)

    async def _action_send_webhook(self, event, config: dict):
        """Forward event to configured webhook URL."""
        url = config.get("url")
        if not url:
            return
        import httpx
        payload = {
            "event_id": event.id,
            "event_type": event.event_type,
            "severity": event.severity,
            "title": event.title,
            "camera_id": event.camera_id,
            "triggered_at": event.triggered_at.isoformat() if event.triggered_at else None,
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(url, json=payload)
        except Exception as e:
            logger.warning(f"Webhook action failed ({url}): {e}")

    async def _action_trigger_alarm_output(self, camera_id: Optional[str], config: dict, event):
        """
        Trigger a relay output on the camera via ONVIF SetRelayOutputState.
        config: {"relay_token": "RelayOut1", "state": "active", "release_after_seconds": 5}
        Falls back to camera's first relay output if no token specified.
        """
        if not camera_id:
            logger.warning("trigger_alarm_output: no camera_id")
            return

        relay_token = config.get("relay_token")
        state = config.get("state", "active")
        release_after = config.get("release_after_seconds", 0)

        async with async_session_maker() as db:
            from app.cameras.models import Camera
            from app.core.crypto import decrypt_value
            from app.cameras.onvif_service import onvif_service
            from sqlalchemy import select

            result = await db.execute(select(Camera).where(Camera.id == camera_id))
            camera = result.scalar_one_or_none()
            if not camera or not camera.onvif_host:
                logger.warning(f"trigger_alarm_output: camera {camera_id} has no ONVIF")
                return

            # If no token configured, use first cached relay output
            if not relay_token and camera.relay_outputs:
                relay_token = camera.relay_outputs[0].get("token", "RelayOut1")
            if not relay_token:
                relay_token = "RelayOut1"

            password = decrypt_value(camera.onvif_password) if camera.onvif_password else "admin"
            ok = await onvif_service.set_relay_output_state(
                camera.onvif_host, camera.onvif_port,
                camera.onvif_username or "admin", password,
                relay_token=relay_token,
                logical_state=state,
            )
            if ok:
                logger.info(f"Relay output {relay_token} set to '{state}' on camera {camera_id}")
                # Auto-release after delay
                if release_after > 0 and state == "active":
                    async def _release():
                        import asyncio as _aio
                        await _aio.sleep(release_after)
                        await onvif_service.set_relay_output_state(
                            camera.onvif_host, camera.onvif_port,
                            camera.onvif_username or "admin", password,
                            relay_token=relay_token,
                            logical_state="inactive",
                        )
                    import asyncio as _aio
                    _aio.create_task(_release())
            else:
                logger.error(f"trigger_alarm_output: SetRelayOutputState failed for {camera_id}")

    async def _action_notify_channel(self, event, config: dict):
        """Broadcast to a specific WebSocket channel."""
        from app.core.websocket import ws_manager
        channel = config.get("channel", "system")
        await ws_manager.broadcast(channel, {
            "type": "linkage_event",
            "data": {
                "event_id": event.id,
                "event_type": event.event_type,
                "severity": event.severity,
                "title": event.title,
                "camera_id": event.camera_id,
            },
        })


# Module singleton
linkage_engine = LinkageEngine()
