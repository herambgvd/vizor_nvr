"""FRS scenario plugin configuration — all env-bound settings + thresholds."""
from __future__ import annotations

import os
from pathlib import Path

PORT = int(os.getenv("PORT", "8093"))
SCENARIO_SLUG = os.getenv("SCENARIO_SLUG", "frs")
VIZOR_BASE_URL = os.getenv("VIZOR_BASE_URL", "http://backend:8000/api").rstrip("/")
VIZOR_API_KEY = os.getenv("VIZOR_API_KEY", "")
VIZOR_SERVICE_TOKEN = os.getenv("VIZOR_SERVICE_TOKEN", "")

# Own Postgres (separate from the NVR DB). Sync engine — this plugin is single
# process and the operations are short; keeps the app dependency-light.
FRS_DATABASE_URL = os.getenv("FRS_DATABASE_URL", "postgresql+psycopg2://frs:frs@frs-db:5432/frs")
DATA_PATH = Path(os.getenv("DATA_PATH", "/data/frs"))

QDRANT_URL = os.getenv("QDRANT_URL", "").rstrip("/")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "vizor_frs_faces")

# Inference backend: 'triton' → shared Triton server (production, batched,
# scales to 64+ channels); otherwise in-process onnxruntime (dev / small node).
INFERENCE_BACKEND = os.getenv("INFERENCE_BACKEND", "onnxruntime-gpu")
TRITON_URL = os.getenv("TRITON_URL", "triton:8000")
# ONNX models — the exact files Triton served in vizor-gpu: SCRFD detector,
# ArcFace embedder, optional MiniFASNet antispoofing. Mounted via the models volume.
DETECTOR_MODEL_PATH = Path(os.getenv("DETECTOR_MODEL_PATH", "/models/scrfd_10g.onnx"))
EMBED_MODEL_PATH = Path(os.getenv("EMBED_MODEL_PATH", "/models/arcface_r50.onnx"))
ANTISPOOF_MODEL_PATH = Path(os.getenv("ANTISPOOF_MODEL_PATH", "/models/antispoofing.onnx"))
FAIRFACE_MODEL_PATH = Path(os.getenv("FAIRFACE_MODEL_PATH", "/models/fairface.onnx"))
LIVENESS_THRESHOLD = float(os.getenv("FRS_LIVENESS_THRESHOLD", "0.5"))

FRAME_INTERVAL_SECONDS = int(os.getenv("FRAME_INTERVAL_SECONDS", "30"))
MAX_SCAN_FRAMES = int(os.getenv("MAX_SCAN_FRAMES", "240"))

# Recognition / enrollment thresholds — ported from vizor-gpu FRS config.
DET_CONF_THRESHOLD = float(os.getenv("FRS_DET_CONF", "0.5"))
SIMILARITY_THRESHOLD = float(os.getenv("FRS_SIMILARITY", "0.6"))   # cosine match
DUPLICATE_COSINE = float(os.getenv("FRS_DUP_COSINE", "0.92"))
ENROLL_MIN_FACE_PX = int(os.getenv("FRS_MIN_FACE_PX", "80"))
ENROLL_MAX_POSE_DEG = float(os.getenv("FRS_MAX_POSE_DEG", "45"))
ENROLL_MIN_SHARPNESS = float(os.getenv("FRS_MIN_SHARPNESS", "50"))
# Live quality gates — vizor-gpu / vizor-app defaults (proven-accurate). These
# are the platform defaults; per-camera config in the UI can loosen them for
# wide/top-down scenes. Do NOT lower the defaults — looser gates admit tiny /
# angled / blurry faces that pollute voting and recognition.
LIVE_MIN_FACE_PX = int(os.getenv("FRS_LIVE_MIN_FACE_PX", "80"))
LIVE_MAX_POSE_DEG = float(os.getenv("FRS_LIVE_MAX_POSE_DEG", "40"))
LIVE_MIN_SHARPNESS = float(os.getenv("FRS_LIVE_MIN_SHARPNESS", "60"))
LIVE_DET_CONF = float(os.getenv("FRS_LIVE_DET_CONF", "0.5"))
# Higher bar to EMIT an "Unknown" event than to detect a face, so SCRFD false
# positives (back-of-head / hand / blur) are tracked but not surfaced as noise.
LIVE_UNKNOWN_MIN_DET_CONF = float(os.getenv("FRS_LIVE_UNKNOWN_MIN_DET_CONF", "0.65"))
# Multi-frame consensus before emitting an event (vizor-gpu default = 5). Firing
# on a single frame produces flickery, low-confidence matches.
LIVE_VOTE_MIN_FRAMES = int(os.getenv("FRS_LIVE_VOTE_MIN_FRAMES", "5"))
LIVE_HIGH_CONF_SCORE = float(os.getenv("FRS_LIVE_HIGH_CONF_SCORE", "0.75"))
# Skip recognition on a frame where the face moved > this fraction of its bbox
# side (likely motion-blurred); the track stays alive so sharp frames vote.
LIVE_MOTION_BLUR_MAX_DISP_RATIO = float(os.getenv("FRS_LIVE_MOTION_BLUR_MAX_DISP_RATIO", "0.35"))

