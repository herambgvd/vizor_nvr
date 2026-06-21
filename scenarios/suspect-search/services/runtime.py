from __future__ import annotations

import io
import json
import math
import os
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image, ImageFile
import psycopg2
from psycopg2.extras import RealDictCursor

from config.settings import (
    DATA_DIR,
    DATABASE_URL,
    DETECTOR_BOX_FORMAT,
    DETECTOR_CLASS_MAP,
    DETECTOR_CONFIDENCE,
    DETECTOR_INPUT_SIZE,
    DETECTOR_IOU,
    DETECTOR_MODEL_PATH,
    FRAME_INTERVAL_SECONDS,
    INFERENCE_BACKEND,
    TRITON_URL,
    MANIFEST_PATH,
    MAX_SCAN_FRAMES,
    PORT,
    QDRANT_COLLECTION,
    QDRANT_URL,
    REID_MODEL_PATH,
    SCENARIO_SLUG,
    THUMB_DIR,
    VECTOR_SIZE,
    VIZOR_API_KEY,
    VIZOR_BASE_URL,
    VIZOR_SERVICE_TOKEN,
)
from deps.auth import require_service_token as _require_service_token

try:
    import numpy as np
except Exception:  # noqa: BLE001
    np = None

ImageFile.LOAD_TRUNCATED_IMAGES = True

try:
    import onnxruntime as ort
except Exception:  # noqa: BLE001
    ort = None

# Shared-Triton inference (production). Falls back to in-process onnxruntime when
# INFERENCE_BACKEND != 'triton' or the package is unavailable.
_USE_TRITON = (INFERENCE_BACKEND or "").lower() == "triton"
try:
    import inference as triton_infer
except Exception as _exc:  # noqa: BLE001
    triton_infer = None
    if _USE_TRITON:
        print(f"[suspect-search] triton inference import failed: {_exc}", flush=True)

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels
except Exception:  # noqa: BLE001
    QdrantClient = None
    qmodels = None


DATA_DIR.mkdir(parents=True, exist_ok=True)
THUMB_DIR.mkdir(parents=True, exist_ok=True)

JOBS: dict[str, dict[str, Any]] = {}
RESULT_THUMBS: dict[str, Path] = {}
RESULT_PAYLOADS: dict[str, dict[str, Any]] = {}
QDRANT: Any | None = None
DETECTOR_SESSION: Any | None = None
REID_SESSION: Any | None = None
DB_LOCK = threading.Lock()



def _load_manifest() -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["slug"] = SCENARIO_SLUG
    return manifest


