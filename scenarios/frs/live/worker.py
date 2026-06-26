"""Per-camera live recognition worker.

One worker per enabled camera. It pulls frames from go2rtc over RTSP with
ffmpeg, samples at the configured FPS, runs the recognition pipeline (or
detection-only), and writes FRS events + attendance — exactly the same outputs
the recorded video-jobs path produces, but in real time. Per-person alert
cooldown prevents event spam.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid

import config
import recognition
from db import session
from schemas import naive, utcnow

try:
    import cv2
    import numpy as np
except Exception:  # noqa: BLE001
    cv2 = None
    np = None

# JPEG SOI/EOI markers — used to split the MJPEG byte stream ffmpeg pipes out.
_SOI = b"\xff\xd8"
_EOI = b"\xff\xd9"

# Backpressure: cap the number of frames being analysed (Triton inference) across
# ALL camera workers at once. Without this, 64 workers fire inference
# simultaneously and thundering-herd the GPU → latency spikes + memory growth.
# A worker that can't acquire the slot quickly DROPS the frame (skip, don't queue).
_INFLIGHT = threading.Semaphore(int(os.getenv("FRS_MAX_INFLIGHT", "12")))


def _bbox_obj(bbox):
    """Normalised [x1,y1,x2,y2] (0..1) → {x,y,w,h} the UI renders."""
    if not bbox or len(bbox) != 4:
        return None
    x1, y1, x2, y2 = bbox
    return {"x": round(x1, 4), "y": round(y1, 4), "w": round(x2 - x1, 4), "h": round(y2 - y1, 4)}


# The event insert path now lives in db/events.py (shared with third-party
# ingest). Thin alias keeps this module's call sites unchanged.
from db.events import record_event as _record_event  # noqa: E402,F401


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
        # Per-person last-event time for alert-suppression cooldown.
        self._last_seen: dict[str, float] = {}
        # Multi-frame consensus: ByteTrack (Kalman + hi/lo split, vizor-gpu parity)
        # + per-track vote buffer. ByteTrack predicts the next bbox so fast-moving
        # faces keep a stable track id long enough to accrue consensus votes.
        from recognition.inference.tracker import ByteTracker
        from recognition.inference.voting import TrackVoteBuffer
        self._tracker = ByteTracker(iou_threshold=0.08, max_age=120,
                                    high_thresh=0.4, low_thresh=0.1)
        self._votes = TrackVoteBuffer()
        # Cross-track embedding dedup (cosine ≥0.85 within 30s).
        self._recent_emb: list[tuple[float, list]] = []
        # Per-track centroid for the motion-blur gate.
        self._prev_centroid: dict[int, tuple[float, float, float]] = {}
        # NVDEC: latch to software decode if the hardware pipe produces no frames
        # (no GPU / ffmpeg without cuvid) so a camera never silently goes dark.
        self._hw_failed = False
        self._used_hw = False
        # Diagnostics (for the /live/logs worker-logs panel).
        self._frame_no = 0
        self._dbg_faces = 0           # faces seen in the last processed frame
        self._dbg_recognized = 0      # cumulative recognised sightings
        from collections import deque
        self._log_buf: deque = deque(maxlen=80)

    def _log(self, level: str, msg: str) -> None:
        import time
        self._log_buf.append({"ts": time.time(), "level": level, "msg": msg})

    def logs(self) -> list:
        return list(self._log_buf)

    def stop(self):
        self._stop.set()

    # ── config helpers ────────────────────────────────────────────────────
    @property
    def direction(self) -> str:
        """Attendance role of this camera: 'entry' / 'exit' / 'both' (default)."""
        return str(self.config.get("direction") or "both").lower()

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
    def unknown_min_det_conf(self):
        # Min SCRFD detection confidence to EMIT an "Unknown" event (higher than the
        # detect threshold) so false detections (back-of-head/hand/blur) are tracked
        # but never surfaced as Unknown noise. Recognised faces are exempt.
        return self._cfg_num("unknown_min_det_conf", config.LIVE_UNKNOWN_MIN_DET_CONF, float)

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
        # Multi-frame consensus before emitting (vizor-gpu default = 5). Per-camera
        # config may override (e.g. lower for sparse top-down scenes), but firing on
        # a single frame produces flickery, low-confidence matches.
        return self._cfg_num("dwell_min_frames", config.LIVE_VOTE_MIN_FRAMES, int)

    def _rtsp_url(self) -> str:
        sid = self.cam.get("sub_stream_id") if config.LIVE_USE_SUBSTREAM else self.cam.get("stream_id")
        sid = sid or self.camera_id
        return f"rtsp://{config.GO2RTC_RTSP_HOST}:{config.GO2RTC_RTSP_PORT}/{sid}"

    def _ffmpeg(self) -> subprocess.Popen:
        # Decode RTSP → MJPEG at the analysis FPS. Native resolution (cap at 1920
        # wide to bound memory) — SCRFD letterboxes to 640 internally, so an
        # upstream downscale would starve far/small faces and wreck recognition.
        #
        # NVDEC path (FRS_HWACCEL=cuda): decode + scale on the GPU's dedicated
        # decoder engines so the CPU/GIL stay free at many-camera scale, then
        # hwdownload the frames to encode MJPEG for the pipe. Falls back to
        # software decode automatically when NVDEC yields no frames.
        use_hw = config.LIVE_HWACCEL == "cuda" and not self._hw_failed
        if use_hw:
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-rw_timeout", "10000000",  # 10s RTSP socket timeout (µs)
                "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
                "-rtsp_transport", "tcp", "-i", self._rtsp_url(),
                # scale on GPU (scale_cuda), then download to host for mjpeg encode.
                "-vf", (f"fps={self.fps},scale_cuda='min(1920,iw)':-2,"
                        "hwdownload,format=nv12"),
                "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "2", "pipe:1",
            ]
        else:
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-rw_timeout", "10000000",  # 10s RTSP socket timeout (µs)
                "-rtsp_transport", "tcp", "-i", self._rtsp_url(),
                "-vf", f"fps={self.fps},scale='min(1920,iw)':-2",
                "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "2", "pipe:1",
            ]
        self._used_hw = use_hw
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10 ** 7)

    # ── main loop ─────────────────────────────────────────────────────────
    def run(self):
        backoff = 2
        while not self._stop.is_set():
            proc = None
            frames = 0
            try:
                proc = self._ffmpeg()
                self.report_state(self.config_id, "running", None)
                backoff = 2
                frames = self._consume(proc)
            except Exception as exc:  # noqa: BLE001
                self.report_state(self.config_id, "error", str(exc)[:200])
            finally:
                if proc and proc.poll() is None:
                    proc.kill()
            if self._stop.is_set():
                break
            # NVDEC pipe produced nothing → GPU/cuvid unavailable. Latch to
            # software decode and retry immediately so the camera isn't dark.
            if self._used_hw and frames == 0 and not self._hw_failed:
                self._hw_failed = True
                print(f"[frs-live] {self.camera_id}: NVDEC unavailable, "
                      f"falling back to software decode", flush=True)
                continue
            # Stream dropped — back off and retry (camera may be briefly down).
            time.sleep(min(backoff, 30))
            backoff *= 2
        self.report_state(self.config_id, "stopped", None)

    def _consume(self, proc) -> int:
        buf = b""
        frames = 0
        # Stall watchdog: a blocking stdout.read() never returns if ffmpeg hangs
        # (camera wedged, network black hole) — the worker would sit dark forever.
        # A daemon thread kills the process if no chunk arrives within the stall
        # window, so the run loop reconnects.
        last_read = [time.time()]
        stall_secs = config.LIVE_STALL_TIMEOUT

        def _watchdog():
            while not self._stop.is_set() and proc.poll() is None:
                if time.time() - last_read[0] > stall_secs:
                    print(f"[frs-live] {self.camera_id}: decode stalled "
                          f"({stall_secs}s no data) — killing ffmpeg", flush=True)
                    try:
                        proc.kill()
                    except Exception:  # noqa: BLE001
                        pass
                    return
                time.sleep(1.0)

        wd = threading.Thread(target=_watchdog, daemon=True)
        wd.start()
        while not self._stop.is_set():
            chunk = proc.stdout.read(65536)
            last_read[0] = time.time()
            if not chunk:
                break  # ffmpeg exited / killed by watchdog → outer loop retries
            buf += chunk
            # Extract complete JPEG frames; BACKPRESSURE: if several frames arrived
            # in one read (we fell behind — GPU saturated), keep only the LATEST and
            # drop the stale ones so latency never snowballs. Recognition cares about
            # "is this person here now", not every intermediate frame.
            latest = None
            while True:
                start = buf.find(_SOI)
                end = buf.find(_EOI, start + 2)
                if start == -1 or end == -1:
                    break
                latest = buf[start:end + 2]
                buf = buf[end + 2:]
            if latest is not None:
                frames += 1
                self._process_frame(latest)
        return frames

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

    def _prune_state(self, now: float) -> None:
        """Bound the per-track dicts so a long-running worker doesn't leak memory:
        track ids increase forever, so _last_seen / _prev_centroid would grow
        without limit. Drop entries older than 5 minutes. (voting + tracker GC
        their own state; these two were the unbounded ones.)"""
        cutoff = now - 300.0
        self._prev_centroid = {k: v for k, v in self._prev_centroid.items() if v[2] > cutoff}
        if len(self._last_seen) > 2000:
            self._last_seen = {k: t for k, t in self._last_seen.items() if t > cutoff}

    def _process_frame(self, jpeg: bytes):
        now = time.time()
        self.last_frame_ts = now                   # heartbeat for /health liveness
        self._frame_no += 1
        if now - getattr(self, "_last_prune", 0) > 60:
            self._prune_state(now)
            self._last_prune = now
        # Backpressure: grab a global inference slot. If none free within 0.5s the
        # GPU is saturated — DROP this frame rather than pile up latency/memory.
        if not _INFLIGHT.acquire(timeout=0.5):
            return
        ts = utcnow()
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
            self._dbg_faces = len(faces)
            if not faces:
                return
            self._process_faces(faces, jpeg, ts, now)
        except Exception:  # noqa: BLE001 - never let one bad frame kill the worker
            return
        finally:
            _INFLIGHT.release()

    def _process_faces(self, faces, jpeg, ts, now) -> None:
        """Post-detection logic: track, vote, gate, fire events. CPU + light I/O
        (snapshot disk, qdrant index, event sink). Shared by the sync _process_frame
        and the async worker pipeline (run via run_in_executor). `jpeg` may be a BGR
        ndarray (the snapshot helper accepts both)."""
        try:
            # Assign track ids via ByteTrack so votes accumulate per face across
            # frames even when the face moves fast (Kalman-predicted association).
            from recognition.inference.tracker import assign_track_ids
            dets = [(f["bbox_px"], float(f.get("confidence") or 0.99))
                    for f in faces if f.get("bbox_px")]
            track_ids = assign_track_ids(self._tracker, dets) if dets else []
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
                        self._sink_event(self.camera_id, None, None, live, snap, "spoof_detected", ts,
                                         bbox=_bbox_obj(f.get("bbox")),
                                         attributes={"face_snapshot": fc, "liveness_score": live,
                                                     **self._demo_attr(f)})
                    continue

                if self.detection_only:
                    if now - self._last_seen.get(f"det:{tid}", 0) < self.cooldown:
                        continue
                    self._last_seen[f"det:{tid}"] = now
                    snap, fc = self._snapshots(jpeg, bbox_px)
                    self._sink_event(self.camera_id, None, None, f.get("confidence", 0.0),
                                     snap, "face_detected", ts, bbox=_bbox_obj(f.get("bbox")),
                                     attributes={"face_snapshot": fc, "liveness_score": live, **self._demo_attr(f)})
                    continue

                # High-confidence lock (vizor-gpu parity): once a track is firmly
                # recognized (score ≥ high_conf), stop re-evaluating it. Weak prior
                # hits stay open so a cleaner frame can still upgrade the identity.
                tstate = self._votes.state(self.camera_id, tid)
                if tstate is not None and tstate.get("status") == "recognized" \
                        and float(tstate.get("score", 0.0)) >= config.LIVE_HIGH_CONF_SCORE:
                    self._votes.touch_state(self.camera_id, tid, now)
                    continue

                # Motion-blur gate: skip recognition on a frame where the face
                # centroid moved a large fraction of its bbox (likely blurred);
                # the track stays alive so sharp frames still vote.
                if bbox_px:
                    cx = (bbox_px[0] + bbox_px[2]) / 2.0
                    cy = (bbox_px[1] + bbox_px[3]) / 2.0
                    bb_side = max(bbox_px[2] - bbox_px[0], bbox_px[3] - bbox_px[1])
                    prev = self._prev_centroid.get(tid)
                    self._prev_centroid[tid] = (cx, cy, now)
                    if prev is not None and bb_side > 1.0:
                        disp = ((cx - prev[0]) ** 2 + (cy - prev[1]) ** 2) ** 0.5
                        if disp / bb_side > config.LIVE_MOTION_BLUR_MAX_DISP_RATIO:
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
                event_type = "face_recognized" if cpid else "face_unknown"

                # False-positive gate for UNKNOWN events: SCRFD occasionally fires on a
                # back-of-head / hand / blurry patch — those produce a garbage embedding
                # that matches nobody, so they surface as "Unknown 0%" noise. Require a
                # higher detection confidence to EMIT an unknown than to detect, so weak
                # detections are tracked+voted but not turned into events. Recognised
                # faces (cpid set) are never suppressed.
                if not cpid and float(f.get("confidence") or 0.0) < self.unknown_min_det_conf:
                    continue

                # should_fire upgrade state-machine (vizor-gpu parity): fire on a
                # new track, on unknown→recognized upgrade, on a different person,
                # or when a weak prior recognition is beaten by ≥0.05.
                prior_status = tstate.get("status") if tstate else None
                prior_score = float(tstate.get("score", 0.0)) if tstate else 0.0
                prior_pid = tstate.get("person_id") if tstate else None
                should_fire = (
                    prior_status is None
                    or (prior_status == "unknown" and event_type == "face_recognized")
                    or (event_type == "face_recognized" and cpid != prior_pid)
                    or (prior_status == "recognized" and prior_score < config.LIVE_HIGH_CONF_SCORE
                        and cscore >= prior_score + 0.05)
                )
                self._votes.set_state(self.camera_id, tid,
                                      "recognized" if cpid else "unknown",
                                      cpid, cname, cscore, now)
                if not should_fire:
                    continue
                # Cross-track dedup so the same person isn't re-fired rapidly.
                if self._emb_is_dup(f["embedding"], now):
                    continue
                key = cpid or "__unknown__"
                if now - self._last_seen.get(key, 0) < self.cooldown:
                    continue
                self._last_seen[key] = now
                snap, fc = self._snapshots(jpeg, bbox_px)
                self._dbg_recognized += 1
                self._log("info", f"{event_type}: {cname or 'unknown'}"
                                  + (f" ({cscore:.2f})" if cscore else ""))
                # Only attach the matched gallery photo when the consensus actually
                # RECOGNISED the person (cpid set). A below-threshold frame-level match
                # must not leak onto an "Unknown" event — that showed a matched POI on
                # an Unknown row, which is contradictory.
                matched_photo = m.get("photo_id") if cpid else None
                ev_id = self._sink_event(self.camera_id, cpid, cname, cscore,
                                         snap, event_type, ts,
                                         bbox=_bbox_obj(f.get("bbox")),
                                         attributes={"face_snapshot": fc, "matched_photo_id": matched_photo,
                                                     "liveness_score": live, **self._demo_attr(f)},
                                         direction=self.direction)
                # Index this sighting's embedding into the SNAPSHOTS collection so
                # the Investigate (forensic) tab can search "where/when seen" —
                # mirrors vizor-app's frs_snapshots. Distinct from the gallery.
                self._index_snapshot(ev_id, f["embedding"], cpid, cname, cscore,
                                     snap, fc, ts, f.get("demographics"), live)
                # Drive transit sessions on a recognised person.
                if cpid:
                    try:
                        self._sink_transit(cpid, self.camera_id, ts, person_name=cname,
                                           snapshot_key=fc or snap)
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

    # ── event sink seam ──────────────────────────────────────────────────────
    # The recognition pipeline routes EVERY event + transit-drive through these two
    # methods instead of calling record_event / on_recognition directly. The default
    # impl writes to Postgres inline (the legacy path — unchanged behaviour). The
    # Redis-worker subclass overrides them to emit onto ai:events, so the events
    # bridge does the DB write off the worker. Keeps recognition/snapshot/qdrant in
    # the worker and DB/transit in the app.
    def _sink_event(self, camera_id, person_id, person_name, confidence, snapshot_path,
                    event_type, ts, bbox=None, attributes=None, direction=None) -> str:
        return _record_event(camera_id, person_id, person_name, confidence, snapshot_path,
                             event_type, ts, bbox=bbox, attributes=attributes, direction=direction)

    def _sink_transit(self, person_id, camera_id, ts, person_name=None, snapshot_key=None) -> None:
        from live.transit_engine import on_recognition
        on_recognition(person_id, camera_id, ts, person_name=person_name, snapshot_key=snapshot_key)

    def _index_snapshot(self, event_id, embedding, person_id, person_name, score,
                        snapshot, face_snapshot, ts, demographics, liveness) -> None:
        """Upsert a live sighting's face embedding into the SNAPSHOTS collection
        for forensic search. Payload carries everything Investigate displays."""
        try:
            from qdrant import store as qstore
            d = demographics or {}
            payload = {
                "event_id": event_id, "camera_id": self.camera_id,
                "person_id": person_id, "person_name": person_name,
                "similarity_score": round(float(score or 0.0), 4),
                "event_type": "face_recognized" if person_id else "face_unknown",
                "frame_timestamp": (ts or utcnow()).isoformat(),
                "snapshot_path": snapshot, "face_snapshot": face_snapshot,
                "liveness_score": liveness,
                "age": d.get("age"), "age_range": d.get("age_range"),
                "gender": d.get("gender"), "gender_confidence": d.get("gender_confidence"),
            }
            pid = str(event_id) if event_id else str(uuid.uuid4())
            qstore.upsert(pid, list(embedding), payload, collection=qstore.SNAPSHOTS_COLLECTION)
        except Exception:  # noqa: BLE001
            pass

    def _snapshots(self, jpeg: bytes, bbox_px=None) -> tuple[str | None, str | None]:
        """Persist the full frame and (when a bbox is known) a cropped face.
        Returns (full_snapshot_path, face_snapshot_path)."""
        frame_id = str(uuid.uuid4())
        full = None
        face = None
        try:
            base = config.DATA_PATH / "snapshots"
            base.mkdir(parents=True, exist_ok=True)
            # `jpeg` may be JPEG bytes (legacy ffmpeg path) OR a BGR ndarray (the live
            # GStreamer worker, which no longer re-encodes every frame). Get both the
            # bytes to persist and the BGR array for the crop, encoding only here.
            if np is not None and isinstance(jpeg, np.ndarray):
                arr = jpeg
                ok, buf = cv2.imencode(".jpg", arr, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
                jpeg_bytes = buf.tobytes() if ok else b""
            else:
                jpeg_bytes = jpeg
                arr = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR) \
                    if (cv2 is not None and np is not None) else None
            (base / f"{frame_id}.jpg").write_bytes(jpeg_bytes)
            full = f"/snapshot?key=live:{frame_id}"
            # Face crop — vizor-app parity: 0.6 margin (head + context), normalise
            # to 384px long edge, JPEG q92. Produces clean, consistent face shots.
            if bbox_px and cv2 is not None and np is not None:
                if arr is not None:
                    h, w = arr.shape[:2]
                    x1, y1, x2, y2 = bbox_px
                    mx = int((x2 - x1) * 0.6); my = int((y2 - y1) * 0.6)
                    cx1 = max(0, int(x1) - mx); cy1 = max(0, int(y1) - my)
                    cx2 = min(w, int(x2) + mx); cy2 = min(h, int(y2) + my)
                    crop = arr[cy1:cy2, cx1:cx2]
                    if crop.size:
                        ch, cw = crop.shape[:2]
                        long_edge = max(ch, cw)
                        if long_edge != 384:
                            scale = 384.0 / long_edge
                            interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_LANCZOS4
                            crop = cv2.resize(crop, (max(1, int(cw * scale)), max(1, int(ch * scale))), interpolation=interp)
                        ok, buf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
                        if ok:
                            (base / f"{frame_id}_face.jpg").write_bytes(buf.tobytes())
                            face = f"/snapshot?key=live:{frame_id}_face"
        except Exception:  # noqa: BLE001
            pass
        return full, face
