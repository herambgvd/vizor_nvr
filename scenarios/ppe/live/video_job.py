"""Offline video-upload PPE compliance jobs.

A user uploads a video; this runs the SAME Triton PPE pipeline as the live worker
(detect → eligible → ROI gate → track → associate → smooth → compliance) over every
frame in a background thread, exposing the latest annotated frame as an MJPEG stream
so the browser watches detection happen, writing an annotated MP4, and recording each
violation / compliant event into the PPE events DB (so they show in the Events tab and
reports exactly like live events). The result page replays the annotated video plus a
per-worker compliance summary.

Inference is vizor's shared Triton detector (no ultralytics) — one model, GPU-efficient,
identical behaviour to live. ROI is the same build_roi / in_roi feet-in-zone gate.
"""
from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Generator, Optional

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
    evaluable_items,
    in_roi,
    positive_evidence,
)
from schemas import utcnow

from .worker import (
    _EVENT_TYPE,
    _bbox_obj,
    _draw_corner_box,
    _draw_status_card,
)

try:
    import cv2
    import numpy as np
except Exception:  # noqa: BLE001
    cv2 = None
    np = None

import logging

logger = logging.getLogger("ppe.video_job")

_BOX_GREEN = (70, 210, 90)
_BOX_RED = (60, 60, 235)

# Only process every Nth frame for detection (the rest are written through so the
# output video stays smooth). Matches the live worker's effective cadence.
_FRAME_STRIDE = max(1, int(getattr(config, "VIDEO_FRAME_STRIDE", 2)))


class VideoJob:
    """One uploaded-video processing job. Thread-safe status/frame access."""

    def __init__(self, job_id: str, input_path: Path, cfg: dict):
        self.job_id = job_id
        self.input_path = Path(input_path)
        self.config = cfg or {}

        self.state = "processing"           # processing | done | error
        self.error: Optional[str] = None
        self.started_at = datetime.utcnow().isoformat()

        self.total_frames = 0
        self.processed_frames = 0
        self.violation_count = 0
        self.compliant_count = 0

        self.output_key: Optional[str] = None   # rustfs object key for the annotated mp4
        self.alerts: list[dict] = []             # newest first (for the live sidebar)
        self._persons: dict[int, dict] = {}      # stable_id -> summary state

        self._latest_jpeg: Optional[bytes] = None
        self._lock = threading.Lock()

    # ── live frame buffer (MJPEG) ────────────────────────────────────────────
    def set_frame(self, frame) -> None:
        if cv2 is None:
            return
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if ok:
            with self._lock:
                self._latest_jpeg = buf.tobytes()

    def get_frame(self) -> Optional[bytes]:
        with self._lock:
            return self._latest_jpeg

    # ── status / result ──────────────────────────────────────────────────────
    @property
    def progress(self) -> float:
        if self.total_frames <= 0:
            return 0.0
        return round(min(100.0, (self.processed_frames / self.total_frames) * 100.0), 1)

    def status(self) -> dict:
        return {
            "job_id": self.job_id,
            "state": self.state,
            "error": self.error,
            "progress": self.progress,
            "processed_frames": self.processed_frames,
            "total_frames": self.total_frames,
            "violation_count": self.violation_count,
            "compliant_count": self.compliant_count,
            "alerts": self.alerts[:12],
            "result_url": f"/video/result/{self.job_id}" if self.state == "done" else None,
        }

    def result(self) -> dict:
        ordered = sorted(self._persons.values(), key=lambda s: s["order"])
        persons = []
        for i, st in enumerate(ordered):
            missing = sorted(st["missing"])
            persons.append({
                "person_number": i + 1,
                "track_id": st["display_id"],
                "missing": missing,
                "compliant": not missing,
            })
        return {
            "job_id": self.job_id,
            "output_key": self.output_key,
            "output_url": f"/video/output/{self.job_id}" if self.output_key else None,
            "frames": self.total_frames,
            "violation_count": self.violation_count,
            "compliant_count": self.compliant_count,
            "persons_summary": persons,
        }


