"""Per-camera live recognition worker.

One worker per enabled camera. It pulls frames from go2rtc over RTSP with
ffmpeg, samples at the configured FPS, runs the recognition pipeline (or
detection-only), and writes FRS events + attendance — exactly the same outputs
the recorded video-jobs path produces, but in real time. Per-person alert
cooldown prevents event spam.
"""
from __future__ import annotations

import subprocess
import threading
import time
import uuid
from datetime import datetime

import config
import recognition
from db import session
from schemas import naive

try:
    import cv2
    import numpy as np
except Exception:  # noqa: BLE001
    cv2 = None
    np = None

# JPEG SOI/EOI markers — used to split the MJPEG byte stream ffmpeg pipes out.
_SOI = b"\xff\xd8"
_EOI = b"\xff\xd9"


def _bbox_obj(bbox):
    """Normalised [x1,y1,x2,y2] (0..1) → {x,y,w,h} the UI renders."""
    if not bbox or len(bbox) != 4:
        return None
    x1, y1, x2, y2 = bbox
    return {"x": round(x1, 4), "y": round(y1, 4), "w": round(x2 - x1, 4), "h": round(y2 - y1, 4)}


def _record_event(camera_id, person_id, person_name, confidence, snapshot_path, event_type, ts,
                  bbox=None, attributes=None):
    """Insert an FRS event; for recognised persons also upsert daily attendance."""
    from db.models import FRSAttendance, FRSEvent  # local import
    from sqlalchemy import select
    with session() as s:
        ev = FRSEvent(
            camera_id=camera_id, event_type=event_type, severity="info",
            title=person_name or ("Face detected" if event_type == "face_detected" else "Unknown face"),
            detection_type="face", person_id=person_id,
            confidence=round(float(confidence), 4) if confidence is not None else None,
            bbox=bbox, attributes=attributes,
            snapshot_path=snapshot_path, triggered_at=naive(ts) or ts,
        )
        s.add(ev)
        if person_id:
            face_snap = (attributes or {}).get("face_snapshot") or snapshot_path
            day_key = (ts or datetime.utcnow()).date().isoformat()
            existing = s.scalar(select(FRSAttendance).where(
                FRSAttendance.person_id == person_id, FRSAttendance.day_key == day_key))
            if existing:
                existing.check_out_at = naive(ts)
                existing.check_out_snapshot = face_snap
            else:
                s.add(FRSAttendance(person_id=person_id, camera_id=camera_id, day_key=day_key,
                                    check_in_at=naive(ts), check_in_snapshot=face_snap,
                                    sighting_type="seen", event_id=ev.id))
        s.commit()


