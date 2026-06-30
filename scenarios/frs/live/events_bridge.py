"""Events bridge — consume `ai:events` and write them into nvr's Postgres.

The FRS Redis worker emits Event objects onto the `ai:events` stream (decoupled,
durable). This bridge runs INSIDE the FRS app (which owns the Postgres gallery +
attendance + transit) and is the only thing that touches the DB for live events:

    ai:events ──XREADGROUP──▶ bridge ──record_event()────▶ FRSEvent + attendance + SSE
                                      └─ on_recognition()─▶ transit sessions

Consumer-group semantics mean a bridge restart resumes from the last acked id, so a
crash never loses a worker-emitted event. Only FRS events (use_case == "frs") are
handled; other scenarios' events on the shared stream are acked and skipped.

It runs on its own thread (daemon) with a synchronous redis client + a fresh asyncio
loop is NOT needed — record_event is sync. Kept simple + resilient: any per-event
error is logged and the message still acked (so one poison event can't wedge the
stream); the original lands nowhere special since the worker's spool already
guarantees emission, not processing.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time

import config

logger = logging.getLogger("frs.events_bridge")

EVENTS_STREAM = "ai:events"
GROUP = "frs-bridge"


class _TransientDBError(Exception):
    """DB not ready / transient blip — the event must NOT be acked so it is redelivered."""


def _redis_url() -> str:
    return os.environ.get("AI_REDIS_URL", "redis://ai-redis:6379/0")


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
        # STABLE consumer id (hostname, not pid) so a restart resumes the same consumer.
        self._consumer = f"frs-bridge-{socket.gethostname()}"

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="frs-events-bridge", daemon=True)
        self._thread.start()
        logger.info("[frs-bridge] started")

    def stop(self) -> None:
        self._stop.set()

    # ── main loop ──────────────────────────────────────────────────────────
    def _run(self) -> None:
        import redis  # sync client — the bridge does blocking DB work anyway
        # socket_timeout must exceed the XREADGROUP block (5s) or every idle read
        # raises "Timeout reading from socket".
        r = redis.from_url(_redis_url(), decode_responses=True, socket_timeout=10)
        # id="0" on FIRST creation so a freshly-created group consumes any backlog already
        # on the stream (events emitted before the group existed are NOT lost). BUSYGROUP
        # leaves steady-state resume-from-last-ack untouched.
        try:
            r.xgroup_create(EVENTS_STREAM, GROUP, id="0", mkstream=True)
        except Exception as e:  # noqa: BLE001
            if "BUSYGROUP" not in str(e):
                logger.warning("[frs-bridge] xgroup_create: %s", e)
        while not self._stop.is_set():
            # Don't read (and therefore can't ack-and-lose) until the DB is ready.
            if not _db_ready():
                self._stop.wait(1.0)
                continue
            try:
                resp = r.xreadgroup(GROUP, self._consumer, {EVENTS_STREAM: ">"},
                                    count=32, block=5000)
            except Exception as e:  # noqa: BLE001
                logger.warning("[frs-bridge] xreadgroup failed: %s", e)
                time.sleep(1.0)
                continue
            if not resp:
                continue
            for _stream, entries in resp:
                for entry_id, fields in entries:
                    try:
                        self._handle(fields)
                    except _TransientDBError as e:
                        logger.warning("[frs-bridge] transient, will retry (%s): %s", entry_id, e)
                        time.sleep(1.0)
                        continue
                    except Exception as e:  # noqa: BLE001 — poison event: log + ack + skip
                        logger.exception("[frs-bridge] poison event dropped (%s): %s", entry_id, e)
                    try:
                        r.xack(EVENTS_STREAM, GROUP, entry_id)
                    except Exception:
                        pass

    def _handle(self, fields: dict) -> None:
        raw = fields.get("data") or fields.get("payload")
        if not raw:
            return
        ev = json.loads(raw)
        if ev.get("use_case") != "frs":
            return  # not ours — ack + skip
        etype = ev.get("event_type")
        data = ev.get("data") or {}
        try:
            self._write(etype, ev, data)
        except Exception as e:  # noqa: BLE001
            from sqlalchemy.exc import DBAPIError, OperationalError
            if isinstance(e, (OperationalError, DBAPIError)):
                raise _TransientDBError(str(e)) from e
            raise

    def _write(self, etype, ev, data) -> None:
        if etype == "transit_drive":
            from live.transit_engine import on_recognition
            from schemas import utcnow
            ts = _parse_ts(ev.get("timestamp")) or utcnow()
            on_recognition(data.get("person_id"), ev.get("device_id"), ts,
                           person_name=data.get("person_name"),
                           snapshot_key=data.get("snapshot_key"))
            return

        # Regular recognition/detection/spoof event -> Postgres.
        from db.events import record_event
        from schemas import utcnow
        ts = _parse_ts(ev.get("timestamp")) or utcnow()
        attributes = dict(data.get("attributes") or {})
        # Preserve the worker-side id so the qdrant snapshot index (written inline in
        # the worker, keyed by that id) can be correlated from Investigate.
        attributes.setdefault("client_event_id", ev.get("id"))
        record_event(
            ev.get("device_id"),
            data.get("person_id"),
            data.get("person_name"),
            data.get("confidence"),
            data.get("snapshot_path"),
            etype,
            ts,
            bbox=data.get("bbox"),
            attributes=attributes,
            direction=data.get("direction"),
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