# ArcFace embeddings are 512-d. (The histogram fallback also emits 512-d so the
# Qdrant collection vector size is stable whether or not models are mounted.)
VECTOR_SIZE = 512
MAX_PHOTO_BYTES = 15 * 1024 * 1024
ALLOWED_CONTENT = {"image/jpeg", "image/jpg", "image/png", "image/webp"}

# ── Data retention (GDPR storage-limitation) ─────────────────────────────────
# Events + their snapshot files + snapshot vectors older than this are purged by
# a background sweeper. 0 disables purging (keep forever). Enrolled gallery
# photos/persons are NEVER auto-purged — only sightings/events.
RETENTION_EVENT_DAYS = int(os.getenv("FRS_RETENTION_EVENT_DAYS", "90"))
RETENTION_SWEEP_HOURS = float(os.getenv("FRS_RETENTION_SWEEP_HOURS", "6"))
RETENTION_BATCH = int(os.getenv("FRS_RETENTION_BATCH", "2000"))
# Surface disk pressure in /health when usage on DATA_PATH exceeds this %.
DISK_WARN_PERCENT = float(os.getenv("FRS_DISK_WARN_PERCENT", "90"))

# ── Live recognition (per-camera RTSP workers) ───────────────────────────────
LIVE_ENABLED = os.getenv("FRS_LIVE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
# go2rtc restreams every camera at rtsp://<host>:<port>/<stream_id>. The plugin
# pulls the low-res sub-stream for analysis.
GO2RTC_RTSP_HOST = os.getenv("GO2RTC_RTSP_HOST", "go2rtc")
GO2RTC_RTSP_PORT = int(os.getenv("GO2RTC_RTSP_PORT", "8554"))
LIVE_POLL_SECONDS = int(os.getenv("FRS_LIVE_POLL_SECONDS", "15"))   # camera catalogue refresh
LIVE_DEFAULT_FPS = float(os.getenv("FRS_LIVE_FPS", "10"))            # analysed frames/sec (vizor-gpu default)
LIVE_ALERT_COOLDOWN = int(os.getenv("FRS_LIVE_ALERT_COOLDOWN", "300"))  # per-person event gap (s)
# Pull the MAIN stream for analysis by default — sub-streams are too low-res for
# reliable face detection/recognition. Flip to true only for constrained setups.
LIVE_USE_SUBSTREAM = os.getenv("FRS_LIVE_SUBSTREAM", "false").lower() in ("1", "true", "yes", "on")
# Hardware-accelerated decode (NVDEC) — essential for many-camera scale. At 64
# cameras, software decode saturates the CPU; NVDEC moves decode + scale onto the
# GPU's dedicated decoder engines, freeing the CPU and the GIL. "cuda" enables
# NVDEC (needs an NVIDIA GPU + ffmpeg built with cuvid). "none" = software decode
# (dev/CPU fallback). Workers auto-fall-back to software if the NVDEC pipe fails.
LIVE_HWACCEL = os.getenv("FRS_HWACCEL", "none").lower()   # cuda | none
# Stall watchdog: kill + reconnect a camera's ffmpeg if no frame arrives within
# this many seconds (wedged camera / dead network that doesn't EOF the pipe).
LIVE_STALL_TIMEOUT = int(os.getenv("FRS_LIVE_STALL_TIMEOUT", "20"))

VERSION = "1.0.0"

DATA_PATH.mkdir(parents=True, exist_ok=True)
# scenario.json lives at the package root (one level up from config/).
MANIFEST_PATH = Path(__file__).resolve().parent.parent / "scenario.json"