class CameraWorker(threading.Thread):
    def __init__(self, cam: dict, report_state):
        super().__init__(daemon=True)
        self.cam = cam
        self.camera_id = cam["camera_id"]
        self.config_id = cam.get("config_id")
        self.config = cam.get("config") or {}
        self.report_state = report_state          # callback(config_id, state, error)
        self._stop = threading.Event()
        # Per-person last-event time for alert-suppression cooldown.
        self._last_seen: dict[str, float] = {}
        # Multi-frame consensus: IoU tracker + per-track vote buffer.
        from recognition.inference.tracker import IouTracker
        from recognition.inference.voting import TrackVoteBuffer
        self._tracker = IouTracker()
        self._votes = TrackVoteBuffer()
        # Cross-track embedding dedup (cosine ≥0.85 within 30s).
        self._recent_emb: list[tuple[float, list]] = []

    def stop(self):
        self._stop.set()

    # ── config helpers ────────────────────────────────────────────────────
    @property
    def fps(self) -> float:
        try:
            return float(self.config.get("fps") or config.LIVE_DEFAULT_FPS)
        except (TypeError, ValueError):
            return config.LIVE_DEFAULT_FPS

    @property
    def cooldown(self) -> int:
        try:
            return int(self.config.get("alert_suppress_seconds") or config.LIVE_ALERT_COOLDOWN)
        except (TypeError, ValueError):
            return config.LIVE_ALERT_COOLDOWN

    @property
    def min_conf(self) -> float:
        try:
            return float(self.config.get("min_confidence") or config.SIMILARITY_THRESHOLD)
        except (TypeError, ValueError):
            return config.SIMILARITY_THRESHOLD

    @property
    def detection_only(self) -> bool:
        # Detection-only OR recognition explicitly disabled → emit face_detected,
        # never identify.
        if bool(self.config.get("detection_enabled")):
            return True
        return not bool(self.config.get("recognition_enabled", True))

    def _cfg_num(self, key, default, cast):
        try:
            v = self.config.get(key)
            return cast(v) if v not in (None, "") else default
        except (TypeError, ValueError):
            return default

    # Quality-gate thresholds — per-camera config first, platform default else.
    @property
    def det_conf(self):
        return self._cfg_num("det_conf", config.LIVE_DET_CONF, float)

    @property
    def min_face_px(self):
        return self._cfg_num("min_face_px", config.LIVE_MIN_FACE_PX, int)

    @property
    def min_sharpness(self):
        return self._cfg_num("min_sharpness", config.LIVE_MIN_SHARPNESS, float)

    @property
    def max_pose_deg(self):
        return self._cfg_num("max_pose_deg", config.LIVE_MAX_POSE_DEG, float)

    @property
    def liveness_enabled(self) -> bool:
        return bool(self.config.get("liveness_enabled"))

    @property
    def liveness_threshold(self) -> float:
        try:
            return float(self.config.get("liveness_threshold") or config.LIVENESS_THRESHOLD)
        except (TypeError, ValueError):
            return config.LIVENESS_THRESHOLD

    @property
    def roi(self):
        r = self.config.get("roi")
        # Accept [[x,y],...] or [{points:[...]}] ; normalise to list-of-polygons.
        if not r:
            return None
        if isinstance(r, list) and r and isinstance(r[0], (list, tuple)) and len(r[0]) == 2:
            return [r]            # single flat polygon
        return r

    @property
    def vote_min_frames(self) -> int:
        # Fire on the first usable detection — wide/top-down NVR cameras give
        # brief, intermittent faces that rarely persist for multi-frame consensus,
        # so any dwell > 1 silently drops every event. Alert cooldown still
        # prevents spam per person.
        return 1

    def _rtsp_url(self) -> str:
        sid = self.cam.get("sub_stream_id") if config.LIVE_USE_SUBSTREAM else self.cam.get("stream_id")
        sid = sid or self.camera_id
        return f"rtsp://{config.GO2RTC_RTSP_HOST}:{config.GO2RTC_RTSP_PORT}/{sid}"

    def _ffmpeg(self) -> subprocess.Popen:
        # Decode RTSP → MJPEG at the analysis FPS, scaled down for speed.
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-rtsp_transport", "tcp", "-i", self._rtsp_url(),
            "-vf", f"fps={self.fps},scale=640:-1",
            "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "5", "pipe:1",
        ]
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10 ** 7)

    # ── main loop ─────────────────────────────────────────────────────────
    def run(self):
        backoff = 2
        while not self._stop.is_set():
            proc = None
            try:
                proc = self._ffmpeg()
                self.report_state(self.config_id, "running", None)
                backoff = 2
                self._consume(proc)
            except Exception as exc:  # noqa: BLE001
                self.report_state(self.config_id, "error", str(exc)[:200])
            finally:
                if proc and proc.poll() is None:
                    proc.kill()
            if self._stop.is_set():
                break
            # Stream dropped — back off and retry (camera may be briefly down).
            time.sleep(min(backoff, 30))
            backoff *= 2
        self.report_state(self.config_id, "stopped", None)

    def _consume(self, proc):
        buf = b""
        while not self._stop.is_set():
            chunk = proc.stdout.read(65536)
            if not chunk:
                break  # ffmpeg exited → outer loop retries
            buf += chunk
            # Extract complete JPEG frames from the pipe.
            while True:
                start = buf.find(_SOI)
                end = buf.find(_EOI, start + 2)
                if start == -1 or end == -1:
                    break
                frame = buf[start:end + 2]
                buf = buf[end + 2:]
                self._process_frame(frame)

    def _emb_is_dup(self, emb: list, now: float) -> bool:
        """Cross-track dedup: suppress a face whose embedding matches a recently
        seen one (cosine ≥0.85 within 30s)."""
        import numpy as _np
        self._recent_emb = [(t, e) for (t, e) in self._recent_emb if now - t < 30.0]
        if emb and self._recent_emb:
            v = _np.asarray(emb, dtype=_np.float32)
            for _t, e in self._recent_emb:
                if float(_np.dot(v, _np.asarray(e, dtype=_np.float32))) >= 0.85:
                    return True
        self._recent_emb.append((now, emb))
        return False

    def _process_frame(self, jpeg: bytes):
        now = time.time()
        ts = datetime.utcnow()
        try:
            self._votes.gc(now)
            result = recognition.analyze_frame(
                jpeg, min_conf=self.min_conf, roi=self.roi,
                with_liveness=self.liveness_enabled,
                with_demographics=True,
                det_conf=self.det_conf,
                min_face_px=self.min_face_px,
                min_sharpness=self.min_sharpness,
                max_pose_deg=self.max_pose_deg,
            )
            faces = result.get("faces", [])
            if not faces:
                return
            # Assign track ids by IoU so votes accumulate per face across frames.
            bboxes = [f["bbox_px"] for f in faces if f.get("bbox_px")]
            track_ids = self._tracker.update(bboxes, now) if bboxes else []
            ti = 0

            for f in faces:
                bbox_px = f.get("bbox_px")
                tid = track_ids[ti] if (bbox_px and ti < len(track_ids)) else 0
                if bbox_px:
                    ti += 1

                # Liveness gate → spoof_detected event, skip recognition.
                live = f.get("liveness")
                if self.liveness_enabled and live is not None and live < self.liveness_threshold:
                    if now - self._last_seen.get(f"spoof:{tid}", 0) >= self.cooldown:
                        self._last_seen[f"spoof:{tid}"] = now
                        snap, fc = self._snapshots(jpeg, bbox_px)
                        _record_event(self.camera_id, None, None, live, snap, "spoof_detected", ts,
                                      bbox=_bbox_obj(f.get("bbox")),
                                      attributes={"face_snapshot": fc, "liveness_score": live,
                                                  **self._demo_attr(f)})
                    continue

                if self.detection_only:
                    if now - self._last_seen.get(f"det:{tid}", 0) < self.cooldown:
                        continue
                    self._last_seen[f"det:{tid}"] = now
                    snap, fc = self._snapshots(jpeg, bbox_px)
                    _record_event(self.camera_id, None, None, f.get("confidence", 0.0),
                                  snap, "face_detected", ts, bbox=_bbox_obj(f.get("bbox")),
                                  attributes={"face_snapshot": fc, "liveness_score": live, **self._demo_attr(f)})
                    continue

                # Recognition: record a vote for this track, fire on consensus.
                m = f.get("match") or {}
                pid = m.get("person_id")
                import numpy as _np
                self._votes.record(self.camera_id, tid, pid, float(m.get("confidence") or 0.0),
                                   _np.asarray(f["embedding"], dtype=_np.float32),
                                   m.get("person_name"), now)
                if not self._votes.should_fire(self.camera_id, tid, now, min_frames=self.vote_min_frames):
                    continue
                consensus = self._votes.consensus(self.camera_id, tid)
                self._votes.clear(self.camera_id, tid)
                if consensus is None:
                    continue
                cpid, cscore, _emb, cname = consensus
                # Cross-track dedup so the same person isn't re-fired rapidly.
                if self._emb_is_dup(f["embedding"], now):
                    continue
                key = cpid or "__unknown__"
                if now - self._last_seen.get(key, 0) < self.cooldown:
                    continue
                self._last_seen[key] = now
                snap, fc = self._snapshots(jpeg, bbox_px)
                _record_event(self.camera_id, cpid, cname, cscore,
                              snap, "face_recognized" if cpid else "face_unknown", ts,
                              bbox=_bbox_obj(f.get("bbox")),
                              attributes={"face_snapshot": fc, "matched_photo_id": m.get("photo_id"),
                                          "liveness_score": live, **self._demo_attr(f)})
                # Drive transit sessions on a recognised person.
                if cpid:
                    try:
                        from live.transit_engine import on_recognition
                        on_recognition(cpid, self.camera_id, ts)
                    except Exception:  # noqa: BLE001
                        pass
        except Exception:  # noqa: BLE001 - never let one bad frame kill the worker
            return

    @staticmethod
    def _demo_attr(face) -> dict:
        d = face.get("demographics")
        if not d:
            return {}
        return {"age": d.get("age"), "age_range": d.get("age_range"),
                "gender": d.get("gender"), "gender_confidence": d.get("gender_confidence")}

    def _snapshots(self, jpeg: bytes, bbox_px=None) -> tuple[str | None, str | None]:
        """Persist the full frame and (when a bbox is known) a cropped face.
        Returns (full_snapshot_path, face_snapshot_path)."""
        frame_id = str(uuid.uuid4())
        full = None
        face = None
        try:
            base = config.DATA_PATH / "snapshots"
            base.mkdir(parents=True, exist_ok=True)
            (base / f"{frame_id}.jpg").write_bytes(jpeg)
            full = f"/snapshot?key=live:{frame_id}"
            # Crop the face region with a small margin.
            if bbox_px and cv2 is not None and np is not None:
                arr = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
                if arr is not None:
                    h, w = arr.shape[:2]
                    x1, y1, x2, y2 = bbox_px
                    mx = int((x2 - x1) * 0.25); my = int((y2 - y1) * 0.25)
                    cx1 = max(0, int(x1) - mx); cy1 = max(0, int(y1) - my)
                    cx2 = min(w, int(x2) + mx); cy2 = min(h, int(y2) + my)
                    crop = arr[cy1:cy2, cx1:cx2]
                    if crop.size:
                        ok, buf = cv2.imencode(".jpg", crop)
                        if ok:
                            (base / f"{frame_id}_face.jpg").write_bytes(buf.tobytes())
                            face = f"/snapshot?key=live:{frame_id}_face"
        except Exception:  # noqa: BLE001
            pass
        return full, face
