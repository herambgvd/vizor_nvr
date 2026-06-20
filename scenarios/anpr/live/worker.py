"""Per-camera live ANPR worker.

One worker per enabled camera. Pulls frames from go2rtc over RTSP (SDK FramePuller
— NVDEC + backpressure + stall watchdog), then per frame runs the ported POC
pipeline with the single-lane bug fixed:

  frame -> (optional) CLAHE low-light enhance
        -> anpr_plate detect (Triton)            [det conf gate]
        -> ByteTracker assigns a track id per plate box
        -> per plate: width gate + ROI gate -> OCR (Triton ppocr_v6)
        -> normalize + PLATE_REGEX gate -> per-TRACK vote accumulation
        -> MotionEstimator.update (direction + speed if calibrated)
   on track exit (plate gone EXIT_FRAMES frames):
        -> vote the plate (most-common-length + per-position majority, >= MIN_READS)
        -> vehicle-type (yolo26 enclosing box) + direction + speed
        -> user-list match -> record_event (action=alert => high severity)

The proven thresholds (det 0.6, OCR conf gate, min reads 3, exit frames 15) are
preserved. Fail-soft throughout — one bad frame never kills the worker.
"""
from __future__ import annotations

import os
import threading
import time
import uuid

import config
from db.events import record_event as _record_event
from db.list_store import match_plate, normalize_plate
from pipeline import (
    MotionEstimator,
    TrackVoteManager,
    build_roi,
    compile_regex,
    enhance_lowlight,
    gate_read,
    is_low_light,
    plate_in_roi,
)
from schemas import utcnow

try:
    import cv2
    import numpy as np
except Exception:  # noqa: BLE001
    cv2 = None
    np = None


# Backpressure: cap concurrent Triton inferences across ALL camera workers so a
# many-camera node doesn't thundering-herd the GPU. A worker that can't get the
# slot quickly DROPS the frame (skip, don't queue).
_INFLIGHT = threading.Semaphore(int(os.getenv("ANPR_MAX_INFLIGHT", "12")))


def _bbox_obj(box, frame_w: int, frame_h: int):
    """Pixel [x1,y1,x2,y2] → normalised {x,y,w,h} the UI renders."""
    if not box or len(box) != 4 or not frame_w or not frame_h:
        return None
    x1, y1, x2, y2 = box
    return {
        "x": round(x1 / frame_w, 4),
        "y": round(y1 / frame_h, 4),
        "w": round((x2 - x1) / frame_w, 4),
        "h": round((y2 - y1) / frame_h, 4),
    }


