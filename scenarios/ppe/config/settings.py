"""PPE Compliance scenario plugin configuration — env-bound settings + the proven
POC thresholds.

Inference runs on the shared Triton server (model ``ppe_yolo26``); this plugin is
a thin client that owns the YOLO pre/post-processing + the temporal compliance
logic. Defaults are the POC's proven values (run_video.py argparse defaults) — do
NOT loosen them without footage validation; they were tuned to stop false
violations while still catching real ones.
"""
from __future__ import annotations

import os
from pathlib import Path

PORT = int(os.getenv("PORT", "8092"))
SCENARIO_SLUG = os.getenv("SCENARIO_SLUG", "ppe")
VERSION = "1.0.0"

# ── NVR wiring ───────────────────────────────────────────────────────────────
VIZOR_BASE_URL = os.getenv("VIZOR_BASE_URL", "http://backend:8000/api").rstrip("/")
VIZOR_API_KEY = os.getenv("VIZOR_API_KEY", "")
VIZOR_SERVICE_TOKEN = os.getenv("VIZOR_SERVICE_TOKEN", "")

# ── Own Postgres (separate from the NVR DB, mirrors FRS) ─────────────────────
# A dedicated ppe-db Postgres service. Sync engine — single process, short ops.
PPE_DATABASE_URL = os.getenv(
    "PPE_DATABASE_URL", "postgresql+psycopg2://ppe:ppe@ppe-db:5432/ppe"
)
DATA_PATH = Path(os.getenv("DATA_PATH", "/data/ppe"))

