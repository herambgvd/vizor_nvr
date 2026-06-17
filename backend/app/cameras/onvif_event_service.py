# =============================================================================
# ONVIF Event Service — PullPoint subscription + per-camera event pull loop
# =============================================================================
# Implements ONVIF Event Service spec:
#   WS-BaseNotification PullPoint model
#   CreatePullPointSubscription → PullMessages → Renew → Unsubscribe
#
# Runs one async pull task per camera that has onvif_events_enabled=True.
# Parsed events are fed directly into the LinkageEngine (fire_event).
#
# ONVIF Topic → NVR EventType mapping:
#   tns1:VideoSource/MotionAlarm                    → motion_detected
#   tns1:VideoSource/ImageTooBlurry                 → camera_tamper
#   tns1:VideoSource/ImageTooDark                   → camera_tamper
#   tns1:VideoSource/GlobalSceneChange/IVA          → motion_detected
#   tns1:VideoAnalytics/Motion/Alarm                → motion_detected
#   tns1:Device/Trigger/DigitalInput                → digital_input_change
#   tns1:RuleEngine/LineDetector/Crossed            → line_crossing
#   tns1:RuleEngine/FieldDetector/ObjectInside      → zone_intrusion
#   tns1:AudioAnalytics/Audio/DetectedSound         → audio_alarm
#   tns1:VideoAnalytics/FaceDetection/Alarm         → face_detected
#   tns1:VideoSource/ConnectionFailed               → video_loss
# =============================================================================

import asyncio
import logging
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)

try:
    from onvif import ONVIFCamera
    _HAS_ONVIF = True
except ImportError:
    _HAS_ONVIF = False


# ---------------------------------------------------------------------------
# Topic → (event_type, severity, title_template)
# ---------------------------------------------------------------------------

_TOPIC_MAP: Dict[str, tuple] = {
    # Motion
    "tns1:VideoSource/MotionAlarm":               ("motion_detected",    "alarm",    "Motion detected"),
    "tns1:VideoSource/GlobalSceneChange/IVA":     ("motion_detected",    "alarm",    "Scene change detected"),
    "tns1:VideoAnalytics/Motion/Alarm":           ("motion_detected",    "alarm",    "Motion alarm"),
    # Tamper
    "tns1:VideoSource/ImageTooBlurry":            ("camera_tamper",      "alarm",    "Camera tamper — image too blurry"),
    "tns1:VideoSource/ImageTooDark":              ("camera_tamper",      "alarm",    "Camera tamper — image too dark"),
    "tns1:VideoSource/ImageTooBright":            ("camera_tamper",      "warning",  "Camera tamper — image too bright"),
    "tns1:VideoSource/GlobalSceneChange":         ("camera_tamper",      "alarm",    "Global scene change / possible tamper"),
    # Digital I/O
    "tns1:Device/Trigger/DigitalInput":           ("digital_input_change","alarm",   "Digital input triggered"),
    # Analytics
    "tns1:RuleEngine/LineDetector/Crossed":       ("line_crossing",      "alarm",    "Line crossing detected"),
    "tns1:RuleEngine/FieldDetector/ObjectInside": ("zone_intrusion",     "alarm",    "Intrusion detected"),
    "tns1:RuleEngine/CountAggregation/Alarm":     ("zone_intrusion",     "warning",  "Object count alarm"),
    # Audio
    "tns1:AudioAnalytics/Audio/DetectedSound":    ("audio_alarm",        "alarm",    "Audio alarm detected"),
    # Face
    "tns1:VideoAnalytics/FaceDetection/Alarm":    ("face_detected",      "info",     "Face detected"),
    # Video signal
    "tns1:VideoSource/ConnectionFailed":          ("video_loss",         "critical", "Video signal lost"),
    # Thermal
    "tns1:ThermalService/TemperatureAlarm":       ("system_error",       "alarm",    "Temperature alarm"),
}


def _resolve_topic(raw_topic: str) -> Optional[tuple]:
    """Match a raw ONVIF topic string against the map (prefix match)."""
    raw = raw_topic.strip()
    # Exact match first
    if raw in _TOPIC_MAP:
        return _TOPIC_MAP[raw]
    # Prefix match — walk up the topic hierarchy
    parts = raw.rsplit("/", 1)
    while parts:
        candidate = parts[0]
        if candidate in _TOPIC_MAP:
            return _TOPIC_MAP[candidate]
        if "/" not in candidate:
            break
        parts = candidate.rsplit("/", 1)
    if any(part in raw for part in ("VideoAnalytics", "RuleEngine", "AudioAnalytics")):
        return ("onvif_metadata", "info", "ONVIF metadata event")
    return None


