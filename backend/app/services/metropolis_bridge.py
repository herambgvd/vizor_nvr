# =============================================================================
# Metropolis Bridge
#
# Consumes detection events from a Metropolis Microservice (Perception,
# Behavior Analytics) via Redis Streams (nvmsgbroker output) and posts
# them in batches to the NVR /api/events/ingest endpoint.
#
# Why a bridge and not direct DB writes:
#   - Keeps Metropolis as a black-box service. Schema changes upstream
#     are absorbed here.
#   - /api/events/ingest already has API-key auth + idempotency + metrics
#   - Background workers can run on separate replicas without DB schema
#     coupling.
#
# Architecture:
#   nvmsgbroker → Redis Stream "metropolis:events" (consumer group "nvr-bridge")
#     → MetropolisBridge.consume()
#       → transform (Metropolis schema → NVR IngestEvent)
#       → buffer up to BATCH_SIZE or BATCH_WINDOW_SECS
#       → POST /api/events/ingest with API key
#     → XACK on success, retry on transient failure, DLQ after N attempts
#
# Operate via env vars:
#   METROPOLIS_BRIDGE_ENABLED        — "true" to start as background task
#   METROPOLIS_REDIS_URL             — default redis://redis:6379/0
#   METROPOLIS_STREAM                — default "metropolis:events"
#   METROPOLIS_GROUP                 — default "nvr-bridge"
#   METROPOLIS_CONSUMER              — default hostname
#   METROPOLIS_DLQ_STREAM            — default "metropolis:events:dlq"
#   NVR_INGEST_URL                   — default http://localhost:8000
#   NVR_INGEST_API_KEY               — required; vzn_* key with events:ingest scope
#   METROPOLIS_BATCH_SIZE            — default 50
#   METROPOLIS_BATCH_WINDOW_SECS     — default 1.0
# =============================================================================

import asyncio
import hashlib
import json
import logging
import os
import socket
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

try:
    import redis.asyncio as aioredis
except ImportError:  # redis-py with asyncio support
    aioredis = None  # type: ignore


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration (env-driven)
# ---------------------------------------------------------------------------

REDIS_URL = os.environ.get("METROPOLIS_REDIS_URL", "redis://redis:6379/0")
STREAM = os.environ.get("METROPOLIS_STREAM", "metropolis:events")
GROUP = os.environ.get("METROPOLIS_GROUP", "nvr-bridge")
CONSUMER = os.environ.get("METROPOLIS_CONSUMER", socket.gethostname())
DLQ_STREAM = os.environ.get("METROPOLIS_DLQ_STREAM", "metropolis:events:dlq")

INGEST_URL = os.environ.get("NVR_INGEST_URL", "http://localhost:8000").rstrip("/")
INGEST_API_KEY = os.environ.get("NVR_INGEST_API_KEY", "")

BATCH_SIZE = int(os.environ.get("METROPOLIS_BATCH_SIZE", "50"))
BATCH_WINDOW_SECS = float(os.environ.get("METROPOLIS_BATCH_WINDOW_SECS", "1.0"))
MAX_DELIVERY_ATTEMPTS = int(os.environ.get("METROPOLIS_MAX_ATTEMPTS", "5"))
READ_BLOCK_MS = int(os.environ.get("METROPOLIS_READ_BLOCK_MS", "1000"))


# ---------------------------------------------------------------------------
# Translation: Metropolis → NVR IngestEvent
# ---------------------------------------------------------------------------

def _parse_ts(val: Any) -> datetime:
    if val is None:
        return datetime.utcnow()
    if isinstance(val, (int, float)):
        # nvmsgbroker emits unix-ms; tolerate seconds too
        if val > 1_000_000_000_000:
            return datetime.fromtimestamp(val / 1000.0, tz=timezone.utc).replace(tzinfo=None)
        return datetime.fromtimestamp(val, tz=timezone.utc).replace(tzinfo=None)
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
    return datetime.utcnow()


