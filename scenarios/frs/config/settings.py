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

INFERENCE_BACKEND = os.getenv("INFERENCE_BACKEND", "onnxruntime-gpu")
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
# Live quality gates — reject garbage faces, but tuned looser than vizor-gpu's
# studio defaults because NVR cameras are often wide/top-down with smaller,
# angled faces. Override per-deploy via env if the scene is close/frontal.
LIVE_MIN_FACE_PX = int(os.getenv("FRS_LIVE_MIN_FACE_PX", "18"))
LIVE_MAX_POSE_DEG = float(os.getenv("FRS_LIVE_MAX_POSE_DEG", "65"))
LIVE_MIN_SHARPNESS = float(os.getenv("FRS_LIVE_MIN_SHARPNESS", "20"))
LIVE_DET_CONF = float(os.getenv("FRS_LIVE_DET_CONF", "0.45"))

# ArcFace embeddings are 512-d. (The histogram fallback also emits 512-d so the
# Qdrant collection vector size is stable whether or not models are mounted.)
VECTOR_SIZE = 512
MAX_PHOTO_BYTES = 15 * 1024 * 1024
ALLOWED_CONTENT = {"image/jpeg", "image/jpg", "image/png", "image/webp"}

# ── Live recognition (per-camera RTSP workers) ───────────────────────────────
LIVE_ENABLED = os.getenv("FRS_LIVE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
# go2rtc restreams every camera at rtsp://<host>:<port>/<stream_id>. The plugin
# pulls the low-res sub-stream for analysis.
GO2RTC_RTSP_HOST = os.getenv("GO2RTC_RTSP_HOST", "go2rtc")
GO2RTC_RTSP_PORT = int(os.getenv("GO2RTC_RTSP_PORT", "8554"))
LIVE_POLL_SECONDS = int(os.getenv("FRS_LIVE_POLL_SECONDS", "15"))   # camera catalogue refresh
LIVE_DEFAULT_FPS = float(os.getenv("FRS_LIVE_FPS", "3"))            # analysed frames/sec
LIVE_ALERT_COOLDOWN = int(os.getenv("FRS_LIVE_ALERT_COOLDOWN", "300"))  # per-person event gap (s)
LIVE_USE_SUBSTREAM = os.getenv("FRS_LIVE_SUBSTREAM", "true").lower() in ("1", "true", "yes", "on")

VERSION = "0.2.0"

DATA_PATH.mkdir(parents=True, exist_ok=True)
# scenario.json lives at the package root (one level up from config/).
MANIFEST_PATH = Path(__file__).resolve().parent.parent / "scenario.json"