def _db_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def _init_store() -> None:
    with DB_LOCK, _db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    job_type TEXT,
                    status TEXT,
                    created_at TIMESTAMPTZ,
                    updated_at TIMESTAMPTZ,
                    payload_json JSONB NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS results (
                    result_id TEXT PRIMARY KEY,
                    job_id TEXT REFERENCES jobs(job_id) ON DELETE SET NULL,
                    camera_id TEXT,
                    object_type TEXT,
                    timestamp TIMESTAMPTZ,
                    thumb_path TEXT,
                    payload_json JSONB NOT NULL
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_results_job ON results(job_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_results_camera_time ON results(camera_id, timestamp)")
        conn.commit()


def _db_ready() -> bool:
    try:
        with DB_LOCK, _db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[suspect-search] postgres unavailable: {exc}", flush=True)
        return False


def _json_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return {}
    return {}


def _dt_param(value: str | None) -> datetime | None:
    return _parse_dt(value)


def _job_public(job: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in job.items() if k != "results"}


def _safe_init_store() -> None:
    last_error = None
    for attempt in range(1, 16):
        try:
            _init_store()
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            print(f"[suspect-search] postgres init attempt {attempt} failed: {exc}", flush=True)
            time.sleep(min(2 * attempt, 20))
    raise RuntimeError(f"postgres init failed: {last_error}")


def _maybe_migrate_sqlite() -> None:
    path = DATA_DIR / "suspect_search.sqlite3"
    marker = DATA_DIR / ".sqlite_migrated_to_postgres"
    if not path.exists() or marker.exists():
        return
    try:
        import sqlite3
    except Exception:
        return
    try:
        sqlite_conn = sqlite3.connect(path)
        sqlite_conn.row_factory = sqlite3.Row
        with sqlite_conn:
            for row in sqlite_conn.execute("SELECT payload_json FROM jobs"):
                job = _json_payload(row["payload_json"])
                if job.get("job_id"):
                    JOBS[str(job["job_id"])] = job
                    _persist_job(str(job["job_id"]))
            for row in sqlite_conn.execute("SELECT job_id, thumb_path, payload_json FROM results"):
                payload = _json_payload(row["payload_json"])
                if payload.get("result_id"):
                    _persist_result(str(row["job_id"]) if row["job_id"] else None, payload, Path(str(row["thumb_path"])) if row["thumb_path"] else None)
        marker.write_text(datetime.utcnow().isoformat(), encoding="utf-8")
        print("[suspect-search] migrated legacy sqlite store to postgres", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[suspect-search] sqlite migration skipped: {exc}", flush=True)


def _load_store() -> None:
    with DB_LOCK, _db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT payload_json FROM jobs ORDER BY created_at DESC NULLS LAST LIMIT 200")
            job_rows = cur.fetchall()
            cur.execute("SELECT result_id, thumb_path, payload_json FROM results ORDER BY timestamp DESC NULLS LAST LIMIT 10000")
            result_rows = cur.fetchall()
    for row in job_rows:
            job = _json_payload(row["payload_json"])
            if not job:
                continue
            if job.get("status") in {"queued", "running"}:
                job["status"] = "cancelled"
                job["message"] = "Plugin restarted before this job completed."
                job["progress"] = min(float(job.get("progress") or 0.0), 0.99)
            JOBS[str(job.get("job_id"))] = job
    for row in result_rows:
            payload = _json_payload(row["payload_json"])
            if not payload:
                continue
            result_id = str(row["result_id"])
            RESULT_PAYLOADS[result_id] = payload
            if row["thumb_path"]:
                RESULT_THUMBS[result_id] = Path(str(row["thumb_path"]))


def _persist_job(job_id: str) -> None:
    job = JOBS.get(job_id)
    if not job:
        return
    created_at = str(job.get("created_at") or datetime.utcnow().isoformat())
    updated_at = str(job.get("updated_at") or created_at)
    with DB_LOCK, _db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO jobs(job_id, job_type, status, created_at, updated_at, payload_json)
                VALUES(%s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT(job_id) DO UPDATE SET
                    job_type=EXCLUDED.job_type,
                    status=EXCLUDED.status,
                    updated_at=EXCLUDED.updated_at,
                    payload_json=EXCLUDED.payload_json
                """,
                (
                    job_id,
                    str(job.get("type") or ""),
                    str(job.get("status") or ""),
                    _dt_param(created_at),
                    _dt_param(updated_at),
                    json.dumps(job, default=str),
                ),
            )
        conn.commit()


def _persist_result(job_id: str | None, result: dict[str, Any], thumb_path: Path | None = None) -> None:
    result_id = str(result.get("result_id") or result.get("id") or "")
    if not result_id:
        return
    RESULT_PAYLOADS[result_id] = dict(result)
    if thumb_path:
        RESULT_THUMBS[result_id] = thumb_path
    path = RESULT_THUMBS.get(result_id)
    with DB_LOCK, _db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO results(result_id, job_id, camera_id, object_type, timestamp, thumb_path, payload_json)
                VALUES(%s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT(result_id) DO UPDATE SET
                    job_id=EXCLUDED.job_id,
                    camera_id=EXCLUDED.camera_id,
                    object_type=EXCLUDED.object_type,
                    timestamp=EXCLUDED.timestamp,
                    thumb_path=EXCLUDED.thumb_path,
                    payload_json=EXCLUDED.payload_json
                """,
                (
                    result_id,
                    job_id,
                    str(result.get("camera_id") or ""),
                    str(result.get("object_type") or ""),
                    _dt_param(str(result.get("timestamp") or "")),
                    str(path) if path else "",
                    json.dumps(result, default=str),
                ),
            )
        conn.commit()


def _stored_results_for_job(job_id: str, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    with DB_LOCK, _db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total FROM results WHERE job_id = %s", (job_id,))
            total_row = cur.fetchone()
            cur.execute(
                """
                SELECT payload_json FROM results
                WHERE job_id = %s
                ORDER BY timestamp ASC NULLS LAST
                LIMIT %s OFFSET %s
                """,
                (job_id, limit, offset),
            )
            rows = cur.fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        payload = _json_payload(row["payload_json"])
        if payload:
            items.append(payload)
    return items, int(total_row["total"] if total_row else 0)


def _stored_job(job_id: str) -> dict[str, Any] | None:
    with DB_LOCK, _db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT payload_json FROM jobs WHERE job_id = %s", (job_id,))
            row = cur.fetchone()
    return _json_payload(row["payload_json"]) if row else None


def _jobs_from_store(limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    with DB_LOCK, _db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total FROM jobs")
            total_row = cur.fetchone()
            cur.execute(
                """
                SELECT payload_json FROM jobs
                ORDER BY created_at DESC NULLS LAST
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            rows = cur.fetchall()
    jobs = [_job_public(_json_payload(row["payload_json"])) for row in rows]
    return jobs, int(total_row["total"] if total_row else 0)


def _stored_thumbnail(result_id: str) -> tuple[Path | None, dict[str, Any] | None]:
    with DB_LOCK, _db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT thumb_path, payload_json FROM results WHERE result_id = %s", (result_id,))
            row = cur.fetchone()
    if not row:
        return None, None
    payload = _json_payload(row["payload_json"])
    path = Path(str(row["thumb_path"])) if row["thumb_path"] else None
    return path, payload


def _reports_from_store(since: str | None = None) -> dict[str, Any]:
    since_dt = _dt_param(since)
    with DB_LOCK, _db_conn() as conn:
        with conn.cursor() as cur:
            if since_dt:
                cur.execute("SELECT payload_json FROM jobs WHERE created_at >= %s", (since_dt,))
            else:
                cur.execute("SELECT payload_json FROM jobs")
            job_rows = cur.fetchall()
            cur.execute("SELECT COUNT(*) AS total FROM results")
            result_row = cur.fetchone()
    jobs = [_json_payload(row["payload_json"]) for row in job_rows]
    status_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    indexed_candidates = 0
    for job in jobs:
        status = str(job.get("status") or "unknown")
        job_type = str(job.get("type") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        type_counts[job_type] = type_counts.get(job_type, 0) + 1
        indexed_candidates += int(job.get("indexed_candidates") or 0)
    return {
        "jobs_total": len(jobs),
        "status_counts": status_counts,
        "type_counts": type_counts,
        "results_total": int(result_row["total"] if result_row else 0),
        "indexed_candidates": indexed_candidates,
    }


def _providers() -> list[str]:
    if not ort:
        return []
    available = set(ort.get_available_providers())
    if os.getenv("ENABLE_TENSORRT", "").lower() in {"1", "true", "yes"}:
        preferred = ["TensorrtExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"]
    else:
        preferred = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    return [provider for provider in preferred if provider in available] or list(available)


def _class_map() -> dict[int, str]:
    mapping: dict[int, str] = {}
    for part in DETECTOR_CLASS_MAP.split(","):
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        try:
            mapping[int(key.strip())] = value.strip().lower()
        except ValueError:
            continue
    return mapping or {0: "person", 24: "bag", 26: "bag", 28: "bag"}


def _session(path: Path, cache_name: str) -> Any | None:
    global DETECTOR_SESSION, REID_SESSION
    if not ort or not path.exists():
        return None
    cached = DETECTOR_SESSION if cache_name == "detector" else REID_SESSION
    if cached is not None:
        return cached
    sess = ort.InferenceSession(str(path), providers=_providers())
    if cache_name == "detector":
        DETECTOR_SESSION = sess
    else:
        REID_SESSION = sess
    return sess


def _onnx_status() -> dict[str, Any]:
    providers = ort.get_available_providers() if ort else []
    detector_present = DETECTOR_MODEL_PATH.exists()
    reid_present = REID_MODEL_PATH.exists()
    detector_loadable = False
    reid_loadable = False
    load_errors: dict[str, str] = {}
    if ort and detector_present:
        try:
            _session(DETECTOR_MODEL_PATH, "detector")
            detector_loadable = True
        except Exception as exc:  # noqa: BLE001
            load_errors["detector"] = str(exc)
    if ort and reid_present:
        try:
            _session(REID_MODEL_PATH, "reid")
            reid_loadable = True
        except Exception as exc:  # noqa: BLE001
            load_errors["reid"] = str(exc)
    return {
        "backend": INFERENCE_BACKEND,
        "runtime_available": ort is not None,
        "providers": providers,
        "cuda_provider": "CUDAExecutionProvider" in providers,
        "detector_model": str(DETECTOR_MODEL_PATH),
        "detector_model_present": detector_present,
        "detector_model_loadable": detector_loadable,
        "reid_model": str(REID_MODEL_PATH),
        "reid_model_present": reid_present,
        "reid_model_loadable": reid_loadable,
        "load_errors": load_errors,
        "ready": bool(ort and detector_loadable and reid_loadable),
        "detector_class_map": _class_map(),
        "vector_size": VECTOR_SIZE,
        "note": "Production inference requires both YOLO26 ONNX detector and ReID ONNX model. Helmet requires a custom PPE/helmet detector because the default COCO detector has person and bag-like classes only.",
    }


def _ensure_payload_indexes(client) -> None:
    """Payload indexes so Stage-1 attribute + time-range filters run efficiently.
    timestamp is a datetime index (for DatetimeRange); the rest are keyword."""
    if qmodels is None:
        return
    try:
        client.create_payload_index(QDRANT_COLLECTION, "timestamp", qmodels.PayloadSchemaType.DATETIME)
    except Exception:  # noqa: BLE001 - already exists
        pass
    for field in ("object_type", "camera_id", "top_type", "bottom_type", "gender", "age_band"):
        try:
            client.create_payload_index(QDRANT_COLLECTION, field, qmodels.PayloadSchemaType.KEYWORD)
        except Exception:  # noqa: BLE001
            pass


def _qdrant_client() -> Any | None:
    global QDRANT
    if QDRANT is not None:
        return QDRANT
    if not QDRANT_URL or QdrantClient is None or qmodels is None:
        return None
    try:
        QDRANT = QdrantClient(url=QDRANT_URL, timeout=10)
        collections = QDRANT.get_collections().collections
        exists = any(c.name == QDRANT_COLLECTION for c in collections)
        if not exists:
            QDRANT.create_collection(
                collection_name=QDRANT_COLLECTION,
                vectors_config=qmodels.VectorParams(size=VECTOR_SIZE, distance=qmodels.Distance.COSINE),
            )
            _ensure_payload_indexes(QDRANT)
        else:
            info = QDRANT.get_collection(QDRANT_COLLECTION)
            vectors = getattr(getattr(info, "config", None), "params", None)
            vector_config = getattr(vectors, "vectors", None)
            current_size = getattr(vector_config, "size", None)
            if current_size and int(current_size) != VECTOR_SIZE:
                print(
                    f"[suspect-search] recreating qdrant collection {QDRANT_COLLECTION}: "
                    f"vector size {current_size} -> {VECTOR_SIZE}",
                    flush=True,
                )
                QDRANT.recreate_collection(
                    collection_name=QDRANT_COLLECTION,
                    vectors_config=qmodels.VectorParams(size=VECTOR_SIZE, distance=qmodels.Distance.COSINE),
                )
        return QDRANT
    except Exception as exc:  # noqa: BLE001
        print(f"[suspect-search] qdrant unavailable: {exc}", flush=True)
        QDRANT = None
        return None


def register_on_boot() -> None:
    """Register the manifest with the NVR catalog via the shared SDK NvrClient
    (same backoff/retry as before)."""
    from vizor_sdk import NvrClient

    NvrClient(VIZOR_BASE_URL, VIZOR_API_KEY, SCENARIO_SLUG).register_manifest(MANIFEST_PATH)


def _retention_sweep() -> int:
    """Purge indexed results older than RETENTION_DAYS — rows, thumbnails, and
    Qdrant points — so the archive index doesn't grow without bound (GDPR
    storage-limitation). 0 disables."""
    days = int(os.getenv("SUSPECT_RETENTION_DAYS", "90"))
    if days <= 0:
        return 0
    purged = 0
    try:
        with _db_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT result_id, thumb_path FROM results "
                "WHERE timestamp IS NOT NULL AND timestamp < now() - interval '%s days' "
                "LIMIT 5000", (days,))
            rows = cur.fetchall()
            for r in rows:
                tp = r.get("thumb_path")
                if tp:
                    try:
                        os.remove(tp)
                    except OSError:
                        pass
                client = _qdrant_client()
                if client:
                    try:
                        client.delete(collection_name=QDRANT_COLLECTION,
                                      points_selector=[r["result_id"]])
                    except Exception:  # noqa: BLE001
                        pass
            if rows:
                ids = tuple(r["result_id"] for r in rows)
                cur.execute("DELETE FROM results WHERE result_id IN %s", (ids,))
                purged = len(rows)
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        print(f"[suspect-search] retention sweep error: {exc}", flush=True)
    return purged


def _retention_loop() -> None:
    import time as _t
    _t.sleep(120)
    interval = float(os.getenv("SUSPECT_RETENTION_SWEEP_HOURS", "6")) * 3600
    while True:
        try:
            n = _retention_sweep()
            if n:
                print(f"[suspect-search] retention purged {n} old results", flush=True)
        except Exception:  # noqa: BLE001
            pass
        _t.sleep(max(3600, interval))


def _startup() -> None:
    _safe_init_store()
    _maybe_migrate_sqlite()
    _load_store()
    # Public dashboard + ingest settings table (SS has no Alembic runner — the
    # SDK-backed settings store owns its own idempotent CREATE TABLE).
    try:
        from db.public_store import init_settings_table
        init_settings_table()
    except Exception as exc:  # noqa: BLE001
        print(f"[suspect-search] settings table init failed: {exc}", flush=True)
    _qdrant_client()
    threading.Thread(target=register_on_boot, daemon=True).start()
    threading.Thread(target=_retention_loop, daemon=True).start()


def health() -> dict:
    return {"status": "ok", "scenario": SCENARIO_SLUG, "version": "0.2.0"}


def deep_health(_: None = Depends(_require_service_token)) -> dict:
    ffmpeg = subprocess.run(
        ["ffmpeg", "-version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    qdrant = _qdrant_client()
    onnx = _onnx_status()
    db_ready = _db_ready()
    engine_ready = db_ready and bool(qdrant) and bool(onnx["runtime_available"] and onnx["ready"])
    return {
        "status": "ok" if ffmpeg.returncode == 0 and engine_ready else "degraded",
        "engine": "qdrant-vector-index + onnx-ready fallback-color-engine",
        "ffmpeg": ffmpeg.returncode == 0,
        "index": "qdrant" if qdrant else "on-demand",
        "qdrant": bool(qdrant),
        "store": {
            "backend": "postgres",
            "data_dir": str(DATA_DIR),
            "database_url": DATABASE_URL.rsplit("@", 1)[-1] if "@" in DATABASE_URL else DATABASE_URL,
            "db_ready": db_ready,
            "thumbnail_dir": str(THUMB_DIR),
        },
        "onnx": onnx,
        "supported_object_types": ["person", "bag", "helmet"],
    }


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _image_histogram(data: bytes) -> list[float]:
    image = Image.open(io.BytesIO(data)).convert("RGB").resize((96, 96))
    bins = [0.0] * 48
    pixels = list(image.getdata())
    for r, g, b in pixels:
        bins[r // 16] += 1.0
        bins[16 + g // 16] += 1.0
        bins[32 + b // 16] += 1.0
    total = float(len(pixels) * 3) or 1.0
    return [x / total for x in bins]


def _normalize_vector(values: list[float], size: int = VECTOR_SIZE) -> list[float]:
    vector = list(values[:size])
    if len(vector) < size:
        vector.extend([0.0] * (size - len(vector)))
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [float(v / norm) for v in vector]


PALETTE: dict[str, tuple[int, int, int]] = {
    "black": (20, 20, 20),
    "white": (235, 235, 235),
    "gray": (128, 128, 128),
    "red": (190, 35, 45),
    "orange": (220, 115, 20),
    "yellow": (220, 190, 45),
    "green": (45, 145, 65),
    "blue": (45, 90, 190),
    "purple": (125, 65, 170),
    "pink": (210, 90, 145),
    "brown": (120, 75, 40),
}


def _nearest_color(rgb: tuple[int, int, int]) -> str:
    return min(
        PALETTE,
        key=lambda name: sum((rgb[i] - PALETTE[name][i]) ** 2 for i in range(3)),
    )


def _dominant_color(image: Image.Image) -> str:
    small = image.convert("RGB").resize((32, 32))
    pixels = list(small.getdata())
    if not pixels:
        return "unknown"
    avg = tuple(int(sum(pixel[i] for pixel in pixels) / len(pixels)) for i in range(3))
    return _nearest_color(avg)


def _attributes_from_image(data: bytes, object_type: str = "person") -> dict[str, Any]:
    # Production: real attributes via Triton (garment type + dominant RGB per
    # region + gender/age + accessories). RGB is the source of truth; a coarse
    # palette name is kept only for legacy display/exact-match scoring.
    if _USE_TRITON and triton_infer is not None:
        try:
            a = triton_infer.extract_attributes(data, object_type)
        except Exception as exc:  # noqa: BLE001
            print(f"[suspect-search] attribute extraction failed: {exc}", flush=True)
            a = None
        if a is not None:
            top = a.get("top_color") or {}
            bot = a.get("bottom_color") or {}
            dom = a.get("dominant_color") or {}
            return {
                # New structured attributes (Eocortex-style).
                "top_type": a.get("top_type"),
                "bottom_type": a.get("bottom_type"),
                "top_rgb": top.get("rgb"), "top_hex": top.get("hex"),
                "bottom_rgb": bot.get("rgb"), "bottom_hex": bot.get("hex"),
                "dominant_rgb": dom.get("rgb"), "dominant_hex": dom.get("hex"),
                "gender": a.get("gender"), "age_band": a.get("age_band"),
                "accessories": a.get("accessories") or [],
                # Legacy palette-name keys (derived from RGB) for back-compat.
                "upper_color": _nearest_color(tuple(top.get("rgb") or (0, 0, 0))) if top else "",
                "lower_color": _nearest_color(tuple(bot.get("rgb") or (0, 0, 0))) if bot else "",
                "dominant_color": _nearest_color(tuple(dom.get("rgb") or (0, 0, 0))) if dom else "",
            }
    # Fallback (no Triton): legacy palette-name heuristic.
    image = Image.open(io.BytesIO(data)).convert("RGB")
    width, height = image.size
    if object_type == "person":
        upper = image.crop((0, 0, width, max(1, height // 2)))
        lower = image.crop((0, height // 2, width, height))
        return {
            "upper_color": _dominant_color(upper),
            "lower_color": _dominant_color(lower),
            "dominant_color": _dominant_color(image),
        }
    return {
        "upper_color": "",
        "lower_color": "",
        "dominant_color": _dominant_color(image),
    }


def _parse_yolo_rows(output: Any, image_size: tuple[int, int], object_types: set[str]) -> list[dict[str, Any]]:
    if np is None:
        return []
    arr = np.asarray(output)
    arr = np.squeeze(arr)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    if arr.ndim != 2:
        return []
    if arr.shape[0] < arr.shape[1] and arr.shape[0] in (6, 7, 8, 84, 85):
        arr = arr.T

    class_map = _class_map()
    width, height = image_size
    detections: list[dict[str, Any]] = []
    for row in arr:
        if row.shape[0] < 6:
            continue
        x, y, w, h = [float(v) for v in row[:4]]
        if row.shape[0] == 6:
            confidence = float(row[4])
            class_id = int(round(float(row[5])))
        else:
            scores_v8 = row[4:]
            class_v8 = int(np.argmax(scores_v8))
            conf_v8 = float(scores_v8[class_v8])
            conf_v5 = -1.0
            class_v5 = class_v8
            if row.shape[0] > 6:
                scores_v5 = row[5:]
                class_v5 = int(np.argmax(scores_v5))
                conf_v5 = float(row[4]) * float(scores_v5[class_v5])
            if conf_v5 > conf_v8:
                confidence = conf_v5
                class_id = class_v5
            else:
                confidence = conf_v8
                class_id = class_v8
        object_type = class_map.get(class_id)
        if not object_type or object_type not in object_types or confidence < DETECTOR_CONFIDENCE:
            continue

        if row.shape[0] == 6 and DETECTOR_BOX_FORMAT != "xywh":
            # YOLO26 ONNX export returns [x1, y1, x2, y2, score, class].
            x1, y1, x2, y2 = x, y, w, h
            if max(abs(x1), abs(y1), abs(x2), abs(y2)) > 2.0:
                x1 /= width
                x2 /= width
                y1 /= height
                y2 /= height
            x1 = max(0.0, min(1.0, x1))
            y1 = max(0.0, min(1.0, y1))
            x2 = max(0.0, min(1.0, x2))
            y2 = max(0.0, min(1.0, y2))
        else:
            # Older YOLO exports commonly output center-x, center-y, width, height.
            # Handle normalized and pixel outputs with the same conversion.
            if max(abs(x), abs(y), abs(w), abs(h)) > 2.0:
                x /= width
                w /= width
                y /= height
                h /= height
            x1 = max(0.0, min(1.0, x - w / 2))
            y1 = max(0.0, min(1.0, y - h / 2))
            x2 = max(0.0, min(1.0, x + w / 2))
            y2 = max(0.0, min(1.0, y + h / 2))
        if x2 <= x1 or y2 <= y1:
            continue
        detections.append(
            {
                "object_type": object_type,
                "class_id": class_id,
                "confidence": confidence,
                "bbox": [round(x1, 5), round(y1, 5), round(x2, 5), round(y2, 5)],
            }
        )
    return _nms(detections)


def _detect_objects(frame_bytes: bytes, object_types: list[str]) -> list[dict[str, Any]]:
    allowed_set = set(object_types or ["person", "bag", "helmet"])
    # Production: shared Triton detector + the existing YOLO row parser / NMS.
    if _USE_TRITON and triton_infer is not None and np is not None:
        outputs, size = triton_infer.detect(frame_bytes)
        if not outputs:
            return []
        dets: list[dict[str, Any]] = []
        for output in outputs:
            dets.extend(_parse_yolo_rows(output, size, allowed_set))
        return _nms(dets)
    sess = None
    if np is not None:
        try:
            sess = _session(DETECTOR_MODEL_PATH, "detector")
        except Exception as exc:  # noqa: BLE001
            print(f"[suspect-search] detector session unavailable: {exc}", flush=True)
    if sess is None or np is None:
        return []

    image = Image.open(io.BytesIO(frame_bytes)).convert("RGB")
    input_meta = sess.get_inputs()[0]
    shape = input_meta.shape
    size = DETECTOR_INPUT_SIZE
    height = int(shape[2]) if len(shape) >= 4 and isinstance(shape[2], int) else size
    width = int(shape[3]) if len(shape) >= 4 and isinstance(shape[3], int) else size
    resized = image.resize((width, height))
    arr = np.asarray(resized).astype("float32") / 255.0
    arr = np.transpose(arr, (2, 0, 1))[None, ...]
    try:
        outputs = sess.run(None, {input_meta.name: arr})
    except Exception as exc:  # noqa: BLE001
        print(f"[suspect-search] detector inference failed: {exc}", flush=True)
        return []

    allowed = set(object_types or ["person", "bag", "helmet"])
    detections: list[dict[str, Any]] = []
    for output in outputs:
        detections.extend(_parse_yolo_rows(output, (width, height), allowed))
    return _nms(detections)


def _candidates_from_frame(frame_bytes: bytes, object_types: list[str]) -> list[dict[str, Any]]:
    image = Image.open(io.BytesIO(frame_bytes)).convert("RGB")
    detections = _detect_objects(frame_bytes, object_types)
    candidates: list[dict[str, Any]] = []
    if not detections:
        for object_type in object_types:
            crop = frame_bytes
            candidates.append(
                {
                    "object_type": object_type,
                    "confidence": 1.0,
                    "bbox": [0, 0, 1, 1],
                    "crop_bytes": crop,
                    "detection_mode": "fallback_full_frame",
                }
            )
        return candidates
    for det in detections:
        crop = _crop_bytes(image, det["bbox"])
        candidates.append(
            {
                **det,
                "crop_bytes": crop,
                "detection_mode": "onnx_detector",
            }
        )
    return candidates


def _embedding_from_image(data: bytes) -> list[float]:
    hist = _image_histogram(data)
    image = Image.open(io.BytesIO(data)).convert("RGB").resize((64, 64))
    cells: list[float] = []
    for y in range(0, 64, 16):
        for x in range(0, 64, 16):
            crop = image.crop((x, y, x + 16, y + 16))
            pixels = list(crop.getdata())
            cells.append(sum(r for r, _g, _b in pixels) / (len(pixels) * 255.0))
    return _normalize_vector(hist + cells)


def _reid_embedding(data: bytes) -> list[float]:
    # Production: shared Triton. Falls back to in-process / histogram.
    if _USE_TRITON and triton_infer is not None:
        vec = triton_infer.reid_embedding(data)
        if vec is not None:
            return vec
        return _embedding_from_image(data)
    sess = None
    if np is not None:
        try:
            sess = _session(REID_MODEL_PATH, "reid")
        except Exception as exc:  # noqa: BLE001
            print(f"[suspect-search] reid session unavailable: {exc}", flush=True)
    if sess is None or np is None:
        return _embedding_from_image(data)

    input_meta = sess.get_inputs()[0]
    shape = input_meta.shape
    height = int(shape[2]) if len(shape) >= 4 and isinstance(shape[2], int) else 256
    width = int(shape[3]) if len(shape) >= 4 and isinstance(shape[3], int) else 128
    image = Image.open(io.BytesIO(data)).convert("RGB").resize((width, height))
    arr = np.asarray(image).astype("float32") / 255.0
    arr = np.transpose(arr, (2, 0, 1))[None, ...]
    try:
        output = sess.run(None, {input_meta.name: arr})[0]
        return _normalize_vector([float(x) for x in np.asarray(output).reshape(-1)])
    except Exception as exc:  # noqa: BLE001
        print(f"[suspect-search] reid inference failed: {exc}", flush=True)
        return _embedding_from_image(data)


def _bbox_area(bbox: list[float]) -> float:
    x1, y1, x2, y2 = bbox
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def _iou(a: list[float], b: list[float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = _bbox_area([ix1, iy1, ix2, iy2])
    union = _bbox_area(a) + _bbox_area(b) - inter
    return 0.0 if union <= 0 else inter / union


def _nms(detections: list[dict[str, Any]], iou_threshold: float = DETECTOR_IOU) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for det in sorted(detections, key=lambda item: item["confidence"], reverse=True):
        if all(det["object_type"] != old["object_type"] or _iou(det["bbox"], old["bbox"]) < iou_threshold for old in kept):
            kept.append(det)
    return kept


def _bbox_meta(bbox: list[float]) -> tuple[str, str]:
    x1, y1, x2, y2 = bbox
    area = _bbox_area(bbox)
    size = "small" if area < 0.05 else "medium" if area < 0.20 else "large"
    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2
    if cx < 0.33:
        region = "left"
    elif cx > 0.66:
        region = "right"
    elif cy < 0.33:
        region = "top"
    elif cy > 0.66:
        region = "bottom"
    else:
        region = "center"
    return size, region


def _crop_bytes(image: Image.Image, bbox: list[float]) -> bytes:
    width, height = image.size
    x1 = int(max(0, min(width - 1, bbox[0] * width)))
    y1 = int(max(0, min(height - 1, bbox[1] * height)))
    x2 = int(max(x1 + 1, min(width, bbox[2] * width)))
    y2 = int(max(y1 + 1, min(height, bbox[3] * height)))
    crop = image.crop((x1, y1, x2, y2))
    out = io.BytesIO()
    crop.save(out, format="JPEG", quality=88)
    return out.getvalue()


# ── Perceptual color match (RGB → Lab ΔE) ────────────────────────────────────
def _rgb_to_lab(rgb):
    """sRGB [r,g,b] (0-255) → CIE-Lab. Pure-python, no deps."""
    r, g, b = [v / 255.0 for v in rgb[:3]]
    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = lin(r), lin(g), lin(b)
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    y = (r * 0.2126 + g * 0.7152 + b * 0.0722)
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883
    def f(t):
        return t ** (1 / 3) if t > 0.008856 else (7.787 * t + 16 / 116)
    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def _color_match(payload_rgb, query_rgb, tol: float = 25.0) -> float | None:
    """1.0 if two colors are within ΔE `tol` (perceptually close), scaled down
    with distance; None if either color missing. ΔE ~25 ≈ 'same color family'."""
    if not payload_rgb or not query_rgb:
        return None
    try:
        la, lb = _rgb_to_lab(payload_rgb), _rgb_to_lab(query_rgb)
        de = sum((la[i] - lb[i]) ** 2 for i in range(3)) ** 0.5
    except Exception:  # noqa: BLE001
        return None
    if de <= tol:
        return 1.0 - 0.5 * (de / tol)        # 1.0 .. 0.5 within tolerance
    return max(0.0, 0.5 - (de - tol) / 100.0)  # taper off beyond tolerance


def _attribute_score(payload: dict[str, Any], filters: dict[str, Any]) -> float:
    """Weighted attribute match. Colors use perceptual RGB ΔE; type/gender/age
    use exact match. Returns 0..1 (1.0 when no attribute filters set)."""
    checks = 0.0
    score = 0.0
    # Perceptual RGB color filters (top / bottom).
    for q_key, p_key in (("top_rgb", "top_rgb"), ("bottom_rgb", "bottom_rgb")):
        q = filters.get(q_key)
        if not q:
            continue
        m = _color_match(payload.get(p_key), q)
        if m is None:
            continue
        checks += 1; score += m
    # Exact-match categorical filters.
    for key in ("top_type", "bottom_type", "gender", "age_band"):
        expected = str(filters.get(key) or "").strip().lower()
        if not expected or expected == "any":
            continue
        checks += 1
        if str(payload.get(key) or "").lower() == expected:
            score += 1
    # Accessories — every requested accessory must be present.
    req_acc = filters.get("accessories") or []
    if req_acc:
        have = set(str(a).lower() for a in (payload.get("accessories") or []))
        checks += 1
        if all(str(a).lower() in have for a in req_acc):
            score += 1
    # Legacy palette-name colors (back-compat).
    for key in ("upper_color", "lower_color", "dominant_color", "position_region", "size_bucket"):
        expected = str(filters.get(key) or "").strip().lower()
        if not expected or expected == "any":
            continue
        checks += 1
        if str(payload.get(key) or "").lower() == expected:
            score += 1
    return 1.0 if checks == 0 else score / checks


def _parse_rgb(value) -> list[int] | None:
    """Accept [r,g,b], 'r,g,b', or '#rrggbb' → [r,g,b] ints, else None."""
    if value is None or value == "":
        return None
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return [int(value[0]), int(value[1]), int(value[2])]
    s = str(value).strip()
    if s.startswith("#") and len(s) == 7:
        return [int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16)]
    if "," in s:
        parts = [p.strip() for p in s.split(",")]
        if len(parts) >= 3:
            try:
                return [int(parts[0]), int(parts[1]), int(parts[2])]
            except ValueError:
                return None
    return None


def _filters(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "object_type": str(payload.get("object_type") or "person").lower(),
        # New structured attribute filters (Eocortex-style).
        "top_type": str(payload.get("top_type") or "").lower(),
        "bottom_type": str(payload.get("bottom_type") or "").lower(),
        "top_rgb": _parse_rgb(payload.get("top_rgb") or payload.get("top_color")),
        "bottom_rgb": _parse_rgb(payload.get("bottom_rgb") or payload.get("bottom_color")),
        "gender": str(payload.get("gender") or "").lower(),
        "age_band": str(payload.get("age_band") or "").lower(),
        "accessories": [a.strip().lower() for a in str(payload.get("accessories") or "").split(",") if a.strip()],
        # Legacy palette-name filters.
        "upper_color": str(payload.get("upper_color") or "").lower(),
        "lower_color": str(payload.get("lower_color") or "").lower(),
        "dominant_color": str(payload.get("dominant_color") or "").lower(),
        "position_region": str(payload.get("position_region") or "").lower(),
        "size_bucket": str(payload.get("size_bucket") or "").lower(),
    }


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


def _extract_frame(recording_path: str, offset: int, out_path: Path) -> bool:
    if not recording_path or not Path(recording_path).exists():
        return False
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        str(max(0, offset)),
        "-i",
        recording_path,
        "-frames:v",
        "1",
        "-vf",
        "scale=240:-1",
        "-q:v",
        "4",
        "-y",
        str(out_path),
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=25, check=False)
        return proc.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0
    except Exception:
        return False


def _recordings(params: dict[str, Any]) -> list[dict[str, Any]]:
    headers = {"X-Vizor-Service-Token": VIZOR_SERVICE_TOKEN, "X-Vizor-Scenario": SCENARIO_SLUG}
    resp = requests.get(
        f"{VIZOR_BASE_URL}/ai/internal/recordings",
        params=params,
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    return list(resp.json().get("items") or [])


def _apply_allowed_cameras(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = [x.strip() for x in str(payload.get("allowed_camera_ids") or "").split(",") if x.strip()]
    requested = [x.strip() for x in str(payload.get("camera_ids") or "").split(",") if x.strip()]
    if not allowed:
        return payload
    selected = [x for x in requested if x in set(allowed)] if requested else allowed
    payload["camera_ids"] = ",".join(selected)
    payload["allowed_camera_ids"] = ",".join(allowed)
    return payload


def _result_from_payload(payload: dict[str, Any], score: float | None = None) -> dict[str, Any]:
    result = dict(payload)
    if score is not None:
        result["confidence"] = round(float(score), 4)
    result.setdefault("thumbnail_url", f"/results/{result.get('result_id')}/thumbnail")
    return result


def _upsert_candidate(result: dict[str, Any], vector: list[float]) -> None:
    client = _qdrant_client()
    if not client or qmodels is None:
        return
    try:
        client.upsert(
            collection_name=QDRANT_COLLECTION,
            points=[
                qmodels.PointStruct(
                    id=result["result_id"],
                    vector=vector,
                    payload=result,
                )
            ],
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[suspect-search] qdrant upsert failed: {exc}", flush=True)


def _qdrant_filter(filters: dict[str, Any], payload: dict[str, Any]) -> Any | None:
    if qmodels is None:
        return None
    must: list[Any] = []
    object_type = str(payload.get("object_type") or filters.get("object_type") or "person").lower()
    if object_type and object_type != "any":
        must.append(qmodels.FieldCondition(key="object_type", match=qmodels.MatchValue(value=object_type)))
    if payload.get("camera_ids"):
        cameras = [x.strip() for x in str(payload["camera_ids"]).split(",") if x.strip()]
        if cameras:
            must.append(qmodels.FieldCondition(key="camera_id", match=qmodels.MatchAny(any=cameras)))
    # Categorical attribute filters (garment type, gender, age) — pushed into the
    # Qdrant query so Stage-1 attribute search is efficient on the index.
    for key in ("top_type", "bottom_type", "gender", "age_band"):
        val = str(filters.get(key) or "").strip().lower()
        if val and val != "any":
            must.append(qmodels.FieldCondition(key=key, match=qmodels.MatchValue(value=val)))
    # TIME-RANGE FILTER (previously accepted but never applied on the index — the
    # core bug). Timestamps are ISO strings; lexical range works for ISO-8601.
    start = str(payload.get("start_time") or "").strip()
    end = str(payload.get("end_time") or "").strip()
    if start or end:
        rng = qmodels.DatetimeRange(gte=start or None, lte=end or None)
        must.append(qmodels.FieldCondition(key="timestamp", range=rng))
    return qmodels.Filter(must=must) if must else None


def _search_qdrant(query_vector: list[float] | None, payload: dict[str, Any], limit: int = 50) -> list[dict[str, Any]]:
    client = _qdrant_client()
    if not client or query_vector is None:
        return []
    filters = _filters(payload)
    try:
        points = client.query_points(
            collection_name=QDRANT_COLLECTION,
            query=query_vector,
            query_filter=_qdrant_filter(filters, payload),
            limit=max(limit * 3, limit),
            with_payload=True,
        ).points
    except AttributeError:
        points = client.search(
            collection_name=QDRANT_COLLECTION,
            query_vector=query_vector,
            query_filter=_qdrant_filter(filters, payload),
            limit=max(limit * 3, limit),
            with_payload=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[suspect-search] qdrant search failed: {exc}", flush=True)
        return []

    min_conf = float(payload.get("min_confidence") or 0.72)
    results: list[dict[str, Any]] = []
    for point in points:
        item = dict(point.payload or {})
        vector_score = float(getattr(point, "score", 0.0) or 0.0)
        attr_score = _attribute_score(item, filters)
        score = (vector_score * 0.78) + (attr_score * 0.22)
        if score >= min_conf:
            results.append(_result_from_payload(item, score=score))
        if len(results) >= limit:
            break
    return sorted(results, key=lambda x: x.get("timestamp") or "")


def _filter_qdrant(payload: dict[str, Any], limit: int = 50) -> list[dict[str, Any]]:
    client = _qdrant_client()
    if not client:
        return []
    filters = _filters(payload)
    try:
        points, _next_page = client.scroll(
            collection_name=QDRANT_COLLECTION,
            scroll_filter=_qdrant_filter(filters, payload),
            limit=max(limit * 5, limit),
            with_payload=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[suspect-search] qdrant filter failed: {exc}", flush=True)
        return []

    min_conf = float(payload.get("min_confidence") or 0.72)
    results: list[dict[str, Any]] = []
    for point in points:
        item = dict(point.payload or {})
        score = _attribute_score(item, filters)
        if score >= min_conf:
            results.append(_result_from_payload(item, score=score))
        if len(results) >= limit:
            break
    return sorted(results, key=lambda x: x.get("timestamp") or "")


def _query_vector_from_payload(reference_bytes: bytes | None, payload: dict[str, Any]) -> list[float] | None:
    if payload.get("reference_result_id"):
        source = RESULT_PAYLOADS.get(str(payload["reference_result_id"]))
        thumb = RESULT_THUMBS.get(str(payload["reference_result_id"]))
        if thumb and thumb.exists():
            return _reid_embedding(thumb.read_bytes())
        if source:
            return None
    if reference_bytes:
        return _reid_embedding(reference_bytes)
    return None


def _set_job(job_id: str, **patch: Any) -> None:
    job = JOBS.get(job_id)
    if job:
        job.update(patch)
        job["updated_at"] = datetime.utcnow().isoformat()
        _persist_job(job_id)


def _job_cancelled(job_id: str) -> bool:
    return JOBS.get(job_id, {}).get("status") == "cancelled"


def run_search_sync(reference_bytes: bytes | None, payload: dict[str, Any]) -> dict[str, Any]:
    """Synchronous suspect search → returns matching sightings immediately.

    The query is a fast Qdrant lookup over the pre-indexed archive (vector +
    attribute + time + camera filters), so there is no background job to poll —
    the operator presses Search and gets events back. (Archive INDEXING remains a
    separate background job; this only searches what is already indexed.)"""
    result_limit = int(payload.get("result_limit") or 50)
    filters = _filters(payload)
    query_vector = None
    if reference_bytes or payload.get("reference_result_id"):
        try:
            query_vector = _query_vector_from_payload(reference_bytes, payload)
        except Exception as exc:  # noqa: BLE001
            return {"items": [], "total": 0, "error": f"reference_decode_failed:{exc}"}
    indexed = (_search_qdrant(query_vector, payload, limit=result_limit) if query_vector
               else _filter_qdrant(payload, limit=result_limit))
    return {
        "items": indexed,
        "total": len(indexed),
        "engine": "qdrant_vector_v1" if query_vector else "qdrant_attribute_filter_v1",
    }


async def search(request: Request, _: None = Depends(_require_service_token)) -> JSONResponse:
    """POST /search — realtime search; returns events directly (no job/polling)."""
    payload, reference_bytes = await _request_payload(request)
    out = run_search_sync(reference_bytes, payload)
    return JSONResponse(out, status_code=200)


def _run_search(job_id: str, reference_bytes: bytes | None, payload: dict[str, Any]) -> None:
    query_vector = None
    ref_hist = None
    if reference_bytes or payload.get("reference_result_id"):
        try:
            query_vector = _query_vector_from_payload(reference_bytes, payload)
            ref_hist = _image_histogram(reference_bytes) if reference_bytes else None
        except Exception as exc:  # noqa: BLE001
            _set_job(job_id, status="failed", progress=1.0, error=f"reference_decode_failed:{exc}")
            return

    result_limit = int(payload.get("result_limit") or 50)
    filters = _filters(payload)
    has_attribute_filters = any(filters.get(key) for key in (
        "top_type", "bottom_type", "top_rgb", "bottom_rgb", "gender", "age_band", "accessories",
        "upper_color", "lower_color", "dominant_color", "position_region", "size_bucket"))
    indexed = _search_qdrant(query_vector, payload, limit=result_limit) if query_vector else _filter_qdrant(payload, limit=result_limit)
    if indexed:
        _set_job(
            job_id,
            status="completed",
            progress=1.0,
            result_count=len(indexed),
            results=indexed,
            message="Qdrant vector index search completed.",
            engine="qdrant_vector_v1",
        )
        return
    if not query_vector and has_attribute_filters:
        _set_job(
            job_id,
            status="completed",
            progress=1.0,
            result_count=0,
            results=[],
            message="Qdrant attribute search completed; no indexed matches found for the selected filters.",
            engine="qdrant_attribute_filter_v1",
        )
        return

    if not reference_bytes and not payload.get("reference_result_id"):
        _set_job(
            job_id,
            status="completed",
            progress=1.0,
            message="No reference image or indexed nested result was provided. Add a photo/sample, or run an index job first.",
            results=[],
            result_count=0,
        )
        return

    min_conf = float(payload.get("min_confidence") or 0.72)
    params: dict[str, Any] = {"limit": int(payload.get("limit") or 200)}
    if payload.get("camera_ids"):
        params["camera_ids"] = payload["camera_ids"]
    if payload.get("start_time"):
        params["start_after"] = payload["start_time"]
    if payload.get("end_time"):
        params["end_before"] = payload["end_time"]

    try:
        recs = _recordings(params)
    except Exception as exc:  # noqa: BLE001
        _set_job(job_id, status="failed", progress=1.0, error=f"recording_catalog_failed:{exc}")
        return

    results: list[dict[str, Any]] = []
    scanned_frames = 0
    _set_job(job_id, status="running", progress=0.02, recording_count=len(recs), scanned_frames=0)
    for rec_index, rec in enumerate(recs):
        if _job_cancelled(job_id):
            return
        duration = int(rec.get("duration") or 0)
        offsets = list(range(0, max(1, duration), max(1, FRAME_INTERVAL_SECONDS))) or [0]
        for offset in offsets:
            if _job_cancelled(job_id):
                return
            if scanned_frames >= MAX_SCAN_FRAMES:
                break
            result_id = str(uuid.uuid4())
            frame_path = THUMB_DIR / f"{result_id}.jpg"
            if not _extract_frame(rec.get("file_path") or "", offset, frame_path):
                continue
            scanned_frames += 1
            try:
                frame_bytes = frame_path.read_bytes()
            except Exception:
                continue
            candidates = _candidates_from_frame(frame_bytes, [filters["object_type"]])
            for candidate in candidates:
                if _job_cancelled(job_id):
                    return
                result_id = str(uuid.uuid4())
                crop_bytes = candidate["crop_bytes"]
                frame_vector = _reid_embedding(crop_bytes)
                try:
                    visual_score = _cosine(query_vector, frame_vector) if query_vector else _cosine(ref_hist or [], _image_histogram(crop_bytes))
                except Exception:
                    continue
                attrs = _attributes_from_image(crop_bytes, filters["object_type"])
                attr_score = _attribute_score(attrs, filters)
                detection_score = float(candidate.get("confidence") or 1.0)
                score = (visual_score * 0.70) + (attr_score * 0.20) + (detection_score * 0.10)
                if score < min_conf:
                    continue
                start = _parse_dt(rec.get("start_time")) or datetime.utcnow()
                ts = start + timedelta(seconds=offset)
                candidate_path = THUMB_DIR / f"{result_id}.jpg"
                candidate_path.write_bytes(crop_bytes)
                size_bucket, position_region = _bbox_meta(candidate["bbox"])
                item = {
                    "result_id": result_id,
                    "recording_id": rec.get("id"),
                    "camera_id": rec.get("camera_id"),
                    "timestamp": ts.isoformat(),
                    "confidence": round(float(score), 4),
                    "offset_seconds": offset,
                    "thumbnail_url": f"/results/{result_id}/thumbnail",
                    "playback_url": f"/playback?camera={rec.get('camera_id')}&date={ts.date().isoformat()}&t={ts.isoformat()}",
                    "match_type": "appearance_color_vector",
                    "object_type": filters["object_type"],
                    "bbox": candidate["bbox"],
                    "size_bucket": size_bucket,
                    "position_region": position_region,
                    "detection_mode": candidate.get("detection_mode"),
                    "detector_confidence": round(detection_score, 4),
                    **attrs,
                }
                _persist_result(job_id, item, candidate_path)
                _upsert_candidate(item, frame_vector)
                results.append(item)
        progress = (rec_index + 1) / max(1, len(recs))
        _set_job(
            job_id,
            progress=round(progress, 3),
            scanned_recordings=rec_index + 1,
            scanned_frames=scanned_frames,
            result_count=len(results),
            results=sorted(results, key=lambda x: x["timestamp"]),
        )
        if scanned_frames >= MAX_SCAN_FRAMES:
            break
    _set_job(
        job_id,
        status="completed",
        progress=1.0,
        scanned_frames=scanned_frames,
        result_count=len(results),
        results=sorted(results, key=lambda x: x["timestamp"]),
        message="Archive scan completed and matching candidates were seeded into Qdrant.",
        engine="fallback_color_vector_v1",
    )


def _run_index(job_id: str, payload: dict[str, Any]) -> None:
    params: dict[str, Any] = {"limit": int(payload.get("limit") or 500)}
    if payload.get("camera_ids"):
        params["camera_ids"] = payload["camera_ids"]
    if payload.get("start_time"):
        params["start_after"] = payload["start_time"]
    if payload.get("end_time"):
        params["end_before"] = payload["end_time"]
    object_types = [
        item.strip().lower()
        for item in str(payload.get("object_types") or payload.get("object_type") or "person,bag,helmet").split(",")
        if item.strip()
    ]
    try:
        recs = _recordings(params)
    except Exception as exc:  # noqa: BLE001
        _set_job(job_id, status="failed", progress=1.0, error=f"recording_catalog_failed:{exc}")
        return

    indexed = 0
    scanned_frames = 0
    _set_job(job_id, status="running", progress=0.02, recording_count=len(recs), indexed_candidates=0)
    for rec_index, rec in enumerate(recs):
        if _job_cancelled(job_id):
            return
        duration = int(rec.get("duration") or 0)
        offsets = list(range(0, max(1, duration), max(1, FRAME_INTERVAL_SECONDS))) or [0]
        for offset in offsets:
            if _job_cancelled(job_id):
                return
            if scanned_frames >= MAX_SCAN_FRAMES:
                break
            frame_id = str(uuid.uuid4())
            frame_path = THUMB_DIR / f"{frame_id}.jpg"
            if not _extract_frame(rec.get("file_path") or "", offset, frame_path):
                continue
            scanned_frames += 1
            frame_bytes = frame_path.read_bytes()
            start = _parse_dt(rec.get("start_time")) or datetime.utcnow()
            ts = start + timedelta(seconds=offset)
            candidates = _candidates_from_frame(frame_bytes, object_types)
            for candidate in candidates:
                if _job_cancelled(job_id):
                    return
                object_type = candidate["object_type"]
                result_id = str(uuid.uuid4())
                candidate_path = THUMB_DIR / f"{result_id}.jpg"
                crop_bytes = candidate["crop_bytes"]
                candidate_path.write_bytes(crop_bytes)
                vector = _reid_embedding(crop_bytes)
                attrs = _attributes_from_image(crop_bytes, object_type)
                size_bucket, position_region = _bbox_meta(candidate["bbox"])
                item = {
                    "result_id": result_id,
                    "recording_id": rec.get("id"),
                    "camera_id": rec.get("camera_id"),
                    "timestamp": ts.isoformat(),
                    "confidence": 1.0,
                    "offset_seconds": offset,
                    "thumbnail_url": f"/results/{result_id}/thumbnail",
                    "playback_url": f"/playback?camera={rec.get('camera_id')}&date={ts.date().isoformat()}&t={ts.isoformat()}",
                    "match_type": "indexed_candidate",
                    "object_type": object_type,
                    "bbox": candidate["bbox"],
                    "size_bucket": size_bucket,
                    "position_region": position_region,
                    "detection_mode": candidate.get("detection_mode"),
                    "detector_confidence": round(float(candidate.get("confidence") or 1.0), 4),
                    **attrs,
                }
                _persist_result(job_id, item, candidate_path)
                _upsert_candidate(item, vector)
                indexed += 1
        _set_job(
            job_id,
            progress=round((rec_index + 1) / max(1, len(recs)), 3),
            scanned_recordings=rec_index + 1,
            scanned_frames=scanned_frames,
            indexed_candidates=indexed,
        )
        if scanned_frames >= MAX_SCAN_FRAMES:
            break
    _set_job(
        job_id,
        status="completed",
        progress=1.0,
        scanned_frames=scanned_frames,
        indexed_candidates=indexed,
        result_count=0,
        message="Archive index completed. Candidates are available in Qdrant for image, color and nested search.",
    )


async def _request_payload(request: Request) -> tuple[dict[str, Any], bytes | None]:
    allowed_camera_ids = request.headers.get("X-Vizor-Allowed-Camera-Ids") or ""
    ctype = request.headers.get("content-type", "")
    if "multipart/form-data" in ctype or "application/x-www-form-urlencoded" in ctype:
        form = await request.form()
        reference = form.get("reference") or form.get("file")
        ref_bytes = await reference.read() if hasattr(reference, "read") else None
        return _apply_allowed_cameras({
            "object_type": str(form.get("object_type") or "person"),
            "object_types": str(form.get("object_types") or ""),
            "camera_ids": str(form.get("camera_ids") or ""),
            "allowed_camera_ids": allowed_camera_ids,
            "start_time": str(form.get("start_time") or ""),
            "end_time": str(form.get("end_time") or ""),
            "min_confidence": float(form.get("min_confidence") or 0.72),
            # New Eocortex-style attribute filters.
            "top_type": str(form.get("top_type") or ""),
            "bottom_type": str(form.get("bottom_type") or ""),
            "top_rgb": str(form.get("top_rgb") or form.get("top_color") or ""),
            "bottom_rgb": str(form.get("bottom_rgb") or form.get("bottom_color") or ""),
            "gender": str(form.get("gender") or ""),
            "age_band": str(form.get("age_band") or ""),
            "accessories": str(form.get("accessories") or ""),
            # Legacy palette-name filters.
            "upper_color": str(form.get("upper_color") or ""),
            "lower_color": str(form.get("lower_color") or ""),
            "dominant_color": str(form.get("dominant_color") or ""),
            "size_bucket": str(form.get("size_bucket") or ""),
            "position_region": str(form.get("position_region") or ""),
            "reference_result_id": str(form.get("reference_result_id") or ""),
        }), ref_bytes
    try:
        data = await request.json()
    except Exception:
        data = {}
    payload = dict(data or {})
    payload["allowed_camera_ids"] = allowed_camera_ids
    return _apply_allowed_cameras(payload), None


async def create_index_job(request: Request, _: None = Depends(_require_service_token)) -> JSONResponse:
    payload, _reference = await _request_payload(request)
    job_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    JOBS[job_id] = {
        "job_id": job_id,
        "type": "index",
        "status": "queued",
        "progress": 0.0,
        "message": "Archive vector indexing queued.",
        "result_count": 0,
        "results": [],
        "engine": "qdrant_color_vector_index_v1",
        "created_at": now,
        "updated_at": now,
    }
    _persist_job(job_id)
    threading.Thread(target=_run_index, args=(job_id, payload), daemon=True).start()
    return JSONResponse(JOBS[job_id], status_code=202)


async def create_search_job(request: Request, _: None = Depends(_require_service_token)) -> JSONResponse:
    payload, reference_bytes = await _request_payload(request)
    job_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    JOBS[job_id] = {
        "job_id": job_id,
        "type": "search",
        "status": "queued",
        "progress": 0.0,
        "result_count": 0,
        "results": [],
        "engine": "appearance_histogram_v1",
        "created_at": now,
        "updated_at": now,
    }
    _persist_job(job_id)
    threading.Thread(target=_run_search, args=(job_id, reference_bytes, payload), daemon=True).start()
    return JSONResponse(JOBS[job_id], status_code=202)


def list_jobs(limit: int = 50, offset: int = 0, _: None = Depends(_require_service_token)) -> dict:
    jobs, total = _jobs_from_store(limit, offset)
    if not jobs and JOBS:
        jobs = sorted(
            (_job_public(job) for job in JOBS.values()),
            key=lambda item: str(item.get("created_at") or ""),
            reverse=True,
        )[offset : offset + limit]
        total = len(JOBS)
    return {"items": jobs, "total": total, "limit": limit, "offset": offset}


def get_job(job_id: str, _: None = Depends(_require_service_token)) -> dict:
    job = JOBS.get(job_id) or _stored_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return _job_public(job)


def get_results(job_id: str, limit: int = 50, offset: int = 0, _: None = Depends(_require_service_token)) -> dict:
    job = JOBS.get(job_id) or _stored_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    results = list(job.get("results") or [])
    if results:
        return {"items": results[offset : offset + limit], "total": len(results), "limit": limit, "offset": offset}
    stored, total = _stored_results_for_job(job_id, limit, offset)
    return {"items": stored, "total": total, "limit": limit, "offset": offset}


def cancel_job(job_id: str, _: None = Depends(_require_service_token)) -> dict:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    _set_job(job_id, status="cancelled", message="Job cancelled by user.")
    return {k: v for k, v in job.items() if k != "results"}


async def search_similar(result_id: str, request: Request, _: None = Depends(_require_service_token)) -> JSONResponse:
    """Stage-2 refine — find more sightings of the person in `result_id` via ReID.
    Synchronous (Qdrant lookup): returns events directly, no job/polling."""
    payload, _reference = await _request_payload(request)
    payload["reference_result_id"] = result_id
    out = run_search_sync(None, payload)
    return JSONResponse(out, status_code=200)


def reports_summary(since: str | None = None, _: None = Depends(_require_service_token)) -> dict:
    report = _reports_from_store(since)

    collection_points = None
    client = _qdrant_client()
    if client:
        try:
            collection_points = int(client.count(collection_name=QDRANT_COLLECTION, exact=False).count)
        except Exception as exc:  # noqa: BLE001
            print(f"[suspect-search] qdrant count failed: {exc}", flush=True)

    model_status = _onnx_status()
    return {
        "scenario": SCENARIO_SLUG,
        "since": since,
        **report,
        "qdrant_points": collection_points,
        "model_ready": model_status["ready"],
        "detector_model_present": model_status["detector_model_present"],
        "reid_model_present": model_status["reid_model_present"],
        "supported_object_types": ["person", "bag", "helmet"],
    }


def result_thumbnail(result_id: str, _: None = Depends(_require_service_token)):
    path = RESULT_THUMBS.get(result_id)
    if not path:
        path, payload = _stored_thumbnail(result_id)
        if payload:
            RESULT_PAYLOADS[result_id] = payload
        if path:
            RESULT_THUMBS[result_id] = path
    if not path or not path.exists():
        raise HTTPException(404, "thumbnail not found")
    return FileResponse(path, media_type="image/jpeg")
