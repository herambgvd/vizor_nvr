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
# Operators only need two states: PPE Missing (a violation) or Compliant. The
# engine's "removed" (worn earlier, then taken off) is still "not wearing PPE
# now", so it's recorded as ppe_missing too — no confusing third state.
_EVENT_TYPE = {"PPE_MISSING": "ppe_missing", "PPE_REMOVED": "ppe_missing"}


# Status colors (BGR) — matches the POC overlay.
_BOX_RED = (45, 45, 235)      # violation
_BOX_GREEN = (70, 210, 90)    # compliant / present
_BOX_NEUTRAL = (155, 160, 168)
_BOX_DARK = (24, 28, 34)


def _translucent_panel(frame, tl, br, alpha=0.84) -> None:
    import cv2 as _cv2
    overlay = frame.copy()
    _cv2.rectangle(overlay, tl, br, _BOX_DARK, -1, _cv2.LINE_AA)
    _cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)


def _draw_helmet_icon(frame, center, color) -> None:
    import cv2 as _cv2
    cx, cy = center
    _cv2.ellipse(frame, (cx, cy + 1), (10, 9), 0, 180, 360, color, -1, _cv2.LINE_AA)
    _cv2.rectangle(frame, (cx - 12, cy + 1), (cx + 12, cy + 5), color, -1, _cv2.LINE_AA)
    _cv2.line(frame, (cx, cy - 7), (cx, cy + 1), (245, 245, 245), 1, _cv2.LINE_AA)


def _draw_vest_icon(frame, center, color) -> None:
    import cv2 as _cv2, numpy as _np
    cx, cy = center
    pts = [(cx - 9, cy - 10), (cx - 3, cy - 12), (cx, cy - 6), (cx + 3, cy - 12),
           (cx + 9, cy - 10), (cx + 12, cy + 11), (cx + 3, cy + 12),
           (cx + 2, cy + 2), (cx - 2, cy + 2), (cx - 3, cy + 12), (cx - 12, cy + 11)]
    _cv2.fillPoly(frame, [_np.array(pts, dtype=_np.int32)], color, _cv2.LINE_AA)
    _cv2.line(frame, (cx, cy - 5), (cx, cy + 11), (245, 245, 245), 1, _cv2.LINE_AA)