# ── Email (scheduled report delivery) ──────────────────────────────────────
SMTP_HOST = os.getenv("PPE_SMTP_HOST", "")
SMTP_PORT = int(os.getenv("PPE_SMTP_PORT", "587"))
SMTP_USER = os.getenv("PPE_SMTP_USER", "")
SMTP_PASSWORD = os.getenv("PPE_SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("PPE_SMTP_FROM", SMTP_USER or "noreply@vizor.local")
SMTP_TLS = os.getenv("PPE_SMTP_TLS", "1").lower() in ("1", "true", "yes", "on")
REPORTS_DIR = DATA_PATH / "reports"

# ── Inference (shared Triton) ────────────────────────────────────────────────
# 'triton' → shared Triton server (production, batched). The plugin decodes the
# raw [1,300,6] ppe_yolo26 output itself; no in-process torch/ultralytics.
INFERENCE_BACKEND = os.getenv("INFERENCE_BACKEND", "triton")
TRITON_URL = os.getenv("TRITON_URL", "triton:8000")
# TensorRT FP16 engine by default (~10x faster than the ONNX path, same accuracy);
# falls back to "ppe_yolo26" (ONNX) if the .plan isn't built on this box.
PPE_MODEL_NAME = os.getenv("PPE_MODEL_NAME", "ppe_yolo26_trt")
PPE_MODEL_INPUT = os.getenv("PPE_MODEL_INPUT", "images")
PPE_MODEL_OUTPUT = os.getenv("PPE_MODEL_OUTPUT", "output0")
# 1536 matches the client-proven POC inference size. Higher resolution greatly
# improves recall on distant / crowded / top-down workers: at 1280 far people score
# below the track-birth threshold and get dropped; at 1536 their confidence roughly
# doubles so they are actually detected + tracked. Must equal the Triton ppe_yolo26
# input dims (config.pbtxt) — rebuild the ONNX + TRT plan at 1536.
PPE_MODEL_IMGSZ = int(os.getenv("PPE_MODEL_IMGSZ", "1536"))
# Second-stage per-person crop PPE re-detection (the proven worker's
# detect_ppe_in_crops). Steadies helmet/vest evidence so a person doesn't
# oscillate compliant<->missing. One extra Triton call per person per frame —
# fine at the analyze-fps cap. Disable to fall back to full-frame-only. (Used only by
# the legacy non-v2 path; the v2/processor pipeline doesn't run the crop stage.)
PPE_CROP_STAGE = os.getenv("PPE_CROP_STAGE", "false").lower() in ("1", "true", "yes", "on")

# Second-stage verifiers (SigLIP / DINOv2) were REMOVED — the new YOLO26 PPE model is
# trained on the negative classes (no_helmet/no_gloves/no_boots) directly and the v2
# association + ReID + lifecycle pipeline handles accuracy, so no veto/rescue stage is
# needed (and it frees the extra VRAM + per-crop inference).

# ── Detection / compliance thresholds (client-proven POC gvd_ppe_poc defaults) ──
# The POC pipeline (utils/*) was validated on the client's (SMCC) footage; these are
# its exact utils/config.py values. The ported pipeline (pipeline/association_engine,
# compliance_engine_poc, tracker_manager, event_manager) reads these. Do NOT loosen
# without footage validation.
#
# Decode floor — drop the NMS-baked export's low-score padding rows before any
# per-class logic. Kept just under the lowest real per-class gate (person 0.35).
DECODE_SCORE_FLOOR = float(os.getenv("PPE_DECODE_SCORE_FLOOR", "0.12"))
# POC per-CATEGORY gates (utils/config.py) — a single floor per category, NOT per item:
#   persons kept lower (occluded / far still detected); PPE + negatives higher to
#   suppress false positives (a helmet on a door handle, a shirt read as a vest).
# This per-category split is what the POC's detector applies and is the key change
# that cuts vest false-alerts vs the old per-item helmet-0.10/vest-0.35 split.
PERSON_CONF = float(os.getenv("PPE_PERSON_CONF", "0.35"))
PPE_CONF = float(os.getenv("PPE_PPE_CONF", "0.50"))            # all positive PPE
NEG_PPE_CONF = float(os.getenv("PPE_NEG_CONF", "0.50"))        # all negative PPE
# Minimum person bbox area (px^2) before a violation is raised — far/tiny persons
# can't be judged reliably, so they must not create (false) events (POC).
MIN_PERSON_BBOX_AREA = int(os.getenv("PPE_MIN_PERSON_AREA", "9000"))
# Per-track person-confidence gate INSIDE compliance (distinct from the 0.35 detection
# gate) — POC ComplianceRuleSet.min_person_confidence.
MIN_PERSON_CONFIDENCE = float(os.getenv("PPE_MIN_PERSON_CONFIDENCE", "0.50"))
# Temporal confirmation of missing PPE (per tracked worker): only flag PPE missing when
# it is absent in >= MIN_MISSING of the last WINDOW observed frames AND currently absent.
# Kills single-frame association dropouts (worker turned / briefly occluded). POC 6-of-8.
PPE_CONFIRM_WINDOW = int(os.getenv("PPE_CONFIRM_WINDOW", "8"))
PPE_CONFIRM_MIN_MISSING = int(os.getenv("PPE_CONFIRM_MIN_MISSING", "6"))
# Association (POC) — PPE→person match floor + same-person-last-frame bonus.
ASSOCIATION_MIN_SCORE = float(os.getenv("PPE_ASSOCIATION_MIN_SCORE", "0.28"))
TEMPORAL_ASSOC_BONUS = float(os.getenv("PPE_TEMPORAL_ASSOC_BONUS", "0.12"))
COOLDOWN = float(os.getenv("PPE_COOLDOWN", "30.0"))            # per-identity/ppe event gap (s)

# ── Event lifecycle (POC EventManager: OBSERVED→NEW→ACTIVE→RESOLVED→EXPIRED) ──
# Frames a violation must persist before an event is created; seconds missing before
# RESOLVED; seconds before the incident is forgotten; duplicate-suppression cooldown.
VIOLATION_PERSISTENCE_FRAMES = int(os.getenv("PPE_PERSISTENCE_FRAMES", "5"))
EVENT_RESOLVE_AFTER_SECONDS = float(os.getenv("PPE_RESOLVE_AFTER_SECONDS", "4"))
EVENT_EXPIRE_AFTER_SECONDS = float(os.getenv("PPE_EXPIRE_AFTER_SECONDS", "120"))
DUPLICATE_COOLDOWN_SECONDS = float(os.getenv("PPE_DUPLICATE_COOLDOWN_SECONDS", "30"))

# ── Legacy v2 / non-v2 thresholds (kept defined for back-compat; NOT read by the
# ported POC pipeline). Do not tune — set the POC constants above instead. ──
HARDHAT_CONF = float(os.getenv("PPE_HARDHAT_CONF", "0.10"))
VEST_CONF = float(os.getenv("PPE_VEST_CONF", "0.35"))
GOGGLES_CONF = float(os.getenv("PPE_GOGGLES_CONF", "0.35"))
BOOTS_CONF = float(os.getenv("PPE_BOOTS_CONF", "0.35"))
NO_HARDHAT_CONF = float(os.getenv("PPE_NO_HARDHAT_CONF", "0.15"))
NO_VEST_CONF = float(os.getenv("PPE_NO_VEST_CONF", str(NO_HARDHAT_CONF)))
NO_GOGGLES_CONF = float(os.getenv("PPE_NO_GOGGLES_CONF", str(NO_HARDHAT_CONF)))
NO_BOOTS_CONF = float(os.getenv("PPE_NO_BOOTS_CONF", str(NO_HARDHAT_CONF)))
PPE_PRESENCE_MIN_FRAC = float(os.getenv("PPE_PRESENCE_MIN_FRAC", "0.3"))
NEGATIVE_MARGIN = float(os.getenv("PPE_NEGATIVE_MARGIN", "1.20"))
IOU = float(os.getenv("PPE_IOU", "0.50"))
MISSING_GRACE = float(os.getenv("PPE_MISSING_GRACE", "2.0"))
MIN_PRESENT = float(os.getenv("PPE_MIN_PRESENT", "3.0"))
V2_PPE_CONF = float(os.getenv("PPE_V2_CONF", "0.35"))

# Person Re-ID (stable worker identity across ByteTrack id changes) — AI-Powered parity.
# Uses the shared `person_reid` Triton model + numpy cosine matcher (no torch). Default
# ON; set PPE_REID=0 to key compliance/events off the raw track id instead.
PPE_REID = os.getenv("PPE_REID", "1").lower() not in ("0", "false", "no", "off")
# Event lifecycle: emit ONE event per confirmed compliance-status transition per worker
# (enter compliant / remove helmet / re-wear), not one per frame. enter_frames = how many
# frames a new status must persist before it commits (blink absorption); expire = drop a
# worker not seen this long (incident closed). Default 3 — on night/low-light or far-camera
# streams detection is intermittent, and a higher value (6) rarely accumulates enough
# consecutive same-status frames to ever commit (so no events fire). The presence smoother
# + dup-cooldown still suppress per-frame churn.
PPE_LIFECYCLE_ENTER_FRAMES = int(os.getenv("PPE_LIFECYCLE_ENTER_FRAMES", "3"))
PPE_LIFECYCLE_EXPIRE_S = float(os.getenv("PPE_LIFECYCLE_EXPIRE_S", "8.0"))
# Same worker+kind not re-emitted within this window (AI-Powered DUPLICATE_COOLDOWN) —
# stops a worker whose helmet flickers across the threshold from spamming events.
PPE_LIFECYCLE_DUP_COOLDOWN_S = float(os.getenv("PPE_LIFECYCLE_DUP_COOLDOWN_S", "30.0"))
# ByteTrack tuning — POC custom_bytetrack.yaml values (client-proven). high_thresh =
# confidence to START a track (POC 0.45: sub-0.45 people are detected at the 0.35 gate
# but not track-birthed until they strengthen — this is intended POC behaviour).
PPE_TRACK_HIGH_THRESH = float(os.getenv("PPE_TRACK_HIGH_THRESH", "0.45"))
PPE_TRACK_LOW_THRESH = float(os.getenv("PPE_TRACK_LOW_THRESH", "0.10"))
PPE_TRACK_MATCH_THRESH = float(os.getenv("PPE_TRACK_MATCH_THRESH", "0.80"))
PPE_TRACK_BUFFER = int(os.getenv("PPE_TRACK_BUFFER", "120"))
PPE_REID_MODEL_NAME = os.getenv("PPE_REID_MODEL_NAME", "person_reid_trt")
# POC REID_SIMILARITY_THRESHOLD = 0.90. NOTE: tuned for POC's 512-d local torchreid
# osnet_x0_25; vizor uses the 768-d Triton person_reid model (different similarity
# calibration). If identities fragment on SMCC footage this is the ONE value that may
# legitimately need empirical re-tuning down — document any deviation.
PPE_REID_THRESHOLD = float(os.getenv("PPE_REID_THRESHOLD", "0.90"))
PPE_REID_HISTORY = int(os.getenv("PPE_REID_HISTORY", "50"))
PPE_REID_MAX_UNKNOWN = int(os.getenv("PPE_REID_MAX_UNKNOWN", "5"))
# Forget an identity unseen this long (POC REID_MAX_AGE_SECONDS); re-extract the OSNet
# embedding for an already-tracked person only every N processed frames (POC speed +
# stability trick — feeds the 0.8*old+0.2*new embedding smoothing).
PPE_REID_MAX_AGE_SECONDS = float(os.getenv("PPE_REID_MAX_AGE_SECONDS", "12"))
PPE_REID_EMBED_REFRESH = int(os.getenv("PPE_REID_EMBED_REFRESH", "15"))
# Missing must persist this long (s) before a violation fires under v2 — AI-Powered used
# ~5 frames of persistence; at a few processed FPS that's ~1s. Keeps a one-frame helmet
# drop from raising a false alert.
# Seconds an item must stay absent before it counts as a violation. Raised from 1.0
# so a brief vest/helmet detection drop (a worker turning, a momentary occlusion)
# doesn't immediately fire a false alert — especially for the vest, which has no
# no_vest class and is judged by absence alone.
V2_MISSING_GRACE = float(os.getenv("PPE_V2_MISSING_GRACE", "2.5"))
ALERT_INITIAL_MISSING = os.getenv("PPE_ALERT_INITIAL_MISSING", "true").lower() in (
    "1", "true", "yes", "on",
)

# Temporal smoothing window (frames) — flicker rejection. A wider window + higher
# min-hits steadies a noisy detector so a person doesn't flip missing<->compliant
# frame to frame.
# Wider window so a brief detection gap (helmet hidden for a few frames while a
# seated worker looks down) doesn't collapse the evidence and flicker a violation.
SMOOTH_WINDOW = int(os.getenv("PPE_SMOOTH_WINDOW", "24"))
SMOOTH_MIN_HITS = int(os.getenv("PPE_SMOOTH_MIN_HITS", "5"))
# Relink window — how long a worker's stable id survives while detection drops
# out. Raised so an intermittently-detected person keeps ONE id (and thus one
# cooldown) instead of churning into a new id + a fresh alert every few seconds.
STABLE_ID_MAX_AGE = float(os.getenv("PPE_STABLE_ID_MAX_AGE", "12.0"))  # relink seconds

# Eligibility gates (suppress edge / artifact tracks).
MIN_PERSON_HEIGHT = int(os.getenv("PPE_MIN_PERSON_HEIGHT", "80"))
MIN_FOOT_Y = float(os.getenv("PPE_MIN_FOOT_Y", "0.20"))
BORDER_MARGIN = int(os.getenv("PPE_BORDER_MARGIN", "6"))
# Reject tall+thin false 'person' boxes (water bottle, pole). Real worker ~<=4:1.
MAX_PERSON_ASPECT = float(os.getenv("PPE_MAX_PERSON_ASPECT", "4.5"))
# Minimum person height as a FRACTION of frame height. A far/small person (e.g.
# someone at a doorway) is too low-res for reliable PPE detection and tends to
# produce false PPE (a shirt read as a vest), so skip them. 0 = disabled.
# Min person height as a fraction of frame height to be eligible. 0.22 dropped far/small
# workers on wide-angle DVR cams (a top client accuracy complaint); 0.08 keeps them.
# Operators can raise it per-camera via the "Min person size" slider.
MIN_PERSON_FRAC = float(os.getenv("PPE_MIN_PERSON_FRAC", "0.08"))

# Default required PPE when a camera does not configure it. Canonical labels.
REQUIRED_PPE_DEFAULT = [
    x.strip() for x in os.getenv("PPE_REQUIRED_DEFAULT", "helmet,vest").split(",") if x.strip()
]

# ── Data retention (storage-limitation) ──────────────────────────────────────
RETENTION_EVENT_DAYS = int(os.getenv("PPE_RETENTION_EVENT_DAYS", "90"))
RETENTION_SWEEP_HOURS = float(os.getenv("PPE_RETENTION_SWEEP_HOURS", "6"))
RETENTION_BATCH = int(os.getenv("PPE_RETENTION_BATCH", "2000"))
DISK_WARN_PERCENT = float(os.getenv("PPE_DISK_WARN_PERCENT", "90"))

# ── Live per-camera workers (go2rtc RTSP restream) ───────────────────────────
LIVE_ENABLED = os.getenv("PPE_LIVE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
GO2RTC_RTSP_HOST = os.getenv("GO2RTC_RTSP_HOST", "go2rtc")
GO2RTC_RTSP_PORT = int(os.getenv("GO2RTC_RTSP_PORT", "8554"))
LIVE_POLL_SECONDS = int(os.getenv("PPE_LIVE_POLL_SECONDS", "15"))
LIVE_DEFAULT_FPS = float(os.getenv("PPE_LIVE_FPS", "5"))
# Pull the MAIN stream by default — sub-streams are too low-res for small PPE.
LIVE_USE_SUBSTREAM = os.getenv("PPE_LIVE_SUBSTREAM", "false").lower() in ("1", "true", "yes", "on")
LIVE_HWACCEL = os.getenv("PPE_HWACCEL", "none").lower()   # cuda | none
LIVE_STALL_TIMEOUT = int(os.getenv("PPE_LIVE_STALL_TIMEOUT", "20"))
LIVE_MAX_WIDTH = int(os.getenv("PPE_LIVE_MAX_WIDTH", "1920"))

DATA_PATH.mkdir(parents=True, exist_ok=True)
# scenario.json lives at the package root (one level up from config/).
MANIFEST_PATH = Path(__file__).resolve().parent.parent / "scenario.json"