def _dedup_key(payload: dict[str, Any]) -> str:
    """Idempotency key — workers retrying the same logical detection must
    produce the same hash. Same scheme used by /api/events/ingest dedup."""
    parts = [
        str(payload.get("sensorId") or payload.get("camera_id") or "unknown"),
        str(payload.get("type") or payload.get("detection_type") or "event"),
        str(payload.get("trackingId") or payload.get("track_id") or ""),
        str(payload.get("timestamp") or payload.get("triggered_at") or ""),
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def _scenario_to_service(scenario_slug: str | None) -> str:
    """Map our scenario slug to a NVR source_service tag."""
    if not scenario_slug:
        return "metropolis"
    return f"metropolis-{scenario_slug}"


def metropolis_to_ingest_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Translate a single Metropolis schema document into the NVR
    /api/events/ingest body.

    Metropolis-schema reference (DeepStream nvmsgconv minimal subset):
      sensorId         camera id
      timestamp        ISO8601 or unix-ms
      type             detection class (Person, Vehicle, FaceMatch, etc.)
      object.bbox      [x, y, w, h] (px or normalized depending on emitter)
      object.id        tracker id
      analyticsModule  scenario slug from our DS config
      confidence       0..1
      personId         FRS gallery match (resolved by Metropolis or bridge)
      attributes       free-form dict
    """
    obj = payload.get("object") or {}
    scenario = payload.get("analyticsModule") or payload.get("scenario")
    detection_type = (
        payload.get("type") or obj.get("type") or scenario or "detection"
    )

    bbox = obj.get("bbox") or payload.get("bbox")
    if isinstance(bbox, dict):  # accept {x,y,w,h} dict form too
        bbox = [bbox.get("x", 0), bbox.get("y", 0), bbox.get("w", 0), bbox.get("h", 0)]

    return {
        "dedup_key": _dedup_key(payload),
        "camera_id": payload.get("sensorId") or payload.get("camera_id"),
        "event_type": detection_type.lower() if isinstance(detection_type, str) else "detection",
        "severity": payload.get("severity") or "info",
        "title": payload.get("title") or f"{detection_type} detected",
        "description": payload.get("description"),
        "source_service": _scenario_to_service(scenario),
        "detection_type": detection_type if isinstance(detection_type, str) else None,
        "confidence": payload.get("confidence") or obj.get("confidence"),
        "bbox": bbox,
        "track_id": str(obj.get("id") or payload.get("trackingId") or "") or None,
        "person_id": payload.get("personId") or payload.get("person_id"),
        "attributes": payload.get("attributes") or obj.get("attributes"),
        "triggered_at": _parse_ts(payload.get("timestamp")).isoformat(),
    }


# ---------------------------------------------------------------------------
# Bridge service
# ---------------------------------------------------------------------------

class MetropolisBridge:
    """Long-running consumer that reads from Redis Stream, batches, POSTs."""

    def __init__(
        self,
        redis_url: str = REDIS_URL,
        stream: str = STREAM,
        group: str = GROUP,
        consumer: str = CONSUMER,
        ingest_url: str = INGEST_URL,
        api_key: str = INGEST_API_KEY,
        batch_size: int = BATCH_SIZE,
        batch_window_secs: float = BATCH_WINDOW_SECS,
    ) -> None:
        self.redis_url = redis_url
        self.stream = stream
        self.group = group
        self.consumer = consumer
        self.ingest_url = ingest_url.rstrip("/")
        self.api_key = api_key
        self.batch_size = batch_size
        self.batch_window_secs = batch_window_secs

        self._redis: Optional["aioredis.Redis"] = None
        self._http: Optional[httpx.AsyncClient] = None
        self._stop = asyncio.Event()

    # ── Lifecycle ───────────────────────────────────────────────────────

    async def start(self) -> None:
        if aioredis is None:
            raise RuntimeError("redis>=5 with asyncio extras is required")
        if not self.api_key:
            raise RuntimeError("NVR_INGEST_API_KEY env var must be set")

        self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
        self._http = httpx.AsyncClient(
            base_url=self.ingest_url,
            headers={"X-Vizor-API-Key": self.api_key},
            timeout=httpx.Timeout(10.0, connect=3.0),
        )

        # Create consumer group (idempotent — ignore BUSYGROUP)
        try:
            await self._redis.xgroup_create(
                self.stream, self.group, id="0", mkstream=True
            )
            logger.info("Created consumer group %s on %s", self.group, self.stream)
        except Exception as e:  # noqa: BLE001
            if "BUSYGROUP" not in str(e):
                raise
            logger.debug("Consumer group %s already exists", self.group)

    async def stop(self) -> None:
        self._stop.set()
        if self._http is not None:
            await self._http.aclose()
        if self._redis is not None:
            await self._redis.aclose()
        logger.info("Metropolis bridge stopped")

    # ── Consume loop ────────────────────────────────────────────────────

    async def run_forever(self) -> None:
        """Main loop. Reads, batches by size or time window, posts to NVR."""
        logger.info(
            "Metropolis bridge starting (stream=%s, group=%s, consumer=%s)",
            self.stream, self.group, self.consumer,
        )

        buffer: list[tuple[str, dict[str, Any]]] = []  # (entry_id, ingest_event)
        last_flush = asyncio.get_event_loop().time()

        while not self._stop.is_set():
            # Read at most batch_size at a time, blocking up to READ_BLOCK_MS
            try:
                entries = await self._redis.xreadgroup(  # type: ignore
                    self.group,
                    self.consumer,
                    {self.stream: ">"},
                    count=self.batch_size,
                    block=READ_BLOCK_MS,
                )
            except Exception:  # noqa: BLE001
                logger.exception("xreadgroup failed; retrying in 1s")
                await asyncio.sleep(1.0)
                continue

            now = asyncio.get_event_loop().time()
            for _stream_name, items in entries or []:
                for entry_id, data in items:
                    try:
                        payload = self._decode_entry(data)
                        ingest_event = metropolis_to_ingest_event(payload)
                        buffer.append((entry_id, ingest_event))
                    except Exception:  # noqa: BLE001
                        logger.exception("Bad payload %s; sending to DLQ", entry_id)
                        await self._dlq(entry_id, data, "decode_error")
                        await self._redis.xack(self.stream, self.group, entry_id)  # type: ignore

            time_window_elapsed = now - last_flush >= self.batch_window_secs
            if len(buffer) >= self.batch_size or (buffer and time_window_elapsed):
                await self._flush(buffer)
                buffer = []
                last_flush = now

        # Drain on shutdown
        if buffer:
            await self._flush(buffer)

    # ── Helpers ─────────────────────────────────────────────────────────

    def _decode_entry(self, data: dict[str, Any]) -> dict[str, Any]:
        """Redis Streams entries are flat dict; payload may be JSON in
        'payload' field or fully expanded as fields. Accept both."""
        if "payload" in data:
            return json.loads(data["payload"])
        # Convert flat dict → nested if needed
        return data

    async def _flush(self, buffer: list[tuple[str, dict[str, Any]]]) -> None:
        if not buffer:
            return

        entry_ids = [eid for eid, _ in buffer]
        events = [ev for _, ev in buffer]

        body = {"events": events}
        attempt = 0
        backoff = 0.5
        while attempt < MAX_DELIVERY_ATTEMPTS:
            attempt += 1
            try:
                resp = await self._http.post("/api/events/ingest", json=body)  # type: ignore
                if resp.status_code == 200:
                    result = resp.json()
                    logger.info(
                        "Ingested batch: inserted=%d skipped=%d failed=%d",
                        result.get("inserted", 0),
                        result.get("skipped", 0),
                        result.get("failed", 0),
                    )
                    # XACK successful entries
                    await self._redis.xack(self.stream, self.group, *entry_ids)  # type: ignore
                    return
                if resp.status_code == 401:
                    logger.error("Ingest API key rejected; check NVR_INGEST_API_KEY")
                    return  # don't retry auth failures
                logger.warning(
                    "Ingest %d (attempt %d/%d): %s",
                    resp.status_code, attempt, MAX_DELIVERY_ATTEMPTS, resp.text[:200],
                )
            except Exception:  # noqa: BLE001
                logger.exception("Ingest POST failed (attempt %d/%d)", attempt, MAX_DELIVERY_ATTEMPTS)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 8.0)

        # Exhausted retries → DLQ each entry
        logger.error("Batch DLQ-ing after %d attempts: %d events", attempt, len(buffer))
        for eid, ev in buffer:
            await self._dlq(eid, ev, "ingest_failed")
            await self._redis.xack(self.stream, self.group, eid)  # type: ignore

    async def _dlq(self, entry_id: str, payload: Any, reason: str) -> None:
        try:
            await self._redis.xadd(  # type: ignore
                DLQ_STREAM,
                {
                    "original_id": entry_id,
                    "reason": reason,
                    "payload": json.dumps(payload, default=str),
                    "ts": datetime.utcnow().isoformat(),
                },
                maxlen=10_000,
                approximate=True,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to write DLQ entry for %s", entry_id)


# ---------------------------------------------------------------------------
# App lifespan glue
# ---------------------------------------------------------------------------

_bridge_singleton: Optional[MetropolisBridge] = None
_bridge_task: Optional[asyncio.Task] = None


async def start_metropolis_bridge() -> None:
    """Called from FastAPI lifespan startup."""
    global _bridge_singleton, _bridge_task

    if os.environ.get("METROPOLIS_BRIDGE_ENABLED", "false").lower() != "true":
        logger.info("Metropolis bridge disabled via env (METROPOLIS_BRIDGE_ENABLED!=true)")
        return

    _bridge_singleton = MetropolisBridge()
    try:
        await _bridge_singleton.start()
    except Exception:  # noqa: BLE001
        logger.exception("Failed to start Metropolis bridge — continuing without it")
        _bridge_singleton = None
        return

    _bridge_task = asyncio.create_task(
        _bridge_singleton.run_forever(),
        name="metropolis-bridge",
    )
    logger.info("Metropolis bridge background task launched")


async def stop_metropolis_bridge() -> None:
    """Called from FastAPI lifespan shutdown."""
    global _bridge_singleton, _bridge_task
    if _bridge_singleton is None:
        return
    await _bridge_singleton.stop()
    if _bridge_task is not None:
        _bridge_task.cancel()
        try:
            await _bridge_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
    _bridge_singleton = None
    _bridge_task = None