class VideoJobManager:
    """In-process registry + background runner for video jobs (singleton)."""

    def __init__(self):
        self.jobs: dict[str, VideoJob] = {}
        self._lock = threading.Lock()

    def get(self, job_id: str) -> Optional[VideoJob]:
        with self._lock:
            return self.jobs.get(job_id)

    def start(self, input_path: Path, cfg: dict) -> VideoJob:
        job_id = "video_" + uuid.uuid4().hex[:10]
        job = VideoJob(job_id, input_path, cfg)
        with self._lock:
            self.jobs[job_id] = job
            # Evict the oldest finished jobs so the registry can't grow unbounded.
            done = [j for j in self.jobs.values() if j.state != "processing"]
            if len(done) > 12:
                for old in done[: len(done) - 12]:
                    self.jobs.pop(old.job_id, None)
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def _run(self, job: VideoJob) -> None:
        try:
            self._process(job)
            job.state = "done"
            logger.info("[video] job %s done (%d violations, %d persons)",
                        job.job_id, job.violation_count, len(job._persons))
        except Exception as exc:  # noqa: BLE001
            logger.exception("[video] job %s failed: %s", job.job_id, exc)
            job.error = str(exc)
            job.state = "error"
        finally:
            try:
                job.input_path.unlink(missing_ok=True)   # drop the raw upload
            except Exception:  # noqa: BLE001
                pass

    # ── the pipeline (mirrors the live worker, offline over a file) ──────────
    def _process(self, job: VideoJob) -> None:
        if cv2 is None:
            raise RuntimeError("OpenCV not available")
        from inference.triton_engine import detector
        from vizor_sdk import assign_track_ids, ByteTracker  # noqa: F401

        cfg = job.config
        required = cfg.get("required_items") or ["helmet", "vest"]
        required_canonical = [ITEM_TO_CANONICAL.get(i, i) for i in required]
        emit_compliant = bool(cfg.get("emit_compliant"))
        missing_grace = float(cfg.get("missing_grace", config.MISSING_GRACE))
        cooldown = float(cfg.get("cooldown", config.COOLDOWN))

        cap = cv2.VideoCapture(str(job.input_path))
        if not cap.isOpened():
            raise RuntimeError(f"could not open video: {job.input_path}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1280)
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 720)
        job.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

        out_path = Path(config.DATA_PATH) / "video_jobs" / f"{job.job_id}.mp4"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        writer = self._open_writer(out_path, fps, w, h)

        roi = build_roi(cfg.get("roi"), h, w)
        tracker = ByteTracker()
        stable = StableIdMapper(getattr(config, "STABLE_ID_MAX_AGE", 2.0))
        smoother = EvidenceSmoother(config.SMOOTH_WINDOW, config.SMOOTH_MIN_HITS)
        engine = ComplianceEngine(required_canonical, missing_grace,
                                  config.MIN_PRESENT, cooldown, config.ALERT_INITIAL_MISSING)
        compliant_last: dict[int, float] = {}
        alert_keys: set = set()
        frame_no = 0
        # A synthetic monotonic clock derived from frame index / fps so grace +
        # cooldown behave the same on a file as in real time.
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                frame_no += 1
                job.processed_frames = frame_no
                now = frame_no / max(1.0, fps)

                if frame_no % _FRAME_STRIDE != 0:
                    writer.write(frame)
                    if frame_no % 2 == 0:
                        job.set_frame(frame)
                    continue

                annotated = self._process_frame(
                    frame, detector, tracker, stable, smoother, engine, roi,
                    required_canonical, emit_compliant, cooldown, compliant_last,
                    alert_keys, job, now, w, h)
                writer.write(annotated)
                job.set_frame(annotated)
        finally:
            cap.release()
            writer.release()
            engine.purge(1e12)

        if job.total_frames <= 0:
            job.total_frames = frame_no

        # Push the annotated mp4 into rustfs (same object store live snapshots use).
        job.output_key = self._store_output(job.job_id, out_path)

    def _process_frame(self, frame, detector, tracker, stable, smoother, engine,
                       roi, required_canonical, emit_compliant, cooldown,
                       compliant_last, alert_keys, job, now, w, h):
        from vizor_sdk import assign_track_ids
        annotated = frame.copy()
        if roi is not None:
            try:
                cv2.polylines(annotated, [roi], True, (70, 200, 235),
                              max(2, int(round(2 * h / 720.0))), cv2.LINE_AA)
            except Exception:  # noqa: BLE001
                pass

        detections = detector.detect(frame)
        all_persons, items = [], []
        for d in detections:
            if d.label == "Person":
                if d.confidence >= config.PERSON_CONF:
                    all_persons.append(d)
            else:
                items.append(d)

        persons = deduplicate_persons(
            eligible_people(all_persons, h, w, config.MIN_PERSON_HEIGHT,
                            config.MIN_FOOT_Y, config.BORDER_MARGIN,
                            config.MAX_PERSON_ASPECT, config.MIN_PERSON_FRAC))
        if roi is not None:
            persons = [p for p in persons if in_roi(p, roi)]
        if not persons:
            engine.purge(now)
            return annotated

        dets_for_track = [(list(p.box), float(p.confidence)) for p in persons]
        raw_ids = assign_track_ids(tracker, dets_for_track)
        raw_tracked = [Detection(p.label, p.confidence, p.box, rid)
                       for p, rid in zip(persons, raw_ids) if rid]
        if not raw_tracked:
            engine.purge(now)
            return annotated
        persons = stable.update(raw_tracked, now)

        items = [it for it in items if it.confidence >= _item_floor(it.label)]
        linked = associate_ppe(persons, items, DEFAULT_RULES)
        try:
            crop_links = detector.detect_crops(frame, persons)
            linked = _merge_links(linked, crop_links)
        except Exception:  # noqa: BLE001
            pass

        active = {p.track_id for p in persons if p.track_id is not None}
        for person in persons:
            tid = person.track_id
            if tid is None:
                continue
            raw = linked.get(tid, {})
            stableev = smoother.update(tid, raw, job.processed_frames)
            evidence = positive_evidence(stableev, config.NO_HARDHAT_CONF, config.NEGATIVE_MARGIN)
            evaluable = evaluable_items(person.box, w, h, required_canonical, linked=stableev)
            fired = engine.update(tid, evidence, now, evaluable=evaluable)
            present_items = [CANONICAL_TO_ITEM.get(k, k) for k in evidence]
            item_colors = {c: (_BOX_GREEN if c in evidence else _BOX_RED)
                           for c in required_canonical}

            if fired:
                by_event: dict[str, list] = {}
                for ppe, event in fired.items():
                    by_event.setdefault(event, []).append(ppe)
                for event, ppes in by_event.items():
                    job.violation_count += 1
                    missing = [CANONICAL_TO_ITEM.get(r, r) for r in required_canonical
                               if r not in evidence] or [CANONICAL_TO_ITEM.get(p, p) for p in ppes]
                    self._emit_violation(job, person, event, evidence, missing,
                                         present_items, frame, annotated, item_colors, w, h)
                    self._track_alert(job, person, missing, alert_keys)
                _draw_corner_box(annotated, _ibox(person.box), _BOX_RED)
                _draw_status_card(annotated, _ibox(person.box), tid, item_colors)
            else:
                _draw_corner_box(annotated, _ibox(person.box), _BOX_GREEN)
                _draw_status_card(annotated, _ibox(person.box), tid, item_colors)
                if emit_compliant and _confidently_compliant(evidence, required_canonical):
                    if now - compliant_last.get(tid, -1e12) >= cooldown:
                        compliant_last[tid] = now
                        job.compliant_count += 1
                        self._emit_compliant(job, person, evidence, present_items,
                                             frame, w, h)
            # roll the per-worker summary
            st = job._persons.setdefault(tid, {"display_id": tid, "missing": set(),
                                                "order": len(job._persons)})
            for r in required_canonical:
                if r not in evidence:
                    st["missing"].add(CANONICAL_TO_ITEM.get(r, r))

        smoother.purge(active)
        engine.purge(now)
        return annotated

    # ── emission (events into the PPE DB, snapshots to disk) ─────────────────
    def _emit_violation(self, job, person, event, evidence, missing, present_items,
                        frame, annotated, item_colors, w, h):
        event_type = _EVENT_TYPE.get(event, "ppe_missing")
        primary = missing[0] if missing else None
        confs = [evidence[ITEM_TO_CANONICAL.get(m, m)].confidence
                 for m in missing if evidence.get(ITEM_TO_CANONICAL.get(m, m))]
        conf = max(confs) if confs else None
        snap = _save_snapshot(job.job_id, frame, person.box, _BOX_RED,
                              person.track_id, item_colors)
        _record_event(f"video:{job.job_id}", event_type, person.track_id, primary,
                      missing, present_items, conf, snap, utcnow(),
                      bbox=_bbox_obj(person.box, w, h))

    def _emit_compliant(self, job, person, evidence, present_items, frame, w, h):
        confs = [evidence[r].confidence for r in evidence]
        conf = min(confs) if confs else None
        item_colors = {c: _BOX_GREEN for c in evidence}
        snap = _save_snapshot(job.job_id, frame, person.box, _BOX_GREEN,
                              person.track_id, item_colors)
        _record_event(f"video:{job.job_id}", "ppe_compliant", person.track_id, None,
                      [], present_items, conf, snap, utcnow(),
                      bbox=_bbox_obj(person.box, w, h))

    def _track_alert(self, job, person, missing, alert_keys):
        key = (person.track_id, tuple(sorted(missing)))
        if key in alert_keys:
            return
        alert_keys.add(key)
        job.alerts.insert(0, {
            "track_id": person.track_id,
            "missing": missing,
            "created_at": utcnow().isoformat(),
        })

    # ── output video ─────────────────────────────────────────────────────────
    def _open_writer(self, out_path: Path, fps, w, h):
        for name in ("avc1", "mp4v"):
            fourcc = cv2.VideoWriter_fourcc(*name)
            writer = cv2.VideoWriter(str(out_path), fourcc, fps, (w, h))
            if writer.isOpened():
                logger.info("[video] writer codec %s", name)
                return writer
            writer.release()
        raise RuntimeError("could not open a video writer")

    def _store_output(self, job_id: str, out_path: Path) -> Optional[str]:
        """Upload the annotated mp4 to rustfs; fall back to the local path on failure."""
        key = f"video_jobs/{job_id}.mp4"
        try:
            from vizor_sdk.objectstore import default_store
            store = default_store()
            if store is not None:
                store.put(key, out_path.read_bytes(), content_type="video/mp4")
                return key
        except Exception as exc:  # noqa: BLE001
            logger.warning("[video] rustfs upload failed (%s) — serving from disk", exc)
        return f"local:{out_path}"


