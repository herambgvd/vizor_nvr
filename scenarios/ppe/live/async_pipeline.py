"""PPE async adapter — bridges the proven CameraWorker pipeline to the shared SDK
async supervisor (vizor_sdk.aio).

`PpePipeline` REUSES the entire CameraWorker pipeline (detector, tracker, stable-id
mapper, smoother, ComplianceEngine, SigLIP verifier, ROI, snapshots, all thresholds
and the exact `_process` logic) by subclassing it — but it does NOT run as a thread
and it does NOT write events to the DB inline. Instead `_emit`/`_maybe_emit_compliant`
collect event payloads into a list, and the supervisor's AsyncEventWriter delivers
them off-thread (Postgres + spool). This keeps the byte-for-byte detection behaviour
while removing the synchronous-DB-on-frame-thread chokepoint.

`build_async_manager()` wires a CameraSupervisor + the HTTP camera reconcile, behind
the PPE_LIVE_ASYNC flag, so it can run side-by-side with the legacy thread manager.
"""
from __future__ import annotations

import logging

import config
from db.events import record_event
from vizor_sdk.aio.supervisor import CameraSupervisor, Pipeline, run_supervisor_thread

from .worker import CameraWorker, _bbox_obj  # reuse the proven pipeline

logger = logging.getLogger(__name__)


class PpePipeline(CameraWorker, Pipeline):
    """A CameraWorker used as a per-frame pipeline (not a thread). Construct one per
    camera; call process(frame) per frame; it returns a list of event dicts."""

    def __init__(self, cam: dict) -> None:
        # Initialise the full CameraWorker state (detector/tracker/engine/vit/roi/
        # config props) WITHOUT starting the thread — pass a no-op report_state.
        CameraWorker.__init__(self, cam, report_state=lambda *a, **k: None)
        self._pending: list[dict] = []

    # ── Pipeline contract ────────────────────────────────────────────────────
    def process(self, frame) -> list[dict]:
        """Run the proven per-frame pipeline; return collected events (may be empty)."""
        self._pending = []
        self._frame_no += 1
        try:
            self._process(frame, _now())
        except Exception as e:  # noqa: BLE001 — one bad frame must not kill the camera
            logger.debug("[ppe-pipeline] frame error: %s", e)
            return []
        out, self._pending = self._pending, []
        return out

    def close(self) -> None:
        return None

    # ── redirect the two emit paths to the pending list (no inline DB write) ──
    def _emit(self, person, event, ppes, evidence, present_items, frame_bgr, h, w) -> None:
        from .worker import _EVENT_TYPE, CANONICAL_TO_ITEM, _BOX_RED
        event_type = _EVENT_TYPE.get(event, "ppe_missing")
        items = [CANONICAL_TO_ITEM.get(p, p) for p in ppes]
        primary = items[0] if items else None
        missing = [CANONICAL_TO_ITEM.get(r, r) for r in self.required_canonical
                   if r not in evidence] or items
        confs = [evidence[p].confidence for p in ppes if evidence.get(p)]
        conf = max(confs) if confs else None
        item_colors = self._status_colors(evidence)
        snap = self._snapshot(frame_bgr, person.box, _BOX_RED, person.track_id, item_colors)
        self._dbg_violations += 1
        self._pending.append({
            "camera_id": self.camera_id, "event_type": event_type,
            "worker_track_id": person.track_id, "ppe_item": primary,
            "missing_items": missing, "present_items": present_items,
            "confidence": conf, "snapshot_path": snap,
            "bbox": _bbox_obj(person.box, w, h),
            "_log": f"Violation: worker #{person.track_id} missing "
                    f"{', '.join(missing) if missing else 'PPE'}",
        })

    def _maybe_emit_compliant(self, person, evidence, present_items, frame_bgr, h, w, now) -> None:
        from .worker import _BOX_GREEN
        key = f"compliant:{person.track_id}"
        last = getattr(self, "_compliant_last", {})
        if now - last.get(key, -1e12) < self.cooldown:
            return
        last[key] = now
        self._compliant_last = last
        confs = [evidence[r].confidence for r in self.required_canonical if evidence.get(r)]
        conf = min(confs) if confs else None
        item_colors = self._status_colors(evidence)
        snap = self._snapshot(frame_bgr, person.box, _BOX_GREEN, person.track_id, item_colors)
        self._pending.append({
            "camera_id": self.camera_id, "event_type": "ppe_compliant",
            "worker_track_id": person.track_id, "ppe_item": None,
            "missing_items": [], "present_items": present_items,
            "confidence": conf, "snapshot_path": snap,
            "bbox": _bbox_obj(person.box, w, h),
            "_log": f"Compliant: worker #{person.track_id}",
        })


def _now() -> float:
    import time
    return time.monotonic()


def _ppe_event_sink(event: dict) -> None:
    """EventSink: persist one PPE event to Postgres via the existing recorder.
    Runs on the AsyncEventWriter thread (off the camera task). Strips the private
    _log key the supervisor already consumed."""
    from schemas import utcnow
    payload = {k: v for k, v in event.items() if not k.startswith("_")}
    record_event(
        camera_id=payload.get("camera_id"),
        event_type=payload.get("event_type", "ppe_missing"),
        worker_track_id=payload.get("worker_track_id"),
        ppe_item=payload.get("ppe_item"),
        missing_items=payload.get("missing_items"),
        present_items=payload.get("present_items"),
        confidence=payload.get("confidence"),
        snapshot_path=payload.get("snapshot_path"),
        ts=utcnow(),
        bbox=payload.get("bbox"),
    )


def build_async_manager():
    """Start the async supervisor on its own loop thread, driven by the HTTP camera
    reconcile. Returns the thread. Mirrors the legacy manager's camera source +
    rtsp url. No-op unless PPE_LIVE_ASYNC is set."""
    from .manager import _fetch_cameras, _report_state  # reuse existing HTTP helpers

    def _rtsp_url(camera_id: str) -> str:
        host = getattr(config, "GO2RTC_RTSP_HOST", "go2rtc")
        port = getattr(config, "GO2RTC_RTSP_PORT", 8554)
        return f"rtsp://{host}:{port}/{camera_id}"

    def _on_state(cam: dict, state: str, error) -> None:
        _report_state(cam.get("config_id"), state, error)

    sup = CameraSupervisor(
        name="ppe",
        make_pipeline=lambda cam: PpePipeline(cam),
        sink=_ppe_event_sink,
        rtsp_url_for=_rtsp_url,
        spool_dir=str(config.DATA_PATH / "spool"),
        on_state=_on_state,
    )
    th = run_supervisor_thread(sup, fetch_cameras=_fetch_cameras,
                               poll_secs=getattr(config, "LIVE_POLL_SECONDS", 5.0))
    logger.info("[ppe-live] async supervisor started (PPE_LIVE_ASYNC)")
    return sup, th
