"""Per-camera live PPE compliance worker.

One worker per enabled camera. Pulls frames from go2rtc over RTSP (SDK FramePuller
— NVDEC + backpressure + stall watchdog), runs the Triton PPE detector, tracks
persons (SDK ByteTracker for raw ids → StableIdMapper relink across occlusions),
associates PPE to workers by body zone, smooths evidence across frames, drives the
ported ComplianceEngine, and writes PPE events (ppe_missing / ppe_removed, plus
optional ppe_compliant) with a snapshot. The proven thresholds / grace / cooldown
are preserved.

Pipeline per frame (ported from run_video.run, minus drawing / video writing):
  detect → split persons/items → eligible_people → deduplicate → ROI gate →
  ByteTracker raw ids → StableIdMapper → associate_ppe(full-frame) → smooth →
  positive_evidence → ComplianceEngine.update → record_event on violation.
"""
from __future__ import annotations

import os
import threading
import time
import uuid

import config
from db.events import record_event as _record_event
from pipeline import (
    CANONICAL_TO_ITEM,
    DEFAULT_RULES,
    ITEM_TO_CANONICAL,
    ComplianceEngine,
    Detection,
    EvidenceSmoother,
    StableIdMapper,
    associate_ppe,
    build_roi,
    deduplicate_persons,
    eligible_people,
    in_roi,
    positive_evidence,
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
_INFLIGHT = threading.Semaphore(int(os.getenv("PPE_MAX_INFLIGHT", "12")))

# Map our internal event verbs to the stored event_type.
_EVENT_TYPE = {"PPE_MISSING": "ppe_missing", "PPE_REMOVED": "ppe_removed"}


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
        self._frame_no = 0
        self._dbg_persons = 0      # persons seen in the last processed frame
        self._dbg_violations = 0   # total violations emitted by this worker
        self._roi = None
        self._roi_built = False

        # Detector (shared Triton client).
        from inference import detector as _detector
        self._detector = _detector

        # Person tracking: SDK ByteTracker gives raw ids; StableIdMapper relinks
        # them to physical workers across short occlusions (proven POC relinker).
        from vizor_sdk import ByteTracker
        self._tracker = ByteTracker(
            iou_threshold=0.10, max_age=90, high_thresh=0.30, low_thresh=0.10,
        )
        self._stable = StableIdMapper(self.stable_id_max_age)
        self._smoother = EvidenceSmoother(config.SMOOTH_WINDOW, config.SMOOTH_MIN_HITS)
        # Optional DINOv2 second-stage verifier (Triton). No-op when not configured.
        from inference.vit_verifier import VitVerifier
        self._vit = VitVerifier(self._detector)
        self._engine = ComplianceEngine(
            self.required_canonical, self.missing_grace, self.min_present,
            self.cooldown, config.ALERT_INITIAL_MISSING,
        )
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

    @property
    def fps(self) -> float:
        return self._cfg_num("fps", config.LIVE_DEFAULT_FPS, float)

    @property
    def required_canonical(self) -> list[str]:
        """Required PPE as canonical detector labels (Hardhat / Safety_Vest)."""
        items = self.config.get("required_items") or self.config.get("required_ppe") \
            or config.REQUIRED_PPE_DEFAULT
        out: list[str] = []
        for it in items:
            canon = ITEM_TO_CANONICAL.get(str(it).lower().replace("-", "_").replace(" ", "_"))
            if canon and canon not in out:
                out.append(canon)
        return out or ["Hardhat", "Safety_Vest"]

    @property
    def missing_grace(self) -> float:
        return self._cfg_num("missing_grace", config.MISSING_GRACE, float)

    @property
    def min_present(self) -> float:
        return self._cfg_num("min_present", config.MIN_PRESENT, float)

    @property
    def cooldown(self) -> float:
        return self._cfg_num("cooldown", config.COOLDOWN, float)

    @property
    def stable_id_max_age(self) -> float:
        return self._cfg_num("stable_id_max_age", config.STABLE_ID_MAX_AGE, float)

    @property
    def person_conf(self) -> float:
        return self._cfg_num("person_conf", config.PERSON_CONF, float)

    @property
    def emit_compliant(self) -> bool:
        return bool(self.config.get("emit_compliant"))

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

        rtsp = self._rtsp_url()
        print(f"[ppe-live] {self.camera_id[:8]} pulling {rtsp} fps={self.fps} hwaccel={config.LIVE_HWACCEL}", flush=True)
        self._puller = FramePuller(
            rtsp, fps=self.fps, hwaccel=config.LIVE_HWACCEL,
            max_width=config.LIVE_MAX_WIDTH, stall_timeout=config.LIVE_STALL_TIMEOUT,
            label=self.camera_id,
        )

        def _on_state(state, detail):
            print(f"[ppe-live] {self.camera_id[:8]} stream {state}" + (f": {detail}" if detail else ""), flush=True)
            self.report_state(self.config_id, state, detail)

        try:
            self._puller.run(on_frame=self._on_frame, on_state=_on_state)
        except Exception as exc:  # noqa: BLE001
            self.report_state(self.config_id, "error", str(exc)[:200])
        finally:
            self.report_state(self.config_id, "stopped", None)

    # ── per-frame pipeline ─────────────────────────────────────────────────
    def _on_frame(self, frame_bgr) -> None:
        if self._stop.is_set() or frame_bgr is None or np is None:
            return
        now = time.monotonic()
        wall = time.time()
        self.last_frame_ts = wall
        self._frame_no += 1
        # Backpressure: drop the frame if the GPU is saturated rather than queue it.
        if not _INFLIGHT.acquire(timeout=0.5):
            return
        try:
            self._process(frame_bgr, now)
        except Exception as exc:  # noqa: BLE001 — one bad frame must not kill the worker
            # Log (rate-limited) instead of swallowing silently — needed to debug
            # why a stream produces no events.
            if self._frame_no % 50 == 0:
                print(f"[ppe-live] {self.camera_id[:8]} frame error: {exc}", flush=True)
            return
        finally:
            _INFLIGHT.release()
        # Heartbeat: every ~100 analysed frames, report what the pipeline saw so
        # operators/testers can tell detection is alive even with zero events.
        if self._frame_no % 100 == 0:
            print(f"[ppe-live] {self.camera_id[:8]} frames={self._frame_no} "
                  f"persons_last={self._dbg_persons} violations_total={self._dbg_violations}",
                  flush=True)

    def _process(self, frame_bgr, now: float) -> None:
        h, w = frame_bgr.shape[:2]
        if not self._roi_built:
            self._roi = build_roi(self.roi_config, h, w)
            self._roi_built = True

        detections = self._detector.detect(frame_bgr)
        if not detections:
            # Still age the tracker / engine so stale state clears.
            self._tracker.update([])
            self._engine.purge(now)
            return

        # Split persons vs PPE items at their respective confidence floors.
        all_persons: list[Detection] = []
        items: list[Detection] = []
        for d in detections:
            if d.label == "Person":
                if d.confidence >= self.person_conf:
                    all_persons.append(d)
            else:
                items.append(d)

        # Eligibility + dedup + ROI gate (ported order from run_video.run).
        persons = deduplicate_persons(
            eligible_people(all_persons, h, w, config.MIN_PERSON_HEIGHT,
                            config.MIN_FOOT_Y, config.BORDER_MARGIN)
        )
        if self._roi is not None:
            persons = [p for p in persons if in_roi(p, self._roi)]
        self._dbg_persons = len(persons)
        if not persons:
            self._tracker.update([])
            self._engine.purge(now)
            return

        # Raw track ids (ByteTracker) → relink to stable worker ids.
        from vizor_sdk import assign_track_ids
        dets_for_track = [(list(p.box), float(p.confidence)) for p in persons]
        raw_ids = assign_track_ids(self._tracker, dets_for_track)
        raw_tracked: list[Detection] = []
        for p, rid in zip(persons, raw_ids):
            if rid:  # 0 = unmatched; skip until the track is established
                raw_tracked.append(Detection(p.label, p.confidence, p.box, rid))
        if not raw_tracked:
            self._engine.purge(now)
            return
        persons = self._stable.update(raw_tracked, now)

        # Full-frame PPE → worker association by body zone, then per-item filter at
        # the proven confidence floors (helmet 0.10 / vest 0.50 / no_helmet 0.15).
        items = [it for it in items if it.confidence >= self._item_floor(it.label)]
        linked = associate_ppe(persons, items, DEFAULT_RULES)

        # DINOv2 second-stage verifier (when enabled): confirm weak helmet positives
        # / rescue confident missed helmet+vest, fused into `linked` before
        # smoothing. No-op + fail-soft when the model/artifact isn't configured.
        if self._vit.enabled:
            scores = self._vit.classify(frame_bgr, persons, self._frame_no)
            if scores:
                self._vit.fuse(linked, scores)

        active_ids = {p.track_id for p in persons if p.track_id is not None}
        for person in persons:
            tid = person.track_id
            if tid is None:
                continue
            raw = linked.get(tid, {})
            stable = self._smoother.update(tid, raw, self._frame_no)
            evidence = positive_evidence(stable, config.NO_HARDHAT_CONF, config.NEGATIVE_MARGIN)
            fired = self._engine.update(tid, evidence, now)
            present_items = [CANONICAL_TO_ITEM.get(k, k) for k in evidence]
            for event, ppe in fired:
                self._dbg_violations += 1
                self._emit(person, event, ppe, evidence, present_items, frame_bgr, h, w)
            # Optional positive compliant event: all required present + none firing.
            if self.emit_compliant and not fired \
                    and all(req in evidence for req in self.required_canonical):
                self._maybe_emit_compliant(person, present_items, frame_bgr, h, w, now)

        self._smoother.purge(active_ids)
        self._engine.purge(now)

    def _item_floor(self, label: str) -> float:
        if label == "NO_Hardhat":
            return config.NO_HARDHAT_CONF
        if label == "Hardhat":
            return config.HARDHAT_CONF
        if label == "Safety_Vest":
            return config.VEST_CONF
        return config.HARDHAT_CONF

    # ── emission ────────────────────────────────────────────────────────────
    def _emit(self, person, event, ppe, evidence, present_items, frame_bgr, h, w) -> None:
        event_type = _EVENT_TYPE.get(event, "ppe_missing")
        item = CANONICAL_TO_ITEM.get(ppe, ppe)
        missing = [CANONICAL_TO_ITEM.get(r, r) for r in self.required_canonical
                   if r not in evidence]
        det = evidence.get(ppe)
        conf = det.confidence if det else None
        snap = self._snapshot(frame_bgr, person.box)
        _record_event(
            self.camera_id, event_type, person.track_id, item,
            missing or [item], present_items, conf, snap, utcnow(),
            bbox=_bbox_obj(person.box, w, h),
        )

    def _maybe_emit_compliant(self, person, present_items, frame_bgr, h, w, now) -> None:
        # Cooldown-gate compliant events per track via the engine's last_seen-style
        # bookkeeping (reuse a simple per-track timestamp dict).
        key = f"compliant:{person.track_id}"
        last = getattr(self, "_compliant_last", {})
        if now - last.get(key, -1e12) < self.cooldown:
            return
        last[key] = now
        self._compliant_last = last
        snap = self._snapshot(frame_bgr, person.box)
        _record_event(
            self.camera_id, "ppe_compliant", person.track_id, None,
            [], present_items, person.confidence, snap, utcnow(),
            bbox=_bbox_obj(person.box, w, h),
        )

    def _snapshot(self, frame_bgr, box) -> str | None:
        """Persist the full annotated-free frame + a person crop. Returns the full
        snapshot key the /snapshot route serves, or None on failure."""
        if cv2 is None:
            return None
        frame_id = str(uuid.uuid4())
        try:
            base = config.DATA_PATH / "snapshots"
            base.mkdir(parents=True, exist_ok=True)
            ok, buf = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if not ok:
                return None
            (base / f"{frame_id}.jpg").write_bytes(buf.tobytes())
            # Person crop with context (0.15 padding, POC parity) for the events UI.
            try:
                x1, y1, x2, y2 = box
                pw, ph = x2 - x1, y2 - y1
                cx1 = max(0, int(x1 - 0.15 * pw)); cy1 = max(0, int(y1 - 0.15 * ph))
                cx2 = min(frame_bgr.shape[1], int(x2 + 0.15 * pw))
                cy2 = min(frame_bgr.shape[0], int(y2 + 0.15 * ph))
                crop = frame_bgr[cy1:cy2, cx1:cx2]
                if crop.size:
                    cok, cbuf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
                    if cok:
                        (base / f"{frame_id}_crop.jpg").write_bytes(cbuf.tobytes())
            except Exception:  # noqa: BLE001
                pass
            return f"/snapshot?key=live:{frame_id}"
        except Exception:  # noqa: BLE001
            return None