def _ibox(box):
    return tuple(int(v) for v in box)


def _item_floor(label: str) -> float:
    if label == "NO_Hardhat":
        return config.NO_HARDHAT_CONF
    if label == "Hardhat":
        return config.HARDHAT_CONF
    if label == "Safety_Vest":
        return config.VEST_CONF
    if label == "Goggles":
        return config.GOGGLES_CONF
    if label == "Boots":
        return config.BOOTS_CONF
    return config.HARDHAT_CONF


def _confidently_compliant(evidence: dict, required_canonical: list) -> bool:
    for req in required_canonical:
        det = evidence.get(req)
        if det is None or det.confidence < _item_floor(req):
            return False
    return True


def _merge_links(base: dict, extra: dict) -> dict:
    """Merge crop-stage detections into the full-frame links (keep the stronger)."""
    out = {tid: dict(d) for tid, d in base.items()}
    for tid, dets in (extra or {}).items():
        slot = out.setdefault(tid, {})
        for label, det in dets.items():
            cur = slot.get(label)
            if cur is None or det.confidence > cur.confidence:
                slot[label] = det
    return out


def _save_snapshot(job_id, frame, box, color, track_id, item_colors) -> Optional[str]:
    if cv2 is None:
        return None
    frame_id = str(uuid.uuid4())
    try:
        base = Path(config.DATA_PATH) / "snapshots"
        base.mkdir(parents=True, exist_ok=True)
        x1, y1, x2, y2 = (int(v) for v in box)
        try:
            pw, ph = x2 - x1, y2 - y1
            cx1, cy1 = max(0, int(x1 - 0.15 * pw)), max(0, int(y1 - 0.15 * ph))
            cx2 = min(frame.shape[1], int(x2 + 0.15 * pw))
            cy2 = min(frame.shape[0], int(y2 + 0.15 * ph))
            crop = frame[cy1:cy2, cx1:cx2]
            if crop.size:
                cok, cbuf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
                if cok:
                    (base / f"{frame_id}_crop.jpg").write_bytes(cbuf.tobytes())
        except Exception:  # noqa: BLE001
            pass
        annotated = frame.copy()
        _draw_corner_box(annotated, (x1, y1, x2, y2), color)
        if item_colors:
            _draw_status_card(annotated, (x1, y1, x2, y2), track_id, item_colors)
        ok, buf = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            return None
        (base / f"{frame_id}.jpg").write_bytes(buf.tobytes())
        return f"/snapshot?key=live:{frame_id}"
    except Exception:  # noqa: BLE001
        return None


def frame_generator(job_id: str) -> Generator[bytes, None, None]:
    """MJPEG multipart generator — streams the latest annotated frame of a job."""
    boundary = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
    placeholder = _placeholder_jpeg()
    while True:
        job = VIDEO_JOBS.get(job_id)
        if job is None:
            break
        frame = job.get_frame() or placeholder
        yield boundary + frame + b"\r\n"
        if job.state != "processing":
            final = job.get_frame() or placeholder
            yield boundary + final + b"\r\n"
            break
        time.sleep(0.08)


def _placeholder_jpeg() -> bytes:
    if cv2 is None or np is None:
        return b""
    canvas = np.zeros((480, 640, 3), dtype=np.uint8)
    canvas[:] = (17, 24, 39)
    cv2.putText(canvas, "Preparing video...", (130, 240),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (148, 163, 184), 2, cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", canvas)
    return buf.tobytes() if ok else b""


VIDEO_JOBS = VideoJobManager()
