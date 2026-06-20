"""ANPR (Automatic Number Plate Recognition) scenario plugin configuration.

Env-bound settings + the proven POC thresholds. Inference runs on the shared
Triton server (three models — anpr_plate detector, ppocr_v6 recognition, yolo26
vehicle classifier); this plugin is a thin Triton client that owns the YOLO
pre/post-processing, the PP-OCRv6 CTC decode, the per-track plate voting, and the
Milesight-parity logic (vehicle-type / direction / speed / whitelist-blacklist).

Defaults are the POC's proven values (final_poc/anpr.py argparse defaults). Do NOT
loosen them without footage validation — they were tuned to stop false plates
while still catching real ones (det conf 0.6, OCR conf gate, regex match, min
reads 3 for the per-vehicle vote).
"""
from __future__ import annotations

import os
from pathlib import Path

PORT = int(os.getenv("PORT", "8094"))
SCENARIO_SLUG = os.getenv("SCENARIO_SLUG", "anpr")
VERSION = "1.0.0"

# ── NVR wiring ───────────────────────────────────────────────────────────────
VIZOR_BASE_URL = os.getenv("VIZOR_BASE_URL", "http://backend:8000/api").rstrip("/")
VIZOR_API_KEY = os.getenv("VIZOR_API_KEY", "")
VIZOR_SERVICE_TOKEN = os.getenv("VIZOR_SERVICE_TOKEN", "")

# ── Own Postgres (separate from the NVR DB, mirrors FRS/PPE) ─────────────────
ANPR_DATABASE_URL = os.getenv(
    "ANPR_DATABASE_URL", "postgresql+psycopg2://anpr:anpr@anpr-db:5432/anpr"
)
DATA_PATH = Path(os.getenv("DATA_PATH", "/data/anpr"))

# ── Inference (shared Triton) ────────────────────────────────────────────────
# 'triton' → shared Triton server (production, batched). The plugin decodes the
# raw model outputs itself; no in-process torch/openvino/onnxruntime.
INFERENCE_BACKEND = os.getenv("INFERENCE_BACKEND", "triton")
TRITON_URL = os.getenv("TRITON_URL", "triton:8000")

# Plate detector — anpr_plate: input "images" [1,3,640,640] fp32, output
# "output0" [1,300,6] (x1,y1,x2,y2,score,class); single plate class, NMS baked in.
PLATE_MODEL_NAME = os.getenv("ANPR_PLATE_MODEL_NAME", "anpr_plate")
PLATE_MODEL_INPUT = os.getenv("ANPR_PLATE_MODEL_INPUT", "images")
PLATE_MODEL_OUTPUT = os.getenv("ANPR_PLATE_MODEL_OUTPUT", "output0")
PLATE_MODEL_IMGSZ = int(os.getenv("ANPR_PLATE_MODEL_IMGSZ", "640"))

# OCR — ppocr_v6 (PP-OCRv6 recognition): input "x" [N,3,48,W] fp32 (dynamic batch
# + dynamic width), output "fetch_name_0" [N,T,18710] CTC logits. dict_v6.txt ships
# in the image for the client-side CTC greedy decode.
OCR_MODEL_NAME = os.getenv("ANPR_OCR_MODEL_NAME", "ppocr_v6")
OCR_MODEL_INPUT = os.getenv("ANPR_OCR_MODEL_INPUT", "x")
OCR_MODEL_OUTPUT = os.getenv("ANPR_OCR_MODEL_OUTPUT", "fetch_name_0")
OCR_REC_H = int(os.getenv("ANPR_OCR_REC_H", "48"))
# Cap the per-crop recognition width so a freak wide crop can't blow up the tensor.
OCR_MAX_W = int(os.getenv("ANPR_OCR_MAX_W", "640"))
# dict_v6.txt — index 0 is the CTC blank; copied into the image at build time.
OCR_DICT_PATH = os.getenv(
    "ANPR_OCR_DICT_PATH",
    str(Path(__file__).resolve().parent.parent / "models" / "dict_v6.txt"),
)

# Vehicle classifier — REUSE the existing yolo26 Triton model (COCO-ish classes).
# Output [1,300,6] like the plate model. Empty name disables vehicle-type tagging.
VEHICLE_MODEL_NAME = os.getenv("ANPR_VEHICLE_MODEL_NAME", "yolo26")
VEHICLE_MODEL_INPUT = os.getenv("ANPR_VEHICLE_MODEL_INPUT", "images")
VEHICLE_MODEL_OUTPUT = os.getenv("ANPR_VEHICLE_MODEL_OUTPUT", "output0")
VEHICLE_MODEL_IMGSZ = int(os.getenv("ANPR_VEHICLE_MODEL_IMGSZ", "640"))
VEHICLE_CONF = float(os.getenv("ANPR_VEHICLE_CONF", "0.35"))

