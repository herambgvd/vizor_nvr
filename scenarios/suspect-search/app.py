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
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True

try:
    import onnxruntime as ort
except Exception:  # noqa: BLE001
    ort = None

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels
except Exception:  # noqa: BLE001
    QdrantClient = None
    qmodels = None


PORT = int(os.getenv("PORT", "8091"))
SCENARIO_SLUG = os.getenv("SCENARIO_SLUG", "suspect-search")
VIZOR_BASE_URL = os.getenv("VIZOR_BASE_URL", "http://backend:8000/api").rstrip("/")
VIZOR_API_KEY = os.getenv("VIZOR_API_KEY", "")
VIZOR_SERVICE_TOKEN = os.getenv("VIZOR_SERVICE_TOKEN", "")
FRAME_INTERVAL_SECONDS = int(os.getenv("FRAME_INTERVAL_SECONDS", "45"))
MAX_SCAN_FRAMES = int(os.getenv("MAX_SCAN_FRAMES", "240"))
THUMB_DIR = Path(os.getenv("THUMB_DIR", "/tmp/vizor-suspect-search-thumbs"))
QDRANT_URL = os.getenv("QDRANT_URL", "").rstrip("/")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "vizor_suspect_search")
INFERENCE_BACKEND = os.getenv("INFERENCE_BACKEND", "onnxruntime-gpu")
DETECTOR_MODEL_PATH = Path(os.getenv("DETECTOR_MODEL_PATH", "/models/yolo26.onnx"))
REID_MODEL_PATH = Path(os.getenv("REID_MODEL_PATH", "/models/person-reid.onnx"))
VECTOR_SIZE = 64
THUMB_DIR.mkdir(parents=True, exist_ok=True)

MANIFEST_PATH = Path(__file__).with_name("scenario.json")
JOBS: dict[str, dict[str, Any]] = {}
RESULT_THUMBS: dict[str, Path] = {}
RESULT_PAYLOADS: dict[str, dict[str, Any]] = {}
QDRANT: Any | None = None

app = FastAPI(title="Vizor Suspect Search", version="0.2.0")


def _load_manifest() -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["slug"] = SCENARIO_SLUG
    return manifest


def _onnx_status() -> dict[str, Any]:
    providers = ort.get_available_providers() if ort else []
    detector_present = DETECTOR_MODEL_PATH.exists()
    reid_present = REID_MODEL_PATH.exists()
    detector_loadable = False
    reid_loadable = False
    load_errors: dict[str, str] = {}
    session_providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    if ort and detector_present:
        try:
            ort.InferenceSession(str(DETECTOR_MODEL_PATH), providers=session_providers)
            detector_loadable = True
        except Exception as exc:  # noqa: BLE001
            load_errors["detector"] = str(exc)
    if ort and reid_present:
        try:
            ort.InferenceSession(str(REID_MODEL_PATH), providers=session_providers)
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
        "note": "Production inference requires both YOLO26 ONNX detector and ReID ONNX model. Fallback color/vector search is available while model files are absent.",
    }


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
        return QDRANT
    except Exception as exc:  # noqa: BLE001
        print(f"[suspect-search] qdrant unavailable: {exc}", flush=True)
        QDRANT = None
        return None


def _require_service_token(x_vizor_service_token: str | None = Header(None)) -> None:
    if VIZOR_SERVICE_TOKEN and x_vizor_service_token != VIZOR_SERVICE_TOKEN:
        raise HTTPException(401, "invalid service token")


def register_on_boot() -> None:
    if not VIZOR_API_KEY:
        print("[suspect-search] VIZOR_API_KEY missing; manifest registration skipped", flush=True)
        return
    headers = {"Content-Type": "application/json", "X-Vizor-API-Key": VIZOR_API_KEY}
    url = f"{VIZOR_BASE_URL}/ai/scenarios/register"
    for attempt in range(1, 16):
        try:
            resp = requests.post(url, json=_load_manifest(), headers=headers, timeout=10)
            resp.raise_for_status()
            print(f"[suspect-search] registered manifest ({resp.status_code})", flush=True)
            return
        except Exception as exc:  # noqa: BLE001
            print(f"[suspect-search] registration attempt {attempt} failed: {exc}", flush=True)
            time.sleep(min(2 * attempt, 20))