def _draw_status_card(frame, box, track_id, helmet_color, vest_color) -> None:
    """POC status card: a translucent panel anchored at the worker's feet showing
    the ID + a helmet and vest icon, each coloured green (worn) / red (missing)."""
    import cv2 as _cv2
    x1, y1, x2, y2 = (int(v) for v in box)
    card_w, card_h = 146, 42
    foot_x = (x1 + x2) // 2
    card_x = max(0, min(foot_x - card_w // 2, frame.shape[1] - card_w - 1))
    card_y = y2 - card_h - 6 if y2 >= card_h + 8 else y2 + 4
    card_y = max(0, min(card_y, frame.shape[0] - card_h - 1))
    _translucent_panel(frame, (card_x, card_y), (card_x + card_w, card_y + card_h))
    overall = _BOX_RED if _BOX_RED in (helmet_color, vest_color) else (
        _BOX_GREEN if helmet_color == vest_color == _BOX_GREEN else _BOX_NEUTRAL)
    _cv2.rectangle(frame, (card_x, card_y), (card_x + 4, card_y + card_h), overall, -1)
    _cv2.putText(frame, f"ID {track_id}", (card_x + 11, card_y + 25),
                 _cv2.FONT_HERSHEY_SIMPLEX, 0.53, (240, 243, 247), 1, _cv2.LINE_AA)
    if helmet_color is not None:
        _draw_helmet_icon(frame, (card_x + 91, card_y + 19), helmet_color)
    if vest_color is not None:
        _draw_vest_icon(frame, (card_x + 127, card_y + 20), vest_color)


def _draw_corner_box(frame, box, color) -> None:
    """Modern corner-bracket box (POC draw_corner_box): a thin base rectangle plus
    thicker accented corner brackets, stroke scaled to frame size. Reads clearly
    on both sub- and main-stream resolutions."""
    import cv2 as _cv2
    x1, y1, x2, y2 = (int(v) for v in box)
    scale = max(frame.shape[0] / 720.0, 1.0)
    base = max(2, int(round(2 * scale)))
    accent = max(4, int(round(4 * scale)))
    length = max(16, min(40, int(min(x2 - x1, y2 - y1) * 0.18)))
    _cv2.rectangle(frame, (x1, y1), (x2, y2), color, base, _cv2.LINE_AA)
    for start, end in (
        ((x1, y1), (x1 + length, y1)), ((x1, y1), (x1, y1 + length)),
        ((x2, y1), (x2 - length, y1)), ((x2, y1), (x2, y1 + length)),
        ((x1, y2), (x1 + length, y2)), ((x1, y2), (x1, y2 - length)),
        ((x2, y2), (x2 - length, y2)), ((x2, y2), (x2, y2 - length)),
    ):
        _cv2.line(frame, start, end, color, accent, _cv2.LINE_AA)


def _merge_links(primary: dict, secondary: dict) -> dict:
    """Confidence-wise fusion of full-frame + crop PPE evidence (proven worker's
    merge_links). Keeps the higher-confidence detection per (track, label)."""
    merged: dict = {}
    for source in (primary, secondary):
        for tid, obs in source.items():
            dst = merged.setdefault(tid, {})
            for label, det in obs.items():
                old = dst.get(label)
                if old is None or det.confidence > old.confidence:
                    dst[label] = det
    return merged


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
        # Set by the manager when this worker is being replaced by a fresh one on a
        # config change. A replaced worker must NOT report "stopped" in its finally
        # block — that race overwrote the new worker's "running" and left the UI
        # stuck on STARTING/stopped while the stream was actually live.
        self.replaced = False
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
        # max_age in frames — keep a track alive through long detection gaps so a
        # briefly-occluded / intermittently-detected person isn't re-numbered.
        self._tracker = ByteTracker(
            iou_threshold=0.10, max_age=150, high_thresh=0.30, low_thresh=0.10,
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
    def crop_stage(self) -> bool:
        # Second-stage per-person crop re-detection (steadier PPE evidence).
        return config.PPE_CROP_STAGE

    @property
    def min_person_frac(self) -> float:
        # Skip far/small people (height < this fraction of frame) — unreliable PPE.
        return self._cfg_num("min_person_frac", config.MIN_PERSON_FRAC, float)

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
            if not self.replaced:
                self.report_state(self.config_id, "error", str(exc)[:200])
        finally:
            # Skip the stopped report when a fresh worker has taken over (config
            # change) — otherwise this late report clobbers the new "running".
            if not self.replaced:
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
            # Log (rate-limited) instead of swallowing silently.
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
                            config.MIN_FOOT_Y, config.BORDER_MARGIN,
                            config.MAX_PERSON_ASPECT, self.min_person_frac)
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

        # Second-stage: re-detect PPE on per-person crops and merge (the proven
        # worker's detect_ppe_in_crops + merge_links). The full-frame pass alone
        # gives weak/intermittent PPE evidence on wide scenes, which makes a person
        # oscillate compliant<->missing; the crop pass steadies it.
        if self.crop_stage:
            try:
                crop_links = self._detector.detect_crops(frame_bgr, persons)
                linked = _merge_links(linked, crop_links)
            except Exception as exc:  # noqa: BLE001 — never kill the frame
                if self._frame_no % 100 == 0:
                    print(f"[ppe-live] {self.camera_id[:8]} crop stage error: {exc}", flush=True)

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
            # The engine fires per missing PPE item; collapse to ONE event per
            # person per event-type listing ALL missing items, so a worker without
            # helmet AND vest is a single "PPE Missing (helmet, vest)" event, not two.
            if fired:
                by_event: dict[str, list[str]] = {}
                for event, ppe in fired:
                    by_event.setdefault(event, []).append(ppe)
                for event, ppes in by_event.items():
                    self._dbg_violations += 1
                    self._emit(person, event, ppes, evidence, present_items, frame_bgr, h, w)
            # Optional positive compliant event — only when EVERY required item is
            # POSITIVELY detected above its own confidence floor (not merely "no
            # violation fired"). A weak/stray helmet box must not flip a person to
            # compliant; that was the source of the false "Compliant 34%".
            if self.emit_compliant and not fired and self._is_confidently_compliant(evidence):
                self._maybe_emit_compliant(person, evidence, present_items, frame_bgr, h, w, now)

        self._smoother.purge(active_ids)
        self._engine.purge(now)

    def _item_floor(self, label: str) -> float:
        # Per-camera operator overrides (Cameras tab) fall back to platform defaults.
        if label == "NO_Hardhat":
            return config.NO_HARDHAT_CONF
        if label == "Hardhat":
            return self._cfg_num("hardhat_conf", config.HARDHAT_CONF, float)
        if label == "Safety_Vest":
            return self._cfg_num("vest_conf", config.VEST_CONF, float)
        if label == "Goggles":
            return self._cfg_num("goggles_conf", config.GOGGLES_CONF, float)
        if label == "Boots":
            return self._cfg_num("boots_conf", config.BOOTS_CONF, float)
        return config.HARDHAT_CONF

    # ── emission ────────────────────────────────────────────────────────────
    def _status_colors(self, evidence: dict):
        """(helmet_color, vest_color) for the status card — green if the item is in
        evidence (worn), red if it's a required item that's missing, None if the
        item isn't required for this camera."""
        req = set(self.required_canonical)
        def _c(canon):
            if canon not in req:
                return None
            return _BOX_GREEN if canon in evidence else _BOX_RED
        return _c("Hardhat"), _c("Safety_Vest")

    def _emit(self, person, event, ppes, evidence, present_items, frame_bgr, h, w) -> None:
        event_type = _EVENT_TYPE.get(event, "ppe_missing")
        # ppes = all canonical PPE items missing for this person this fire.
        items = [CANONICAL_TO_ITEM.get(p, p) for p in ppes]
        primary = items[0] if items else None
        missing = [CANONICAL_TO_ITEM.get(r, r) for r in self.required_canonical
                   if r not in evidence] or items
        # Best available confidence among the fired items.
        confs = [evidence[p].confidence for p in ppes if evidence.get(p)]
        conf = max(confs) if confs else None
        hc, vc = self._status_colors(evidence)
        snap = self._snapshot(frame_bgr, person.box, _BOX_RED, person.track_id, hc, vc)
        _record_event(
            self.camera_id, event_type, person.track_id, primary,
            missing, present_items, conf, snap, utcnow(),
            bbox=_bbox_obj(person.box, w, h),
        )

    def _is_confidently_compliant(self, evidence: dict) -> bool:
        """True only when every required PPE item is present AND its detection
        confidence clears that item's floor — a real positive, not absence of a
        violation. Mirrors the proven worker requiring a positive PPE box."""
        for req in self.required_canonical:
            det = evidence.get(req)
            if det is None:
                return False
            # canonical req -> the detector label whose floor applies.
            floor = self._item_floor("Hardhat" if req == "Hardhat" else "Safety_Vest")
            if det.confidence < floor:
                return False
        return True

    def _maybe_emit_compliant(self, person, evidence, present_items, frame_bgr, h, w, now) -> None:
        # Cooldown-gate compliant events per track.
        key = f"compliant:{person.track_id}"
        last = getattr(self, "_compliant_last", {})
        if now - last.get(key, -1e12) < self.cooldown:
            return
        last[key] = now
        self._compliant_last = last
        # Compliance confidence = the WEAKEST required-PPE detection (the limiting
        # factor), NOT the person-box score (that was the bogus "34%").
        confs = [evidence[r].confidence for r in self.required_canonical if evidence.get(r)]
        conf = min(confs) if confs else None
        hc, vc = self._status_colors(evidence)
        snap = self._snapshot(frame_bgr, person.box, _BOX_GREEN, person.track_id, hc, vc)
        _record_event(
            self.camera_id, "ppe_compliant", person.track_id, None,
            [], present_items, conf, snap, utcnow(),
            bbox=_bbox_obj(person.box, w, h),
        )

    def _snapshot(self, frame_bgr, box, color=_BOX_RED, track_id=None,
                  helmet_color=None, vest_color=None) -> str | None:
        """Persist the full annotated frame (offender in a corner-bracket box +
        POC status card showing helmet/vest icons) + a person crop. Returns the
        snapshot key the /snapshot route serves, or None on failure."""
        if cv2 is None:
            return None
        frame_id = str(uuid.uuid4())
        try:
            base = config.DATA_PATH / "snapshots"
            base.mkdir(parents=True, exist_ok=True)
            x1, y1, x2, y2 = (int(v) for v in box)
            # Person crop with context (0.15 padding, POC parity) — saved FIRST,
            # from the clean frame, so the events UI can show the offender tightly.
            try:
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
            # Full frame with the person in a modern corner-bracket box (POC style)
            # so the operator can immediately locate them in context.
            annotated = frame_bgr.copy()
            # Draw the evaluation ROI (amber outline) + the worker's foot-point
            # (the bottom-centre dot ROI membership is tested against). This makes
            # it OBVIOUS why a person counted — a worker near the door still
            # evaluates if their feet fall inside the configured zone.
            if self._roi is not None:
                try:
                    roi_thick = max(2, int(round(2 * annotated.shape[0] / 720.0)))
                    cv2.polylines(annotated, [self._roi], True, (70, 200, 235), roi_thick, cv2.LINE_AA)
                except Exception:  # noqa: BLE001
                    pass
            foot = (int((x1 + x2) / 2), int(y2))
            cv2.circle(annotated, foot, max(4, int(annotated.shape[0] / 180)), color, -1, cv2.LINE_AA)
            _draw_corner_box(annotated, (x1, y1, x2, y2), color)
            if helmet_color is not None or vest_color is not None:
                _draw_status_card(annotated, (x1, y1, x2, y2), track_id, helmet_color, vest_color)
            ok, buf = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if not ok:
                return None
            (base / f"{frame_id}.jpg").write_bytes(buf.tobytes())
            return f"/snapshot?key=live:{frame_id}"
        except Exception:  # noqa: BLE001
            return None