def _extract_topic_from_message(msg: Any) -> Optional[str]:
    """Pull the Topic string out of a ONVIF NotificationMessage zeep object."""
    try:
        return str(msg.Topic._value_1)
    except Exception:
        pass
    try:
        return str(msg.Topic)
    except Exception:
        return None


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    try:
        public = {
            key: _json_safe(val)
            for key, val in vars(value).items()
            if not key.startswith("_")
        }
        if public:
            return public
    except Exception:
        pass
    return str(value)


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, (str, bytes, dict)):
        return [value]
    try:
        return list(value)
    except TypeError:
        return [value]


def _simple_items_to_dict(container: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not container or not hasattr(container, "SimpleItem"):
        return out
    for item in _as_list(container.SimpleItem):
        name = getattr(item, "Name", None)
        if not name:
            continue
        out[str(name)] = _json_safe(getattr(item, "Value", None))
    return out


def _element_items_to_dict(container: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not container or not hasattr(container, "ElementItem"):
        return out
    for item in _as_list(container.ElementItem):
        name = getattr(item, "Name", None)
        if not name:
            continue
        out[str(name)] = _json_safe(getattr(item, "Value", item))
    return out


def _extract_metadata(msg: Any) -> dict:
    """Extract JSON-safe Profile M/PullPoint metadata from NotificationMessage."""
    meta: dict = {"onvif": {"source": {}, "data": {}, "elements": {}}}
    try:
        # ProducerReference → camera source reference
        if hasattr(msg, "ProducerReference") and msg.ProducerReference:
            meta["source"] = str(msg.ProducerReference.Address)
            meta["onvif"]["producer_reference"] = str(msg.ProducerReference.Address)
    except Exception:
        pass
    try:
        message = msg.Message.Message
        source_items = _simple_items_to_dict(getattr(message, "Source", None))
        data_items = _simple_items_to_dict(getattr(message, "Data", None))
        element_items = _element_items_to_dict(getattr(message, "Data", None))
        meta["onvif"]["source"] = source_items
        meta["onvif"]["data"] = data_items
        meta["onvif"]["elements"] = element_items
        # Preserve the previous flat shape for existing event filters/linkages.
        meta.update(data_items)
    except Exception:
        pass
    if not meta["onvif"]["source"] and not meta["onvif"]["data"] and not meta["onvif"]["elements"]:
        meta.pop("onvif", None)
    return meta


# ---------------------------------------------------------------------------
# Per-camera pull worker
# ---------------------------------------------------------------------------

class _CameraPullWorker:
    """
    Manages a single camera's ONVIF PullPoint subscription.
    Runs as an asyncio task. Handles:
    - CreatePullPointSubscription
    - Periodic PullMessages (every 2 s)
    - Subscription renewal (every 45 s — ONVIF default TTL is 60 s)
    - Graceful Unsubscribe on stop
    """

    PULL_INTERVAL = 2          # seconds between PullMessages calls
    RENEWAL_INTERVAL = 45      # seconds between subscription renewals
    PULL_TIMEOUT = "PT5S"      # ONVIF pull timeout expressed in ISO 8601 duration
    MAX_MESSAGES = 50          # messages per pull

    def __init__(self, camera_id: str, host: str, port: int, username: str, password: str, topics: list):
        self.camera_id = camera_id
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.topics = topics  # empty list = subscribe to all

        self._task: Optional[asyncio.Task] = None
        self._running = False
        # Consecutive PullMessages failures — escalates from debug to warning so
        # a silently-broken subscription doesn't drop events unnoticed.
        self._pull_failures = 0

    def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name=f"onvif_events_{self.camera_id}")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self):
        while self._running:
            try:
                await self._pull_loop()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[{self.camera_id}] ONVIF event pull failed: {e}. Retrying in 30s")
                await asyncio.sleep(30)

    async def _pull_loop(self):
        """Establish subscription and poll until stopped."""
        pullpoint, subscription_mgr = await asyncio.to_thread(self._create_subscription)
        if pullpoint is None:
            logger.warning(f"[{self.camera_id}] Could not create ONVIF PullPoint subscription")
            await asyncio.sleep(60)
            return

        logger.info(f"[{self.camera_id}] ONVIF PullPoint subscription active")
        last_renewal = asyncio.get_event_loop().time()

        try:
            while self._running:
                now = asyncio.get_event_loop().time()

                # Renew subscription before it expires
                if (now - last_renewal) >= self.RENEWAL_INTERVAL:
                    try:
                        await asyncio.to_thread(self._renew_subscription, subscription_mgr)
                        last_renewal = now
                        logger.debug(f"[{self.camera_id}] ONVIF subscription renewed")
                    except Exception as e:
                        logger.warning(f"[{self.camera_id}] Subscription renewal failed: {e} — recreating subscription")
                        break  # Exit inner loop so _run() recreates the subscription

                # Pull messages
                messages = await asyncio.to_thread(self._pull_messages, pullpoint)
                for msg in messages:
                    await self._handle_message(msg)

                await asyncio.sleep(self.PULL_INTERVAL)
        finally:
            # Unsubscribe cleanly on exit
            try:
                await asyncio.to_thread(self._unsubscribe, subscription_mgr)
                logger.info(f"[{self.camera_id}] ONVIF subscription terminated")
            except Exception:
                pass

    def _create_subscription(self):
        """Blocking: create PullPoint subscription on the camera."""
        try:
            cam = ONVIFCamera(self.host, self.port, self.username, self.password)
            event_service = cam.create_events_service()

            # Build topic filter if specific topics requested.
            # onvif-zeep accepts a plain dict and zeep coerces it.
            req_kwargs = {"InitialTerminationTime": "PT60S"}
            if self.topics:
                topic_exprs = " | ".join(f'"{t}"' for t in self.topics)
                req_kwargs["Filter"] = {
                    "TopicExpression": {
                        "_value_1": topic_exprs,
                        "Dialect": "http://www.onvif.org/ver10/tev/topicExpression/ConcreteSet",
                    }
                }

            # onvif-zeep maps CreatePullPointSubscription via the WSDL —
            # call it as a method, do NOT use create_type (that lookup
            # resolves against the wrong WSDL namespace on some builds).
            result = event_service.CreatePullPointSubscription(req_kwargs)

            # Capture the SubscriptionReference (subscription manager) and
            # build a PullPoint client whose endpoint is the subscription
            # address returned by the device.
            try:
                sub_ref = result.SubscriptionReference
                sub_address = sub_ref.Address._value_1
            except Exception:
                # Some firmwares return Address directly as a string
                sub_address = (
                    str(result.SubscriptionReference.Address)
                    if hasattr(result, "SubscriptionReference")
                    else None
                )
                sub_ref = getattr(result, "SubscriptionReference", None)

            # Re-point a pullpoint service client at the per-subscription
            # endpoint. onvif-zeep's helper handles wsse + zeep binding.
            pullpoint = cam.create_pullpoint_service()
            if sub_address:
                try:
                    pullpoint.zeep_client.transport.session  # touch to ensure init
                    pullpoint.xaddr = sub_address
                except Exception:
                    pass

            return pullpoint, sub_ref

        except Exception as e:
            logger.error(f"[{self.camera_id}] CreatePullPointSubscription error: {e}")
            return None, None

    def _pull_messages(self, pullpoint) -> list:
        """Blocking: PullMessages from the pullpoint."""
        try:
            result = pullpoint.PullMessages({
                "Timeout": self.PULL_TIMEOUT,
                "MessageLimit": self.MAX_MESSAGES,
            })
            self._pull_failures = 0
            return result.NotificationMessage or []
        except Exception as e:
            # A single failure is routine (timeout/transient); a sustained run
            # of failures means events are being silently dropped — escalate.
            self._pull_failures += 1
            if self._pull_failures in (5, 25) or self._pull_failures % 100 == 0:
                logger.warning(
                    f"[{self.camera_id}] PullMessages failing "
                    f"({self._pull_failures} consecutive): {e}"
                )
            else:
                logger.debug(f"[{self.camera_id}] PullMessages error: {e}")
            return []

    def _renew_subscription(self, subscription_mgr_ref):
        """Blocking: renew subscription via Renew request on the subscription manager."""
        try:
            from onvif import ONVIFCamera
            cam = ONVIFCamera(self.host, self.port, self.username, self.password)
            sub_mgr = cam.create_subscription_service()
            if subscription_mgr_ref is not None:
                try:
                    addr = subscription_mgr_ref.Address._value_1
                    sub_mgr.xaddr = addr
                except Exception:
                    pass
            sub_mgr.Renew({"TerminationTime": "PT60S"})
        except Exception as e:
            raise RuntimeError(f"Renew failed: {e}")

    def _unsubscribe(self, subscription_mgr_ref):
        """Blocking: unsubscribe cleanly."""
        try:
            from onvif import ONVIFCamera
            cam = ONVIFCamera(self.host, self.port, self.username, self.password)
            sub_mgr = cam.create_subscription_service()
            if subscription_mgr_ref is not None:
                try:
                    addr = subscription_mgr_ref.Address._value_1
                    sub_mgr.xaddr = addr
                except Exception:
                    pass
            sub_mgr.Unsubscribe()
        except Exception:
            pass

    async def _handle_message(self, msg: Any):
        """Parse a ONVIF NotificationMessage and fire through the linkage engine."""
        topic_raw = _extract_topic_from_message(msg)
        if not topic_raw:
            return

        mapping = _resolve_topic(topic_raw)
        if not mapping:
            logger.debug(f"[{self.camera_id}] Unhandled ONVIF topic: {topic_raw}")
            return

        event_type, severity, title_template = mapping
        meta = _extract_metadata(msg)
        meta["onvif_topic"] = topic_raw

        # Snapshot on alarm events
        snapshot_path = None
        if severity in ("alarm", "critical"):
            try:
                from app.services.ffmpeg_manager import ffmpeg_manager
                snapshot_path = await ffmpeg_manager.capture_snapshot_by_camera_id(self.camera_id)
            except Exception:
                pass

        from app.events.linkage_service import linkage_engine
        await linkage_engine.fire_event(
            camera_id=self.camera_id,
            event_type=event_type,
            severity=severity,
            title=f"{title_template}",
            description=f"ONVIF event from camera: {topic_raw}",
            metadata=meta,
            snapshot_path=snapshot_path,
        )

        # Push event into active PullPoint subscription queues (device server)
        try:
            from app.onvif_device.service import subscription_queues
            if subscription_queues:
                from datetime import datetime, timezone
                evt_payload = {
                    "topic": topic_raw,
                    "camera_id": self.camera_id,
                    "source": meta.get("source", f"camera:{self.camera_id}"),
                    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "value": "true",
                    "metadata": meta,
                }
                for q in list(subscription_queues.values()):
                    try:
                        q.put_nowait(evt_payload)
                    except Exception:
                        pass  # Queue full — drop event
                # Fan-out to BaseNotification push subscribers
                try:
                    from app.onvif_device.service import _enqueue_push_event
                    _enqueue_push_event(evt_payload)
                except Exception:
                    pass
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Service manager — one worker per camera
# ---------------------------------------------------------------------------

