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
# 1280 matches the POC's full-frame inference size (the model is exported at
# 1280); 640 lost too much detail on wide/top-down scenes -> weak persons + false
# PPE. Must equal the Triton ppe_yolo26 input dims.
PPE_MODEL_IMGSZ = int(os.getenv("PPE_MODEL_IMGSZ", "1280"))
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

# ── Detection / compliance thresholds (POC run_video.py defaults) ────────────
# Decode floor — drop the NMS-baked export's low-score padding rows before any
# per-class logic. Just under the lowest real per-class threshold.
DECODE_SCORE_FLOOR = float(os.getenv("PPE_DECODE_SCORE_FLOOR", "0.12"))
# POC-proven floors (these gave good accuracy AT 1280 input). The earlier
# false-compliant was a 640-resolution artifact, not a threshold problem — fixed
# by the 1280 export. Operators can still raise helmet/vest per camera in the UI.
PERSON_CONF = float(os.getenv("PPE_PERSON_CONF", "0.20"))
HARDHAT_CONF = float(os.getenv("PPE_HARDHAT_CONF", "0.10"))
VEST_CONF = float(os.getenv("PPE_VEST_CONF", "0.50"))
GOGGLES_CONF = float(os.getenv("PPE_GOGGLES_CONF", "0.35"))
BOOTS_CONF = float(os.getenv("PPE_BOOTS_CONF", "0.35"))
NO_HARDHAT_CONF = float(os.getenv("PPE_NO_HARDHAT_CONF", "0.15"))
# Per-negative-class floors. A "missing item" must be at least this confident before it
# false-flags a worker. Default to the NO_Hardhat floor so behaviour is unchanged unless
# tuned per site.
NO_VEST_CONF = float(os.getenv("PPE_NO_VEST_CONF", str(NO_HARDHAT_CONF)))
NO_GOGGLES_CONF = float(os.getenv("PPE_NO_GOGGLES_CONF", str(NO_HARDHAT_CONF)))
NO_BOOTS_CONF = float(os.getenv("PPE_NO_BOOTS_CONF", str(NO_HARDHAT_CONF)))
# Presence smoothing: fraction of the window an item must be seen to count as worn. Lower
# than 0.5 so an intermittently-detected worn item is still credited (favours not falsely
# flagging a compliant worker).
PPE_PRESENCE_MIN_FRAC = float(os.getenv("PPE_PRESENCE_MIN_FRAC", "0.3"))
NEGATIVE_MARGIN = float(os.getenv("PPE_NEGATIVE_MARGIN", "1.20"))
IOU = float(os.getenv("PPE_IOU", "0.50"))

MISSING_GRACE = float(os.getenv("PPE_MISSING_GRACE", "2.0"))   # s absent before violation
MIN_PRESENT = float(os.getenv("PPE_MIN_PRESENT", "3.0"))       # stable s before "removed"
COOLDOWN = float(os.getenv("PPE_COOLDOWN", "30.0"))            # per-track/ppe event gap (s)

# v2 logic uses ONE uniform PPE confidence floor (AI-Powered's 0.35) for all items
# instead of the per-item split (helmet 0.10 / vest 0.50). The very low helmet floor
# let stray weak helmet boxes flicker a worker compliant<->missing; 0.35 is what gave the
# stable AI-Powered results.
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
# ByteTrack tuning. high_thresh = confidence to START a track; it MUST be <= PERSON_CONF
# or low-confidence (night/far) people never establish a track and produce no events — so
# it is left UNSET here and the processor derives it from PERSON_CONF. iou/buffer kept
# permissive so a worker isn't re-numbered through brief occlusion. (The AI-Powered yaml's
# 0.45/0.80 were tuned for a bright webcam and silently dropped dim workers.)
PPE_TRACK_HIGH_THRESH = os.getenv("PPE_TRACK_HIGH_THRESH")  # None → derived from PERSON_CONF
if PPE_TRACK_HIGH_THRESH is not None:
    PPE_TRACK_HIGH_THRESH = float(PPE_TRACK_HIGH_THRESH)
PPE_TRACK_LOW_THRESH = float(os.getenv("PPE_TRACK_LOW_THRESH", "0.05"))
PPE_TRACK_MATCH_THRESH = float(os.getenv("PPE_TRACK_MATCH_THRESH", "0.30"))
PPE_TRACK_BUFFER = int(os.getenv("PPE_TRACK_BUFFER", "150"))
PPE_REID_MODEL_NAME = os.getenv("PPE_REID_MODEL_NAME", "person_reid_trt")
PPE_REID_THRESHOLD = float(os.getenv("PPE_REID_THRESHOLD", "0.60"))
PPE_REID_HISTORY = int(os.getenv("PPE_REID_HISTORY", "50"))
PPE_REID_MAX_UNKNOWN = int(os.getenv("PPE_REID_MAX_UNKNOWN", "5"))
# Missing must persist this long (s) before a violation fires under v2 — AI-Powered used
# ~5 frames of persistence; at a few processed FPS that's ~1s. Keeps a one-frame helmet
# drop from raising a false alert.
V2_MISSING_GRACE = float(os.getenv("PPE_V2_MISSING_GRACE", "1.0"))
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
