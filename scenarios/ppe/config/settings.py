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

# ── Inference (shared Triton) ────────────────────────────────────────────────
# 'triton' → shared Triton server (production, batched). The plugin decodes the
# raw [1,300,6] ppe_yolo26 output itself; no in-process torch/ultralytics.
INFERENCE_BACKEND = os.getenv("INFERENCE_BACKEND", "triton")
TRITON_URL = os.getenv("TRITON_URL", "triton:8000")
PPE_MODEL_NAME = os.getenv("PPE_MODEL_NAME", "ppe_yolo26")
PPE_MODEL_INPUT = os.getenv("PPE_MODEL_INPUT", "images")
PPE_MODEL_OUTPUT = os.getenv("PPE_MODEL_OUTPUT", "output0")
# 1280 matches the POC's full-frame inference size (the model is exported at
# 1280); 640 lost too much detail on wide/top-down scenes -> weak persons + false
# PPE. Must equal the Triton ppe_yolo26 input dims.
PPE_MODEL_IMGSZ = int(os.getenv("PPE_MODEL_IMGSZ", "1280"))
# Second-stage per-person crop PPE re-detection (the proven worker's
# detect_ppe_in_crops). Steadies helmet/vest evidence so a person doesn't
# oscillate compliant<->missing. One extra Triton call per person per frame —
# fine at the analyze-fps cap. Disable to fall back to full-frame-only.
PPE_CROP_STAGE = os.getenv("PPE_CROP_STAGE", "true").lower() in ("1", "true", "yes", "on")

# Optional DINOv2 head/torso verifier — Triton model name. Empty = YOLO-only
# baseline (the POC supports this by omitting --vit-verifier). Wiring is present
# so the verifier can be hosted later without touching the pipeline.
PPE_VIT_MODEL_NAME = os.getenv("PPE_VIT_MODEL_NAME", "")
# Camera-trained linear heads (helmet/vest) over the DINOv2 CLS embedding. Bundled
# in the image at models/; the DINOv2 backbone itself is served on Triton.
PPE_VIT_ARTIFACT = os.getenv(
    "PPE_VIT_ARTIFACT",
    str(Path(__file__).resolve().parent.parent / "models" / "vit_ppe_dinov2_small.npz"),
)
PPE_VIT_CONFIRM = float(os.getenv("PPE_VIT_CONFIRM", "0.58"))      # reject helmet below
PPE_VIT_RESCUE = float(os.getenv("PPE_VIT_RESCUE", "0.82"))        # add helmet above
PPE_VIT_VEST_RESCUE = float(os.getenv("PPE_VIT_VEST_RESCUE", "0.92"))  # add vest above
# Veto a YOLO vest the DINOv2 torso head doesn't agree with — kills the common
# "red/bright shirt read as a hi-vis vest" false positive. 0 = no vest veto.
PPE_VIT_VEST_CONFIRM = float(os.getenv("PPE_VIT_VEST_CONFIRM", "0.50"))
# The hosted DINOv2 vest head is untrained (returns ~0.96 for every torso), so
# vest fusion (both rescue and veto) is OFF — vests come from YOLO only. Flip on
# only with a properly trained vest head.
PPE_VIT_FUSE_VEST = os.getenv("PPE_VIT_FUSE_VEST", "false").lower() in ("1", "true", "yes", "on")
PPE_VIT_INTERVAL = int(os.getenv("PPE_VIT_INTERVAL", "5"))         # run once / N frames

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
NEGATIVE_MARGIN = float(os.getenv("PPE_NEGATIVE_MARGIN", "1.20"))
IOU = float(os.getenv("PPE_IOU", "0.50"))

MISSING_GRACE = float(os.getenv("PPE_MISSING_GRACE", "2.0"))   # s absent before violation
MIN_PRESENT = float(os.getenv("PPE_MIN_PRESENT", "3.0"))       # stable s before "removed"
COOLDOWN = float(os.getenv("PPE_COOLDOWN", "30.0"))            # per-track/ppe event gap (s)
ALERT_INITIAL_MISSING = os.getenv("PPE_ALERT_INITIAL_MISSING", "true").lower() in (
    "1", "true", "yes", "on",
)

# Temporal smoothing window (frames) — flicker rejection. A wider window + higher
# min-hits steadies a noisy detector so a person doesn't flip missing<->compliant
# frame to frame.
SMOOTH_WINDOW = int(os.getenv("PPE_SMOOTH_WINDOW", "15"))
SMOOTH_MIN_HITS = int(os.getenv("PPE_SMOOTH_MIN_HITS", "6"))
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
MIN_PERSON_FRAC = float(os.getenv("PPE_MIN_PERSON_FRAC", "0.22"))

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