# ── Detection / OCR / gating thresholds (POC anpr.py defaults) ───────────────
DET_CONF = float(os.getenv("ANPR_DET_CONF", "0.6"))        # YOLO plate confidence
OCR_CONF = float(os.getenv("ANPR_OCR_CONF", "0.65"))       # OCR mean-char conf gate (0..1)
MIN_PLATE_W = int(os.getenv("ANPR_MIN_PLATE_W", "90"))     # min plate width px to OCR (far plates skipped)
MIN_READS = int(os.getenv("ANPR_MIN_READS", "3"))          # ignore vehicle blips with fewer reads
EXIT_FRAMES = int(os.getenv("ANPR_EXIT_FRAMES", "15"))     # plate gone N frames => track left => emit
TRACK_MAX_AGE = int(os.getenv("ANPR_TRACK_MAX_AGE", "30")) # ByteTrack max_age (frames)

# Allow raw (regex-failing) reads to be emitted too. Off by default — the POC drops
# non-matching reads. Flip on for regions whose format isn't covered by the regex.
ALLOW_RAW_READS = os.getenv("ANPR_ALLOW_RAW_READS", "false").lower() in (
    "1", "true", "yes", "on",
)

# CLAHE low-light enhancement before detect/OCR (POC enhance_lowlight). On by
# default (proven to help night plates); a camera can override via config.
LOWLIGHT_ENHANCE = os.getenv("ANPR_LOWLIGHT_ENHANCE", "true").lower() in (
    "1", "true", "yes", "on",
)
LOWLIGHT_THRESH = float(os.getenv("ANPR_LOWLIGHT_THRESH", "70"))  # mean-gray below => low light

# ── Plate format / region (configurable; default Indian incl. BH-series) ─────
# Standard:  LL N(N) L(LL) NNNN   |   BH-series:  NN BH NNNN L(L)
# Ported verbatim from final_poc/anpr.py PLATE_REGEX.
PLATE_REGION = os.getenv("ANPR_PLATE_REGION", "IN")
PLATE_REGEX_DEFAULT = (
    r"[0-9]{2}BH[0-9]{4}[A-Z]{1,2}|[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{3,4}"
)
PLATE_REGEX = os.getenv("ANPR_PLATE_REGEX", PLATE_REGEX_DEFAULT)

# ── Speed estimation (per-camera calibration; ESTIMATE only) ─────────────────
# Single-camera speed is an ESTIMATE and requires calibration. If a camera has no
# calibration configured, speed is omitted (never faked). Calibration = two lines
# a known real-world distance apart (line crossing -> displacement/time), OR one
# line + a real-world metres-per-pixel scale. See pipeline/speed.py.
SPEED_ENABLED_DEFAULT = os.getenv("ANPR_SPEED_ENABLED", "false").lower() in (
    "1", "true", "yes", "on",
)

# ── Data retention (storage-limitation) ──────────────────────────────────────
RETENTION_EVENT_DAYS = int(os.getenv("ANPR_RETENTION_EVENT_DAYS", "90"))
RETENTION_SWEEP_HOURS = float(os.getenv("ANPR_RETENTION_SWEEP_HOURS", "6"))
RETENTION_BATCH = int(os.getenv("ANPR_RETENTION_BATCH", "2000"))
DISK_WARN_PERCENT = float(os.getenv("ANPR_DISK_WARN_PERCENT", "90"))

# ── Live per-camera workers (go2rtc RTSP restream) ───────────────────────────
LIVE_ENABLED = os.getenv("ANPR_LIVE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
GO2RTC_RTSP_HOST = os.getenv("GO2RTC_RTSP_HOST", "go2rtc")
GO2RTC_RTSP_PORT = int(os.getenv("GO2RTC_RTSP_PORT", "8554"))
LIVE_POLL_SECONDS = int(os.getenv("ANPR_LIVE_POLL_SECONDS", "15"))
LIVE_DEFAULT_FPS = float(os.getenv("ANPR_LIVE_FPS", "8"))
# Pull the MAIN stream by default — sub-streams are too low-res for small plates.
LIVE_USE_SUBSTREAM = os.getenv("ANPR_LIVE_SUBSTREAM", "false").lower() in ("1", "true", "yes", "on")
LIVE_HWACCEL = os.getenv("ANPR_HWACCEL", "none").lower()   # cuda | none
LIVE_STALL_TIMEOUT = int(os.getenv("ANPR_LIVE_STALL_TIMEOUT", "20"))
LIVE_MAX_WIDTH = int(os.getenv("ANPR_LIVE_MAX_WIDTH", "1920"))

DATA_PATH.mkdir(parents=True, exist_ok=True)
# scenario.json lives at the package root (one level up from config/).
MANIFEST_PATH = Path(__file__).resolve().parent.parent / "scenario.json"
