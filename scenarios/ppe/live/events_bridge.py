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
import socket
import threading
import time

logger = logging.getLogger("ppe.events_bridge")

EVENTS_STREAM = "ai:events"
GROUP = "ppe-bridge"


class _TransientDBError(Exception):
    """The DB isn't ready / a transient DB blip — the event must NOT be acked, so it is
    redelivered once the DB recovers (instead of being silently lost)."""


def _redis_url() -> str:
    return os.environ.get("AI_REDIS_URL", "redis://redis:6379/1")


def _db_ready() -> bool:
    try:
        from db.engine import db_ready
        return bool(db_ready())
    except Exception:  # noqa: BLE001
        return False


class EventsBridge:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # STABLE consumer id (hostname, not pid) so a restart resumes the SAME consumer and
        # re-reads its own pending entries instead of orphaning them.
        self._consumer = f"ppe-bridge-{socket.gethostname()}"

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
        # socket_timeout must exceed the XREADGROUP block (5s) or every idle read raises.
        r = redis.from_url(_redis_url(), decode_responses=True, socket_timeout=10)
        # id="0" on FIRST creation so a freshly-created group consumes any backlog already
        # on the stream (events emitted before the group existed are NOT lost). BUSYGROUP
        # (already exists) leaves the steady-state resume-from-last-ack untouched.
        try:
            r.xgroup_create(EVENTS_STREAM, GROUP, id="0", mkstream=True)
        except Exception as e:  # noqa: BLE001
            if "BUSYGROUP" not in str(e):
                logger.warning("[ppe-bridge] xgroup_create: %s", e)
        while not self._stop.is_set():
            # Don't read (and therefore can't ack-and-lose) until the DB is ready.
            if not _db_ready():
                self._stop.wait(1.0)
                continue
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
                    except _TransientDBError as e:
                        # DB blip — do NOT ack; the entry stays pending and is redelivered.
                        logger.warning("[ppe-bridge] transient, will retry (%s): %s", entry_id, e)
                        time.sleep(1.0)
                        continue
                    except Exception as e:  # noqa: BLE001 — poison event: log + ack + skip
                        logger.exception("[ppe-bridge] poison event dropped (%s): %s", entry_id, e)
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
        try:
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
        except Exception as e:  # noqa: BLE001
            # A DB connectivity / transient error must NOT be acked (else the event is lost
            # forever). Re-raise as transient so the caller leaves it pending for redelivery.
            from sqlalchemy.exc import DBAPIError, OperationalError
            if isinstance(e, (OperationalError, DBAPIError)):
                raise _TransientDBError(str(e)) from e
            raise   # genuine poison (bad payload etc.) — caller acks + logs


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
