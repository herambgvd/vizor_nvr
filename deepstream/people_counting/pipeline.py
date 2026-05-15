"""
DeepStream People Counting pipeline — production.

Architecture:
    [Camera 1 RTSP] ─┐
    [Camera 2 RTSP] ─┼─► nvstreammux ─► nvinferserver(YOLOv12m/Triton)
    [Camera N RTSP] ─┘                  └► nvtracker(NvDCF)
                                            └► fakesink + buffer-probe
                                                   ├► extract per-track bboxes
                                                   ├► analytics.evaluate_zones
                                                   └► Redis xadd("ai:events")

Environment:
    REDIS_URL            redis://redis:6379/0
    BACKEND_URL          http://backend:8000
    BACKEND_API_KEY      vzn_*  (used for /api/ai/cameras/active)
    AI_EVENT_STREAM      ai:events  (Redis stream key)
    AI_CONTROL_CHANNEL   ai:control:reload
    PGIE_CONFIG          /app/configs/pgie_yolov12m.txt
    TRACKER_CONFIG       /app/configs/tracker_nvdcf.yml
    MUXER_WIDTH/HEIGHT   1280/720 (mux output)
    BATCH_TIMEOUT_US     40000
    SIMULATE             1 = synthetic events, 0 = real GStreamer

`SIMULATE=1` falls back to a pure-Python random-event emitter — used
during dev when the DeepStream image isn't available on the host
(non-GPU laptop). Production must set SIMULATE=0.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import signal
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
import redis.asyncio as aioredis

from analytics import CameraTrackState, evaluate_zones

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s  %(levelname)-8s  %(name)-20s  %(message)s",
)
logger = logging.getLogger("ds-people")


# ── Config ───────────────────────────────────────────────────────────────

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
AI_EVENT_STREAM = os.environ.get("AI_EVENT_STREAM", "ai:events")
CONTROL_CHANNEL = os.environ.get("AI_CONTROL_CHANNEL", "ai:control:reload")

BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000").rstrip("/")
BACKEND_API_KEY = os.environ.get("BACKEND_API_KEY", "")

PGIE_CONFIG = os.environ.get("PGIE_CONFIG", "/app/configs/pgie_yolov12m.txt")
TRACKER_CONFIG = os.environ.get("TRACKER_CONFIG", "/app/configs/tracker_nvdcf.yml")

MUXER_WIDTH = int(os.environ.get("MUXER_WIDTH", "1280"))
MUXER_HEIGHT = int(os.environ.get("MUXER_HEIGHT", "720"))
BATCH_TIMEOUT_US = int(os.environ.get("BATCH_TIMEOUT_US", "40000"))

SIMULATE = os.environ.get("SIMULATE", "0") == "1"
SIM_INTERVAL = float(os.environ.get("SIM_INTERVAL", "7"))
PERSON_CLASS_ID = int(os.environ.get("PERSON_CLASS_ID", "0"))


# ── Bootstrap state ──────────────────────────────────────────────────────


class Worker:
    """Owns Redis, http client, zones, per-camera analytics state."""

    def __init__(self) -> None:
        self.redis: Optional[aioredis.Redis] = None
        self.http: Optional[httpx.AsyncClient] = None
        self.cameras: List[Dict[str, Any]] = []
        self.zones: List[Dict[str, Any]] = []
        self.cam_state: Dict[str, CameraTrackState] = {}
        self.alert_ts: Dict[str, Dict[str, float]] = defaultdict(dict)
        self._stop = asyncio.Event()
        # source-id (mux pad index) → camera_id
        self.source_map: Dict[int, str] = {}
        # camera_id → frame size (px) for normalization
        self.frame_size: Dict[str, Tuple[int, int]] = {}
        # Event queue feeding the async publisher from the GStreamer thread
        self.event_queue: asyncio.Queue = asyncio.Queue(maxsize=10000)

    # ── Lifecycle ───────────────────────────────────────────────────────

    async def start(self) -> None:
        self.redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        headers = {}
        if BACKEND_API_KEY:
            headers["X-Vizor-API-Key"] = BACKEND_API_KEY
        self.http = httpx.AsyncClient(
            base_url=BACKEND_URL, headers=headers, timeout=10.0,
        )
        await self.reload_config()

    async def stop(self) -> None:
        self._stop.set()
        try:
            if self.http:
                await self.http.aclose()
        except Exception:
            pass
        try:
            if self.redis:
                await self.redis.aclose()
        except Exception:
            pass

    # ── Config bootstrap ────────────────────────────────────────────────

    async def reload_config(self) -> None:
        """Pull active cameras + zones from backend. Idempotent."""
        try:
            r = await self.http.get(
                "/api/ai/cameras/active",
                params={"scenario": "people_counting"},
            )
            if r.status_code == 200:
                payload = r.json()
                self.cameras = payload.get("cameras", []) or []
                self.zones = payload.get("zones", []) or []
                logger.info(
                    "reload_config: %d cameras / %d zones",
                    len(self.cameras), len(self.zones),
                )
            else:
                logger.warning("backend /active returned %d", r.status_code)
        except Exception as e:
            logger.warning("reload_config failed: %s", e)

        # Build source pad → camera map (1:1 by index of self.cameras)
        self.source_map = {i: c["id"] for i, c in enumerate(self.cameras)}
        for c in self.cameras:
            self.cam_state.setdefault(c["id"], CameraTrackState())

    # ── Event publisher ─────────────────────────────────────────────────

    async def publish_loop(self) -> None:
        """Drain event_queue → Redis xadd. Runs forever."""
        while not self._stop.is_set():
            try:
                evt = await asyncio.wait_for(self.event_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            try:
                await self.redis.xadd(  # type: ignore
                    AI_EVENT_STREAM,
                    {"payload": json.dumps(evt, default=str)},
                    maxlen=50000,
                    approximate=True,
                )
            except Exception:
                logger.exception("xadd failed")

    # ── Control channel ─────────────────────────────────────────────────

    async def control_loop(self) -> None:
        """Listen for reload signals from backend (zone edits etc.)."""
        try:
            pubsub = self.redis.pubsub()  # type: ignore
            await pubsub.subscribe(CONTROL_CHANNEL)
            async for msg in pubsub.listen():
                if msg.get("type") == "message":
                    logger.info("control reload received")
                    await self.reload_config()
                if self._stop.is_set():
                    break
        except Exception:
            logger.exception("control_loop crashed")

    # ── Frame callback ──────────────────────────────────────────────────

    def on_frame(
        self,
        source_id: int,
        tracks_px: List[Tuple[int, Tuple[float, float, float, float]]],
        frame_wh: Tuple[int, int],
    ) -> None:
        """Called from GStreamer buffer-probe thread for every frame.

        `tracks_px` is list of (track_id, (x, y, w, h)) in pixel coords.
        We normalize to 0-1 here so analytics.evaluate_zones can be
        resolution-agnostic.
        """
        camera_id = self.source_map.get(source_id)
        if not camera_id:
            return
        w, h = frame_wh
        if w <= 0 or h <= 0:
            return
        norm = [
            (tid, (x / w, y / h, bw / w, bh / h))
            for tid, (x, y, bw, bh) in tracks_px
        ]
        state = self.cam_state[camera_id]
        last_alert = self.alert_ts[camera_id]
        events = evaluate_zones(
            self.zones, camera_id, norm, state, last_alert,
        )
        for e in events:
            try:
                self.event_queue.put_nowait(e)
            except asyncio.QueueFull:
                logger.warning("event_queue full — dropping %s", e.get("type"))


# ── Simulation mode ──────────────────────────────────────────────────────


async def simulate_loop(worker: Worker) -> None:
    """Synthetic events for dev. Removed once DeepStream image runs on
    the deploy host."""
    while not worker._stop.is_set():
        for z in worker.zones:
            cid = z.get("camera_id")
            zid = z.get("id")
            if not cid or not zid:
                continue
            if z.get("scenario") == "in_out":
                direction = random.choice([
                    z.get("direction_a_label", "in"),
                    z.get("direction_b_label", "out"),
                ])
                await worker.event_queue.put({
                    "type": "line_crossing",
                    "analyticsModule": "people_counting",
                    "sensorId": cid,
                    "zoneId": zid,
                    "direction": direction,
                    "trackingId": random.randint(1, 9999),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            elif z.get("scenario") == "crowd":
                cnt = random.randint(0, max(2 * (z.get("threshold") or 5), 8))
                await worker.event_queue.put({
                    "type": "occupancy_update",
                    "analyticsModule": "people_counting",
                    "sensorId": cid,
                    "zoneId": zid,
                    "count": cnt,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                if z.get("threshold") and cnt >= z["threshold"]:
                    await worker.event_queue.put({
                        "type": "crowd_alert",
                        "analyticsModule": "people_counting",
                        "sensorId": cid,
                        "zoneId": zid,
                        "count": cnt,
                        "threshold": z["threshold"],
                        "severity": "warning",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
        await asyncio.sleep(SIM_INTERVAL)


# ── GStreamer pipeline (production path) ─────────────────────────────────


def run_gstreamer(worker: Worker, loop: asyncio.AbstractEventLoop) -> None:
    """Build + run the DeepStream pipeline. Blocks on bus loop. Runs in
    a dedicated thread because GLib MainLoop and asyncio can't share one."""

    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import GLib, Gst, GstApp  # noqa: F401

    Gst.init(None)

    n_sources = len(worker.cameras)
    if n_sources == 0:
        logger.warning("No cameras configured — GStreamer pipeline idle")
        return

    pipeline = Gst.Pipeline.new("people-pipe")

    # Mux
    streammux = Gst.ElementFactory.make("nvstreammux", "mux")
    streammux.set_property("width", MUXER_WIDTH)
    streammux.set_property("height", MUXER_HEIGHT)
    streammux.set_property("batch-size", n_sources)
    streammux.set_property("batched-push-timeout", BATCH_TIMEOUT_US)
    streammux.set_property("live-source", 1)
    pipeline.add(streammux)

    # PGIE — nvinferserver (Triton gRPC)
    pgie = Gst.ElementFactory.make("nvinferserver", "pgie")
    pgie.set_property("config-file-path", PGIE_CONFIG)
    pgie.set_property("batch-size", n_sources)

    tracker = Gst.ElementFactory.make("nvtracker", "tracker")
    tracker.set_property("tracker-width", 640)
    tracker.set_property("tracker-height", 384)
    tracker.set_property("ll-config-file", TRACKER_CONFIG)
    tracker.set_property("ll-lib-file", "/opt/nvidia/deepstream/deepstream/lib/libnvds_nvmultiobjecttracker.so")
    tracker.set_property("display-tracking-id", 0)

    sink = Gst.ElementFactory.make("fakesink", "sink")
    sink.set_property("sync", 0)

    for e in (pgie, tracker, sink):
        pipeline.add(e)

    streammux.link(pgie)
    pgie.link(tracker)
    tracker.link(sink)

    # Sources
    for idx, cam in enumerate(worker.cameras):
        url = cam.get("main_stream_url")
        if not url:
            continue
        src = Gst.ElementFactory.make("uridecodebin", f"src-{idx}")
        src.set_property("uri", url)
        pipeline.add(src)

        # Connect pad-added to plug into mux sink_<idx>
        def _pad_added(_src, pad, sink_pad):
            caps = pad.get_current_caps()
            if not caps:
                return
            struct = caps.get_structure(0)
            name = struct.get_name()
            if not name.startswith("video"):
                return
            pad.link(sink_pad)

        sinkpad = streammux.get_request_pad(f"sink_{idx}")
        src.connect("pad-added", _pad_added, sinkpad)
        logger.info("Bound source[%d] = %s", idx, cam.get("name") or cam.get("id"))

    # Probe — extracts tracker bboxes
    src_pad = tracker.get_static_pad("src")

    def _probe(_pad, info):
        from pyds import gst_buffer_get_nvds_batch_meta, NvDsFrameMeta, NvDsObjectMeta  # type: ignore

        buf = info.get_buffer()
        if not buf:
            return Gst.PadProbeReturn.OK
        batch_meta = gst_buffer_get_nvds_batch_meta(hash(buf))
        if not batch_meta:
            return Gst.PadProbeReturn.OK

        l_frame = batch_meta.frame_meta_list
        while l_frame is not None:
            try:
                frame_meta = NvDsFrameMeta.cast(l_frame.data)
            except StopIteration:
                break
            source_id = frame_meta.pad_index
            frame_w, frame_h = frame_meta.source_frame_width, frame_meta.source_frame_height
            tracks: List[Tuple[int, Tuple[float, float, float, float]]] = []

            l_obj = frame_meta.obj_meta_list
            while l_obj is not None:
                try:
                    obj = NvDsObjectMeta.cast(l_obj.data)
                except StopIteration:
                    break
                if obj.class_id == PERSON_CLASS_ID and obj.object_id != 0xFFFFFFFFFFFFFFFF:
                    r = obj.rect_params
                    tracks.append((int(obj.object_id), (float(r.left), float(r.top), float(r.width), float(r.height))))
                try:
                    l_obj = l_obj.next
                except StopIteration:
                    break

            asyncio.run_coroutine_threadsafe(
                _bounce_to_worker(worker, source_id, tracks, (frame_w, frame_h)),
                loop,
            )

            try:
                l_frame = l_frame.next
            except StopIteration:
                break

        return Gst.PadProbeReturn.OK

    src_pad.add_probe(Gst.PadProbeType.BUFFER, _probe)

    # Run
    glib_loop = GLib.MainLoop()

    def _bus_call(_bus, msg):
        t = msg.type
        if t == Gst.MessageType.EOS:
            logger.info("EOS")
            glib_loop.quit()
        elif t == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            logger.error("GStreamer error: %s | %s", err, dbg)
            glib_loop.quit()
        return True

    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", _bus_call)

    pipeline.set_state(Gst.State.PLAYING)
    logger.info("DeepStream pipeline running")
    try:
        glib_loop.run()
    finally:
        pipeline.set_state(Gst.State.NULL)


async def _bounce_to_worker(worker: Worker, source_id, tracks, frame_wh):
    """Lightweight async wrapper called from the probe thread via
    run_coroutine_threadsafe."""
    worker.on_frame(source_id, tracks, frame_wh)


# ── Main ─────────────────────────────────────────────────────────────────


async def main() -> None:
    worker = Worker()
    await worker.start()
    tasks = [
        asyncio.create_task(worker.publish_loop()),
        asyncio.create_task(worker.control_loop()),
    ]
    if SIMULATE:
        logger.warning("SIMULATE=1 — emitting synthetic events every %ss", SIM_INTERVAL)
        tasks.append(asyncio.create_task(simulate_loop(worker)))
    else:
        loop = asyncio.get_running_loop()
        threading.Thread(
            target=run_gstreamer, args=(worker, loop), daemon=True, name="gst-thread",
        ).start()

    def _shutdown(*_):
        for t in tasks:
            t.cancel()
        worker._stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            pass

    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await worker.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
