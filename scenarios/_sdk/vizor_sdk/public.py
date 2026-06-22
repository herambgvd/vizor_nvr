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

import base64
import binascii
import hmac
import json
import logging
import queue
import secrets
import threading
import uuid
from pathlib import Path
from typing import Callable, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse

logger = logging.getLogger(__name__)

# Cap an ingested image so a caller can't push a giant blob (10 MB decoded).
_MAX_SNAPSHOT_BYTES = 10 * 1024 * 1024
_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def save_ingest_snapshot(snapshot_base64: Optional[str], data_path) -> Optional[str]:
    """Decode a base64 image from an ingest payload, save it under
    <data_path>/snapshots/<uuid>.jpg, and return the snapshot key path
    ("/snapshot?key=ingest:<uuid>") the scenario's /snapshot route serves —
    same scheme the live workers use. Returns None on absent/invalid input
    (ingest still records the event, just without an image).

    Accepts a raw base64 string or a data URL ("data:image/jpeg;base64,...").
    """
    if not snapshot_base64:
        return None
    s = snapshot_base64.strip()
    if s.startswith("data:"):
        # data URL — drop the "data:...;base64," prefix.
        comma = s.find(",")
        if comma != -1:
            s = s[comma + 1:]
    try:
        raw = base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError):
        logger.warning("[ingest] snapshot_base64 is not valid base64 — dropping image")
        return None
    if not raw or len(raw) > _MAX_SNAPSHOT_BYTES:
        logger.warning("[ingest] snapshot empty or over %d bytes — dropping image", _MAX_SNAPSHOT_BYTES)
        return None
    if not (raw[:3] == _JPEG_MAGIC or raw[:8] == _PNG_MAGIC):
        logger.warning("[ingest] snapshot is not a JPEG/PNG — dropping image")
        return None
    try:
        base = Path(data_path) / "snapshots"
        base.mkdir(parents=True, exist_ok=True)
        key = uuid.uuid4().hex
        (base / f"{key}.jpg").write_bytes(raw)
        return f"/snapshot?key=ingest:{key}"
    except Exception as exc:  # noqa: BLE001 — image is best-effort, never fail ingest
        logger.warning("[ingest] could not save snapshot: %s", exc)
        return None


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
    data_path=None,
) -> APIRouter:
    """Public (no-auth) dashboard + SSE. `dashboard(settings)` returns the
    aggregate stats dict. All routes 404 when the public toggle is off. When
    `data_path` is given, a /public/snapshot route serves the PERSON CROP for a
    feed event (crop only — never the full-frame context) so the live feed can
    show a thumbnail without leaking the wider scene."""
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

    @router.get("/snapshot")
    def public_snapshot(key: str = Query(...)):
        """Serve the person CROP for a feed key ("live:<id>" / "<id>"). Only the
        crop variant — the full frame is never exposed publicly. 404 when the
        public toggle is off or the crop is missing."""
        _guard()
        if data_path is None:
            raise HTTPException(404, "not found")
        frame_id = key.split(":", 1)[1] if ":" in key else key
        if "/" in frame_id or "\\" in frame_id or ".." in frame_id:
            raise HTTPException(400, "invalid key")
        path = (data_path / "snapshots" / f"{frame_id}_crop.jpg")
        if not path.exists():
            raise HTTPException(404, "snapshot not found")
        return FileResponse(str(path), media_type="image/jpeg")

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
