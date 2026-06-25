"""PPE events bridge — consume `ai:events` and write PPE events into Postgres.

Mirrors the FRS bridge. Runs inside the PPE app (which owns the PPE Postgres), reads
the shared ai:events stream via a consumer group, and maps each PPE Event onto PPE's
record_event (PPEEvent + SSE). A restart resumes from the last ack so no event is
lost. Non-PPE events on the shared stream are acked + skipped.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time

logger = logging.getLogger("ppe.events_bridge")

EVENTS_STREAM = "ai:events"
GROUP = "ppe-bridge"


def _redis_url() -> str:
    return os.environ.get("AI_REDIS_URL", "redis://ai-redis:6379/0")


class EventsBridge:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._consumer = f"ppe-bridge-{os.getpid()}"

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="ppe-events-bridge", daemon=True)
        self._thread.start()
        logger.info("[ppe-bridge] started")

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        import redis
        r = redis.from_url(_redis_url(), decode_responses=True)
        try:
            r.xgroup_create(EVENTS_STREAM, GROUP, id="$", mkstream=True)
        except Exception as e:  # noqa: BLE001
            if "BUSYGROUP" not in str(e):
                logger.warning("[ppe-bridge] xgroup_create: %s", e)
        while not self._stop.is_set():
            try:
                resp = r.xreadgroup(GROUP, self._consumer, {EVENTS_STREAM: ">"},
                                    count=32, block=5000)
            except Exception as e:  # noqa: BLE001
                logger.warning("[ppe-bridge] xreadgroup failed: %s", e)
                time.sleep(1.0)
                continue
            if not resp:
                continue
            for _stream, entries in resp:
                for entry_id, fields in entries:
                    try:
                        self._handle(fields)
                    except Exception as e:  # noqa: BLE001
                        logger.exception("[ppe-bridge] handle failed (%s): %s", entry_id, e)
                    try:
                        r.xack(EVENTS_STREAM, GROUP, entry_id)
                    except Exception:
                        pass

    def _handle(self, fields: dict) -> None:
        raw = fields.get("data") or fields.get("payload")
        if not raw:
            return
        ev = json.loads(raw)
        if ev.get("use_case") != "ppe":
            return
        data = ev.get("data") or {}
        from db.events import record_event
        from schemas import utcnow
        ts = _parse_ts(ev.get("timestamp")) or utcnow()
        record_event(
            ev.get("device_id"),
            ev.get("event_type", "ppe_missing"),
            data.get("worker_track_id"),
            data.get("ppe_item"),
            data.get("missing_items"),
            data.get("present_items"),
            data.get("confidence"),
            data.get("snapshot_path"),
            ts,
            bbox=data.get("bbox"),
        )


def _parse_ts(s):
    if not s:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:  # noqa: BLE001
        return None


_BRIDGE: EventsBridge | None = None


def start_events_bridge() -> EventsBridge:
    global _BRIDGE
    if _BRIDGE is None:
        _BRIDGE = EventsBridge()
        _BRIDGE.start()
    return _BRIDGE
