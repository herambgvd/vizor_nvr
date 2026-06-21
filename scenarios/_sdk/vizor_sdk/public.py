"""Generic public dashboard + third-party ingest for any scenario plugin.

Every scenario needs the same two operator features FRS pioneered:
  1. A public (no-auth) realtime analytics dashboard, gated by an operator toggle.
  2. A third-party ingest API (an external system pushes events in), gated by an
     operator-minted API key.

The machinery is identical across scenarios; only the *data* differs (FRS shows
recognized/unknown faces, PPE shows violations, ANPR shows plate reads). So the
SDK owns:
  - SettingsStore  — read/update the singleton settings row (public toggle, ingest
                     toggle, ingest key, show_names) on the plugin's OWN model.
  - EventBus        — in-process pub/sub for the SSE stream (the plugin publishes
                     each event it records).
  - build_public_router(...)  — GET /public/dashboard + /public/stream.
  - build_ingest_router(...)  — POST /ingest/event.

The plugin supplies: its settings SQLAlchemy model + session factory, a
`dashboard()` callable returning the aggregate stats dict, and an `ingest()`
callable that turns a posted payload into a recorded event.
"""
from __future__ import annotations

import hmac
import json
import queue
import secrets
import threading
from typing import Callable, Optional

from fastapi import APIRouter, Body, Header, HTTPException
from fastapi.responses import StreamingResponse


# ── settings store (works on the plugin's own singleton model) ───────────────
class SettingsStore:
    """Read/update the public+ingest settings on a plugin's singleton settings
    row. The row must expose: public_dashboard_enabled, ingest_api_enabled,
    ingest_api_key, public_show_names (bool/str columns).

        store = SettingsStore(session, FooSettings, key_prefix="foo")
    """

    _FIELDS = ("public_dashboard_enabled", "ingest_api_enabled",
               "ingest_api_key", "public_show_names")

    def __init__(self, session_factory: Callable, model, *,
                 singleton_id: str = "singleton", key_prefix: str = "scn"):
        self._session = session_factory
        self._model = model
        self._id = singleton_id
        self._prefix = key_prefix

    def _row(self, s):
        row = s.get(self._model, self._id)
        if row is None:
            row = self._model(id=self._id)
            s.add(row)
            s.commit()
            s.refresh(row)
        return row

    def get(self) -> dict:
        with self._session() as s:
            r = self._row(s)
            return {
                "public_dashboard_enabled": bool(r.public_dashboard_enabled),
                "ingest_api_enabled": bool(r.ingest_api_enabled),
                "ingest_api_key": r.ingest_api_key,
                "public_show_names": bool(r.public_show_names),
            }

    def update(self, **patch) -> dict:
        with self._session() as s:
            r = self._row(s)
            for k, v in patch.items():
                if k in self._FIELDS:
                    setattr(r, k, v)
            # Mint a key the first time ingest is enabled.
            if patch.get("ingest_api_enabled") and not r.ingest_api_key:
                r.ingest_api_key = self._mint()
            s.commit()
        return self.get()

    def rotate_key(self) -> str:
        new_key = self._mint()
        with self._session() as s:
            r = self._row(s)
            r.ingest_api_key = new_key
            s.commit()
        return new_key

    def verify_key(self, presented: Optional[str]) -> bool:
        st = self.get()
        if not st["ingest_api_enabled"] or not st["ingest_api_key"]:
            return False
        return bool(presented) and hmac.compare_digest(
            str(presented), str(st["ingest_api_key"]))

    def _mint(self) -> str:
        return f"{self._prefix}k_" + secrets.token_urlsafe(32)


# ── realtime event bus (for the SSE stream) ──────────────────────────────────
class EventBus:
    """Bounded per-subscriber fan-out. The plugin's record_event publishes a
    small aggregate-safe dict; public_stream subscribers receive it."""

    def __init__(self):
        self._subs: set[queue.Queue] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=100)
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subs.discard(q)

    def publish(self, payload: dict) -> None:
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass  # slow client — drop rather than block the recorder


# ── routers ──────────────────────────────────────────────────────────────────
def build_public_router(
    store: SettingsStore,
    bus: EventBus,
    dashboard: Callable[[dict], dict],
) -> APIRouter:
    """Public (no-auth) dashboard + SSE. `dashboard(settings)` returns the
    aggregate stats dict. Both routes 404 when the public toggle is off."""
    router = APIRouter(prefix="/public", tags=["public"])

    def _guard() -> dict:
        st = store.get()
        if not st["public_dashboard_enabled"]:
            raise HTTPException(404, "not found")
        return st

    @router.get("/dashboard")
    def public_dashboard() -> dict:
        st = _guard()
        return dashboard(st)

    @router.get("/stream")
    def public_stream() -> StreamingResponse:
        _guard()
        q = bus.subscribe()

        def _gen():
            try:
                yield ": connected\n\n"
                while True:
                    try:
                        item = q.get(timeout=20)
                        yield f"data: {json.dumps(item)}\n\n"
                    except queue.Empty:
                        yield ": ping\n\n"
            finally:
                bus.unsubscribe(q)

        return StreamingResponse(
            _gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router


def build_ingest_router(
    store: SettingsStore,
    ingest: Callable[[dict], dict],
    *,
    key_header: str = "x-scn-ingest-key",
) -> APIRouter:
    """Third-party ingest. `ingest(payload)` records the event and returns a
    result dict. Gated by the operator-minted ingest API key."""
    router = APIRouter(prefix="/ingest", tags=["ingest"])

    @router.post("/event")
    def ingest_event(
        body: dict = Body(...),
        ingest_key: Optional[str] = Header(None, alias=key_header),
    ) -> dict:
        if not store.verify_key(ingest_key):
            raise HTTPException(401, "invalid or disabled ingest key")
        return ingest(body)

    return router
