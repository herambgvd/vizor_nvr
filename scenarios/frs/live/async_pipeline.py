"""FRS async adapter — bridges the proven CameraWorker pipeline to the shared SDK
async supervisor (vizor_sdk.aio) with a GStreamer frame source.

`FrsPipeline` REUSES the entire CameraWorker recognition pipeline (SCRFD detect →
ByteTrack → vote consensus → ArcFace match → liveness/quality gates → events +
attendance) by subclassing it — but it does NOT run its own ffmpeg thread. The
supervisor owns one asyncio task per camera, decodes RTSP via GStreamer (NVDEC-capable,
H.264/H.265) into BGR frames, and calls `process(frame)` off the event loop. The frame
is JPEG-encoded once and fed to the existing `_process_frame`, so detection behaviour
is byte-for-byte identical to the legacy worker. Events are still written inline by
record_event (FRS owns its own Postgres) — that runs on the supervisor's worker thread,
off the event loop, so it never blocks decode.

`build_async_manager()` wires a CameraSupervisor + the HTTP camera reconcile behind the
FRS_LIVE_ASYNC flag, so it runs side-by-side with the legacy thread manager.
"""
from __future__ import annotations

import logging

import cv2

import config
from vizor_sdk.aio.supervisor import CameraSupervisor, Pipeline, run_supervisor_thread

from .worker import CameraWorker  # reuse the proven recognition pipeline

logger = logging.getLogger(__name__)


class FrsPipeline(CameraWorker, Pipeline):
    """A CameraWorker used as a per-frame pipeline (not a thread). Construct one per
    camera; call process(bgr_frame) per frame. Events are recorded inline by the
    existing pipeline; process() returns an empty list (nothing for the sink)."""

    def __init__(self, cam: dict) -> None:
        # Initialise the full CameraWorker state (detector/tracker/votes/roi/config)
        # WITHOUT starting the thread — pass a no-op report_state.
        CameraWorker.__init__(self, cam, report_state=lambda *a, **k: None)

    # ── Pipeline contract ────────────────────────────────────────────────────
    def process(self, frame) -> list[dict]:
        """Run the proven recognition pipeline on a BGR frame. Encodes it to JPEG (the
        recognition path expects JPEG bytes) and drives _process_frame, which writes
        any FRS events + attendance inline. Returns [] (events already persisted)."""
        try:
            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            if not ok:
                return []
            self._process_frame(buf.tobytes())
        except Exception as e:  # noqa: BLE001 — one bad frame must not kill the camera
            logger.debug("[frs-pipeline] frame error: %s", e)
        return []

    def stats(self) -> dict:
        """FRS counters for the worker-logs panel."""
        return {
            "faces_last": getattr(self, "_dbg_faces", 0),
            "recognized_total": getattr(self, "_dbg_recognized", 0),
        }

    def close(self) -> None:
        return None


def _frs_event_sink(event: dict) -> None:
    # Events are written inline by record_event inside the pipeline (FRS owns its DB),
    # so there is nothing to deliver here. Present only to satisfy the supervisor API.
    return None


def build_async_manager():
    """Start the async supervisor on its own loop thread, driven by the HTTP camera
    reconcile, decoding via GStreamer. No-op unless FRS_LIVE_ASYNC is set."""
    from .manager import _fetch_cameras, _report_state  # reuse existing HTTP helpers

    def _rtsp_url(camera_id: str) -> str:
        host = getattr(config, "GO2RTC_RTSP_HOST", "go2rtc")
        port = getattr(config, "GO2RTC_RTSP_PORT", 8554)
        return f"rtsp://{host}:{port}/{camera_id}"

    def _on_state(cam: dict, state: str, error) -> None:
        # Push the worker's stream_state back to the NVR so the Cameras tab shows
        # running / starting / stopped / error instead of a stale value.
        _report_state(cam.get("config_id"), state, error)

    sup = CameraSupervisor(
        name="frs",
        make_pipeline=lambda cam: FrsPipeline(cam),
        sink=_frs_event_sink,
        rtsp_url_for=_rtsp_url,
        spool_dir=str(config.DATA_PATH / "spool"),
        on_state=_on_state,
    )
    th = run_supervisor_thread(sup, fetch_cameras=_fetch_cameras,
                               poll_secs=getattr(config, "LIVE_POLL_SECONDS", 5.0))
    logger.info("[frs-live] async supervisor started (FRS_LIVE_ASYNC)")
    return sup, th
