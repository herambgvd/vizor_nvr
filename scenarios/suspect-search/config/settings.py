from __future__ import annotations

import os
from pathlib import Path

PORT = int(os.getenv("PORT", "8091"))
SCENARIO_SLUG = os.getenv("SCENARIO_SLUG", "suspect-search")
VIZOR_BASE_URL = os.getenv("VIZOR_BASE_URL", "http://backend:8000/api").rstrip("/")
VIZOR_API_KEY = os.getenv("VIZOR_API_KEY", "")
VIZOR_SERVICE_TOKEN = os.getenv("VIZOR_SERVICE_TOKEN", "")

FRAME_INTERVAL_SECONDS = int(os.getenv("FRAME_INTERVAL_SECONDS", "45"))
MAX_SCAN_FRAMES = int(os.getenv("MAX_SCAN_FRAMES", "240"))

DATA_DIR = Path(os.getenv("DATA_DIR", "/data/suspect-search"))
THUMB_DIR = Path(os.getenv("THUMB_DIR", str(DATA_DIR / "thumbs")))
DATABASE_URL = os.getenv(
    "SUSPECT_SEARCH_DATABASE_URL",
    "postgresql://suspect:suspect@suspect-search-db:5432/suspect_search",
)

QDRANT_URL = os.getenv("QDRANT_URL", "").rstrip("/")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "vizor_suspect_search")
VECTOR_SIZE = int(os.getenv("VECTOR_SIZE", "768"))

# 'triton' → shared Triton server (production); else in-process onnxruntime (dev).
INFERENCE_BACKEND = os.getenv("INFERENCE_BACKEND", "onnxruntime-gpu")
TRITON_URL = os.getenv("TRITON_URL", "triton:8000")
DETECTOR_MODEL_PATH = Path(os.getenv("DETECTOR_MODEL_PATH", "/models/yolo26.onnx"))
REID_MODEL_PATH = Path(os.getenv("REID_MODEL_PATH", "/models/person-reid.onnx"))
DETECTOR_INPUT_SIZE = int(os.getenv("DETECTOR_INPUT_SIZE", "640"))
DETECTOR_CONFIDENCE = float(os.getenv("DETECTOR_CONFIDENCE", "0.35"))
DETECTOR_IOU = float(os.getenv("DETECTOR_IOU", "0.45"))
DETECTOR_CLASS_MAP = os.getenv("DETECTOR_CLASS_MAP", "0:person,24:bag,26:bag,28:bag")
DETECTOR_BOX_FORMAT = os.getenv("DETECTOR_BOX_FORMAT", "auto").lower()

SCENARIO_DIR = Path(__file__).resolve().parents[1]
MANIFEST_PATH = SCENARIO_DIR / "scenario.json"