class ONVIFEventService:
    """Manages per-camera ONVIF event pull workers."""

    def __init__(self):
        self._workers: Dict[str, _CameraPullWorker] = {}

    async def start_all(self):
        """Start pull workers for all cameras with onvif_events_enabled=True."""
        if not _HAS_ONVIF:
            logger.info("python-onvif-zeep not installed — ONVIF events disabled")
            return
        try:
            from app.database import async_session_maker
            from app.cameras.models import Camera
            from app.core.crypto import decrypt_value
            from sqlalchemy import select

            async with async_session_maker() as db:
                result = await db.execute(
                    select(Camera).where(
                        Camera.is_enabled.is_(True),
                        Camera.onvif_events_enabled.is_(True),
                        Camera.onvif_host.isnot(None),
                    )
                )
                cameras = result.scalars().all()

            for cam in cameras:
                await self.start_camera(
                    cam.id, cam.onvif_host, cam.onvif_port,
                    decrypt_value(cam.onvif_username) if cam.onvif_username else "admin",
                    decrypt_value(cam.onvif_password) if cam.onvif_password else "admin",
                    cam.onvif_event_topics or [],
                )
            logger.info(f"ONVIF event service started ({len(cameras)} cameras)")
        except Exception as e:
            logger.error(f"ONVIF event service start_all error: {e}")

    async def stop_all(self):
        """Stop all pull workers."""
        for camera_id in list(self._workers.keys()):
            await self.stop_camera(camera_id)
        logger.info("ONVIF event service stopped")

    async def start_camera(
        self, camera_id: str, host: str, port: int,
        username: str, password: str, topics: list,
    ):
        """Start (or restart) ONVIF event pull for a single camera."""
        if not _HAS_ONVIF:
            return
        await self.stop_camera(camera_id)
        worker = _CameraPullWorker(camera_id, host, port, username, password, topics)
        worker.start()
        self._workers[camera_id] = worker
        logger.info(f"[{camera_id}] ONVIF event pull started")

    async def stop_camera(self, camera_id: str):
        """Stop the pull worker for a camera."""
        worker = self._workers.pop(camera_id, None)
        if worker:
            await worker.stop()
            logger.info(f"[{camera_id}] ONVIF event pull stopped")

    def is_active(self, camera_id: str) -> bool:
        worker = self._workers.get(camera_id)
        return bool(worker and worker._running and worker._task and not worker._task.done())

    def active_camera_ids(self) -> list:
        return [cid for cid in self._workers if self.is_active(cid)]


# Module singleton
onvif_event_service = ONVIFEventService()