class CameraWorker(threading.Thread):
    def __init__(self, cam: dict, report_state):
        super().__init__(daemon=True)
        self.cam = cam
        self.camera_id = cam["camera_id"]
        self.config_id = cam.get("config_id")
        self.config = cam.get("config") or {}
        self.report_state = report_state          # callback(config_id, state, error)
        self._stop = threading.Event()
        self.last_frame_ts = 0.0                   # liveness: last decoded frame (epoch)
        self._roi = None
        self._roi_built = False
        self._motion = None                        # built lazily once frame size known
        self._motion_built = False

        # Shared Triton clients (module singletons).
        from inference import detector as _det, ocr as _ocr, vehicle as _veh
        self._detector = _det
        self._ocr = _ocr
        self._vehicle = _veh

        # Plate tracking: SDK ByteTracker assigns a stable id per plate box so each
        # vehicle's reads vote independently (fixes the POC single-lane bug).
        from vizor_sdk import ByteTracker
        self._tracker = ByteTracker(
            iou_threshold=0.08, max_age=config.TRACK_MAX_AGE,
            high_thresh=self.det_conf, low_thresh=max(0.1, self.det_conf - 0.2),
        )
        self._votes = TrackVoteManager(self.exit_frames, self.min_reads)
        self._regex = compile_regex(self.plate_regex)
        self._puller = None

    def stop(self):
        self._stop.set()
        if self._puller is not None:
            try:
                self._puller.stop()
            except Exception:  # noqa: BLE001
                pass

    # ── config helpers ────────────────────────────────────────────────────
    def _cfg_num(self, key, default, cast):
        try:
            v = self.config.get(key)
            return cast(v) if v not in (None, "") else default
        except (TypeError, ValueError):
            return default

    def _cfg_bool(self, key, default):
        v = self.config.get(key)
        if v is None:
            return default
        return bool(v)

    @property
    def fps(self) -> float:
        return self._cfg_num("fps", config.LIVE_DEFAULT_FPS, float)

    @property
    def det_conf(self) -> float:
        return self._cfg_num("det_conf", config.DET_CONF, float)

    @property
    def ocr_conf(self) -> float:
        # OCR conf is on a 0..1 scale in config; the OCR returns 0..100, so the
        # gate compares against ocr_conf*100 below.
        return self._cfg_num("ocr_conf", config.OCR_CONF, float)

    @property
    def min_plate_w(self) -> int:
        return self._cfg_num("min_plate_w", config.MIN_PLATE_W, int)

    @property
    def min_reads(self) -> int:
        return self._cfg_num("min_reads", config.MIN_READS, int)

    @property
    def exit_frames(self) -> int:
        return self._cfg_num("exit_frames", config.EXIT_FRAMES, int)

    @property
    def plate_regex(self) -> str:
        return self.config.get("plate_regex") or config.PLATE_REGEX

    @property
    def allow_raw(self) -> bool:
        return self._cfg_bool("allow_raw_reads", config.ALLOW_RAW_READS)

    @property
    def lowlight(self) -> bool:
        return self._cfg_bool("lowlight_enhance", config.LOWLIGHT_ENHANCE)

    @property
    def roi_config(self):
        return self.config.get("roi")

    def _rtsp_url(self) -> str:
        sid = self.cam.get("sub_stream_id") if config.LIVE_USE_SUBSTREAM else self.cam.get("stream_id")
        sid = sid or self.camera_id
        return f"rtsp://{config.GO2RTC_RTSP_HOST}:{config.GO2RTC_RTSP_PORT}/{sid}"

    # ── main loop ─────────────────────────────────────────────────────────
    def run(self):
        from vizor_sdk.frames import FramePuller

        self._puller = FramePuller(
            self._rtsp_url(), fps=self.fps, hwaccel=config.LIVE_HWACCEL,
            max_width=config.LIVE_MAX_WIDTH, stall_timeout=config.LIVE_STALL_TIMEOUT,
            label=self.camera_id,
        )

        def _on_state(state, detail):
            self.report_state(self.config_id, state, detail)

        try:
            self._puller.run(on_frame=self._on_frame, on_state=_on_state)
        except Exception as exc:  # noqa: BLE001
            self.report_state(self.config_id, "error", str(exc)[:200])
        finally:
            # Flush any open vehicle sessions so a vehicle mid-pass at shutdown is
            # still emitted (best-effort).
            try:
                for res in self._votes.flush():
                    self._emit(res, None)
            except Exception:  # noqa: BLE001
                pass
            self.report_state(self.config_id, "stopped", None)

    # ── per-frame pipeline ─────────────────────────────────────────────────
    def _on_frame(self, frame_bgr) -> None:
        if self._stop.is_set() or frame_bgr is None or np is None:
            return
        self.last_frame_ts = time.time()
        if not _INFLIGHT.acquire(timeout=0.5):
            return  # GPU saturated — drop this frame rather than queue
        try:
            self._process(frame_bgr)
        except Exception:  # noqa: BLE001 — one bad frame must not kill the worker
            return
        finally:
            _INFLIGHT.release()

    def _process(self, frame_bgr) -> None:
        h, w = frame_bgr.shape[:2]
        if not self._roi_built:
            self._roi = build_roi(self.roi_config, h, w)
            self._roi_built = True
        if not self._motion_built:
            self._motion = MotionEstimator(self.config, w, h)
            self._motion_built = True

        # Optional CLAHE low-light enhancement (POC parity) before detect/OCR.
        proc = frame_bgr
        if self.lowlight and is_low_light(frame_bgr, config.LOWLIGHT_THRESH):
            proc = enhance_lowlight(frame_bgr)

        plates = self._detector.detect(proc, conf_thresh=self.det_conf)
        from vizor_sdk import assign_track_ids
        if not plates:
            # No plate this frame: advance tracker + close any departed sessions.
            assign_track_ids(self._tracker, [])
            self._close(self._votes.tick(set()))
            return

        dets_for_track = [(list(p.box), float(p.confidence)) for p in plates]
        track_ids = assign_track_ids(self._tracker, dets_for_track)

        active: set[int] = set()
        gate_scale = self.ocr_conf * 100.0  # OCR returns 0..100; gate is configured 0..1
        for plate, tid in zip(plates, track_ids):
            if tid:
                active.add(tid)
                # Direction / speed: feed the plate-box center every frame it's tracked.
                if self._motion is not None:
                    x1, y1, x2, y2 = plate.box
                    self._motion.update(tid, ((x1 + x2) / 2.0, (y1 + y2) / 2.0))

            # ROI + width gating (POC: skip far/tiny plates + plates outside zone).
            x1, y1, x2, y2 = plate.box
            if (x2 - x1) < self.min_plate_w:
                continue
            if self._roi is not None and not plate_in_roi(plate.box, self._roi):
                continue
            if not tid:
                continue  # unestablished track — wait until ByteTracker confirms it

            crop = proc[y1:y2, x1:x2]
            if crop is None or crop.size == 0:
                continue
            text, conf = self._ocr.read(crop)         # conf 0..100
            accepted = gate_read(text, conf, gate_scale, self._regex, self.allow_raw)
            if accepted is None:
                continue
            # Accumulate this read on the vehicle's own session (per-track vote).
            self._votes.add(tid, accepted, conf, crop=crop.copy(),
                            box=plate.box, frame=frame_bgr)

        # Advance gaps + close sessions whose vehicle has left the scene.
        self._close(self._votes.tick(active))

    # ── session close → event ────────────────────────────────────────────────
    def _close(self, finished) -> None:
        for res in finished:
            self._emit(res, res.get("frame"))
            if self._motion is not None:
                self._motion.forget(res["track_id"])

    def _emit(self, res: dict, frame_bgr) -> None:
        plate = res["plate"]
        norm = normalize_plate(plate)
        conf = res.get("conf")
        track_id = res.get("track_id")
        box = res.get("box")
        snap_frame = frame_bgr if frame_bgr is not None else res.get("frame")
        crop = res.get("crop")
        fh = snap_frame.shape[0] if snap_frame is not None else 0
        fw = snap_frame.shape[1] if snap_frame is not None else 0

        # Vehicle type — enclosing yolo26 box on the best read's frame (fail-soft).
        vehicle_type = None
        try:
            if snap_frame is not None and box is not None:
                vehicle_type = self._vehicle.vehicle_type_for_plate(snap_frame, box)
        except Exception:  # noqa: BLE001
            vehicle_type = None

        direction = self._motion.direction_for(track_id) if self._motion else None
        speed = self._motion.speed_for(track_id) if self._motion else None

        # Match the plate against the user-defined lists. The matched list's
        # ACTION drives the event: alert -> high-severity blacklist_hit,
        # allow -> whitelist_hit (info), log -> just tagged as a plate_read.
        list_hit = None
        list_label = None
        event_type = "plate_read"
        hit = match_plate(norm)
        if hit:
            list_hit = hit.get("list_name")      # store the matched LIST NAME
            list_label = hit.get("label")
            action = hit.get("action")
            if action == "alert":
                event_type = "blacklist_hit"
            elif action == "allow":
                event_type = "whitelist_hit"
            else:
                event_type = "plate_read"

        snap = self._snapshot(snap_frame, crop)
        _record_event(
            self.camera_id, plate, conf,
            event_type=event_type,
            vehicle_type=vehicle_type,
            direction=direction,
            speed_kmh=speed,
            list_hit=list_hit,
            list_label=list_label,
            track_id=track_id,
            n_frames=res.get("frames"),
            bbox=_bbox_obj(box, fw, fh),
            snapshot_path=snap,
            ts=utcnow(),
        )

    def _snapshot(self, frame_bgr, crop) -> str | None:
        """Persist the full frame + the plate crop. Returns the snapshot key the
        /snapshot route serves, or None on failure."""
        if cv2 is None:
            return None
        frame_id = str(uuid.uuid4())
        try:
            base = config.DATA_PATH / "snapshots"
            base.mkdir(parents=True, exist_ok=True)
            wrote = False
            if frame_bgr is not None:
                ok, buf = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                if ok:
                    (base / f"{frame_id}.jpg").write_bytes(buf.tobytes())
                    wrote = True
            if crop is not None and getattr(crop, "size", 0):
                cok, cbuf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
                if cok:
                    (base / f"{frame_id}_crop.jpg").write_bytes(cbuf.tobytes())
                    wrote = True
            return f"/snapshot?key=live:{frame_id}" if wrote else None
        except Exception:  # noqa: BLE001
            return None