@app.on_event("startup")
def _startup() -> None:
    _qdrant_client()
    threading.Thread(target=register_on_boot, daemon=True).start()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "scenario": SCENARIO_SLUG, "version": "0.2.0"}


@app.post("/health/deep")
def deep_health(_: None = Depends(_require_service_token)) -> dict:
    ffmpeg = subprocess.run(
        ["ffmpeg", "-version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    qdrant = _qdrant_client()
    onnx = _onnx_status()
    engine_ready = bool(qdrant) and bool(onnx["runtime_available"] and onnx["ready"])
    return {
        "status": "ok" if ffmpeg.returncode == 0 and engine_ready else "degraded",
        "engine": "qdrant-vector-index + onnx-ready fallback-color-engine",
        "ffmpeg": ffmpeg.returncode == 0,
        "index": "qdrant" if qdrant else "on-demand",
        "qdrant": bool(qdrant),
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


def _embedding_from_image(data: bytes) -> list[float]:
    hist = _image_histogram(data)
    image = Image.open(io.BytesIO(data)).convert("RGB").resize((64, 64))
    cells: list[float] = []
    for y in range(0, 64, 16):
        for x in range(0, 64, 16):
            crop = image.crop((x, y, x + 16, y + 16))
            pixels = list(crop.getdata())
            cells.append(sum(r for r, _g, _b in pixels) / (len(pixels) * 255.0))
    vector = (hist + cells)[:VECTOR_SIZE]
    if len(vector) < VECTOR_SIZE:
        vector.extend([0.0] * (VECTOR_SIZE - len(vector)))
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def _attribute_score(payload: dict[str, Any], filters: dict[str, Any]) -> float:
    checks = 0
    hits = 0
    for key in ("upper_color", "lower_color", "dominant_color", "position_region", "size_bucket"):
        expected = str(filters.get(key) or "").strip().lower()
        if not expected or expected == "any":
            continue
        checks += 1
        if str(payload.get(key) or "").lower() == expected:
            hits += 1
    return 1.0 if checks == 0 else hits / checks


def _filters(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "object_type": str(payload.get("object_type") or "person").lower(),
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
            return _embedding_from_image(thumb.read_bytes())
        if source:
            return None
    if reference_bytes:
        return _embedding_from_image(reference_bytes)
    return None


def _set_job(job_id: str, **patch: Any) -> None:
    job = JOBS.get(job_id)
    if job:
        job.update(patch)


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
    has_attribute_filters = any(filters.get(key) for key in ("upper_color", "lower_color", "dominant_color", "position_region", "size_bucket"))
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
        if JOBS.get(job_id, {}).get("status") == "cancelled":
            return
        duration = int(rec.get("duration") or 0)
        offsets = list(range(0, max(1, duration), max(1, FRAME_INTERVAL_SECONDS))) or [0]
        for offset in offsets:
            if scanned_frames >= MAX_SCAN_FRAMES:
                break
            result_id = str(uuid.uuid4())
            frame_path = THUMB_DIR / f"{result_id}.jpg"
            if not _extract_frame(rec.get("file_path") or "", offset, frame_path):
                continue
            scanned_frames += 1
            try:
                frame_bytes = frame_path.read_bytes()
                frame_vector = _embedding_from_image(frame_bytes)
                score = _cosine(query_vector, frame_vector) if query_vector else _cosine(ref_hist or [], _image_histogram(frame_bytes))
            except Exception:
                continue
            attrs = _attributes_from_image(frame_bytes, filters["object_type"])
            attr_score = _attribute_score(attrs, filters)
            score = (score * 0.78) + (attr_score * 0.22)
            if score >= min_conf:
                start = _parse_dt(rec.get("start_time")) or datetime.utcnow()
                ts = start + timedelta(seconds=offset)
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
                    "bbox": [0, 0, 1, 1],
                    "size_bucket": filters.get("size_bucket") or "medium",
                    "position_region": filters.get("position_region") or "center",
                    **attrs,
                }
                RESULT_THUMBS[result_id] = frame_path
                RESULT_PAYLOADS[result_id] = item
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
        if JOBS.get(job_id, {}).get("status") == "cancelled":
            return
        duration = int(rec.get("duration") or 0)
        offsets = list(range(0, max(1, duration), max(1, FRAME_INTERVAL_SECONDS))) or [0]
        for offset in offsets:
            if scanned_frames >= MAX_SCAN_FRAMES:
                break
            frame_id = str(uuid.uuid4())
            frame_path = THUMB_DIR / f"{frame_id}.jpg"
            if not _extract_frame(rec.get("file_path") or "", offset, frame_path):
                continue
            scanned_frames += 1
            frame_bytes = frame_path.read_bytes()
            vector = _embedding_from_image(frame_bytes)
            start = _parse_dt(rec.get("start_time")) or datetime.utcnow()
            ts = start + timedelta(seconds=offset)
            for object_type in object_types:
                result_id = str(uuid.uuid4())
                candidate_path = THUMB_DIR / f"{result_id}.jpg"
                try:
                    candidate_path.write_bytes(frame_bytes)
                except Exception:
                    candidate_path = frame_path
                attrs = _attributes_from_image(frame_bytes, object_type)
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
                    "bbox": [0, 0, 1, 1],
                    "size_bucket": "medium",
                    "position_region": "center",
                    **attrs,
                }
                RESULT_THUMBS[result_id] = candidate_path
                RESULT_PAYLOADS[result_id] = item
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


@app.post("/jobs/index")
async def create_index_job(request: Request, _: None = Depends(_require_service_token)) -> JSONResponse:
    payload, _reference = await _request_payload(request)
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {
        "job_id": job_id,
        "type": "index",
        "status": "queued",
        "progress": 0.0,
        "message": "Archive vector indexing queued.",
        "result_count": 0,
        "results": [],
        "engine": "qdrant_color_vector_index_v1",
    }
    threading.Thread(target=_run_index, args=(job_id, payload), daemon=True).start()
    return JSONResponse(JOBS[job_id], status_code=202)


@app.post("/jobs/search")
async def create_search_job(request: Request, _: None = Depends(_require_service_token)) -> JSONResponse:
    payload, reference_bytes = await _request_payload(request)
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {
        "job_id": job_id,
        "type": "search",
        "status": "queued",
        "progress": 0.0,
        "result_count": 0,
        "results": [],
        "engine": "appearance_histogram_v1",
    }
    threading.Thread(target=_run_search, args=(job_id, reference_bytes, payload), daemon=True).start()
    return JSONResponse(JOBS[job_id], status_code=202)


@app.get("/jobs/{job_id}")
def get_job(job_id: str, _: None = Depends(_require_service_token)) -> dict:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return {k: v for k, v in job.items() if k != "results"}


@app.get("/jobs/{job_id}/results")
def get_results(job_id: str, limit: int = 50, offset: int = 0, _: None = Depends(_require_service_token)) -> dict:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    results = list(job.get("results") or [])
    return {"items": results[offset : offset + limit], "total": len(results), "limit": limit, "offset": offset}


@app.delete("/jobs/{job_id}")
def cancel_job(job_id: str, _: None = Depends(_require_service_token)) -> dict:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    job["status"] = "cancelled"
    return {k: v for k, v in job.items() if k != "results"}


@app.post("/results/{result_id}/search-similar")
async def search_similar(result_id: str, request: Request, _: None = Depends(_require_service_token)) -> JSONResponse:
    payload, _reference = await _request_payload(request)
    payload["reference_result_id"] = result_id
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {
        "job_id": job_id,
        "type": "nested_search",
        "status": "queued",
        "progress": 0.0,
        "result_count": 0,
        "results": [],
        "engine": "qdrant_nested_vector_v1",
        "reference_result_id": result_id,
    }
    threading.Thread(target=_run_search, args=(job_id, None, payload), daemon=True).start()
    return JSONResponse(JOBS[job_id], status_code=202)


@app.get("/results/{result_id}/thumbnail")
def result_thumbnail(result_id: str, _: None = Depends(_require_service_token)):
    path = RESULT_THUMBS.get(result_id)
    if not path or not path.exists():
        raise HTTPException(404, "thumbnail not found")
    return FileResponse(path, media_type="image/jpeg")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
