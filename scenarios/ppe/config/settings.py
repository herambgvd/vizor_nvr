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
PPE_MODEL_IMGSZ = int(os.getenv("PPE_MODEL_IMGSZ", "640"))

# Optional DINOv2 head/torso verifier — Triton model name. Empty = YOLO-only
# baseline (the POC supports this by omitting --vit-verifier). Wiring is present
# so the verifier can be hosted later without touching the pipeline.
PPE_VIT_MODEL_NAME = os.getenv("PPE_VIT_MODEL_NAME", "")
PPE_VIT_CONFIRM = float(os.getenv("PPE_VIT_CONFIRM", "0.58"))      # reject below
PPE_VIT_RESCUE = float(os.getenv("PPE_VIT_RESCUE", "0.82"))        # add helmet above
PPE_VIT_VEST_RESCUE = float(os.getenv("PPE_VIT_VEST_RESCUE", "0.92"))  # add vest above
PPE_VIT_INTERVAL = int(os.getenv("PPE_VIT_INTERVAL", "5"))         # run once / N frames

# ── Detection / compliance thresholds (POC run_video.py defaults) ────────────
PERSON_CONF = float(os.getenv("PPE_PERSON_CONF", "0.20"))
HARDHAT_CONF = float(os.getenv("PPE_HARDHAT_CONF", "0.10"))
VEST_CONF = float(os.getenv("PPE_VEST_CONF", "0.50"))
NO_HARDHAT_CONF = float(os.getenv("PPE_NO_HARDHAT_CONF", "0.15"))
NEGATIVE_MARGIN = float(os.getenv("PPE_NEGATIVE_MARGIN", "1.20"))
IOU = float(os.getenv("PPE_IOU", "0.50"))

MISSING_GRACE = float(os.getenv("PPE_MISSING_GRACE", "1.0"))   # s absent before violation
MIN_PRESENT = float(os.getenv("PPE_MIN_PRESENT", "3.0"))       # stable s before "removed"
COOLDOWN = float(os.getenv("PPE_COOLDOWN", "30.0"))            # per-track/ppe event gap (s)
ALERT_INITIAL_MISSING = os.getenv("PPE_ALERT_INITIAL_MISSING", "true").lower() in (
    "1", "true", "yes", "on",
)

# Temporal smoothing window (frames) — flicker rejection.
SMOOTH_WINDOW = int(os.getenv("PPE_SMOOTH_WINDOW", "8"))
SMOOTH_MIN_HITS = int(os.getenv("PPE_SMOOTH_MIN_HITS", "3"))
STABLE_ID_MAX_AGE = float(os.getenv("PPE_STABLE_ID_MAX_AGE", "3.0"))  # relink seconds

# Eligibility gates (suppress edge / artifact tracks).
MIN_PERSON_HEIGHT = int(os.getenv("PPE_MIN_PERSON_HEIGHT", "80"))
MIN_FOOT_Y = float(os.getenv("PPE_MIN_FOOT_Y", "0.20"))
BORDER_MARGIN = int(os.getenv("PPE_BORDER_MARGIN", "6"))

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
