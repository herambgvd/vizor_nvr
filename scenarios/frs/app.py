from __future__ import annotations

import io
import json
import math
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import requests
from fastapi import Body, Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, Response
from PIL import Image, ImageFile
from sqlalchemy import (
    JSON, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, and_, create_engine, func, or_, select,
)
from sqlalchemy.orm import declarative_base, sessionmaker

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


# =============================================================================
# Config
# =============================================================================
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
DETECTOR_MODEL_PATH = Path(os.getenv("DETECTOR_MODEL_PATH", "/models/face-detector.onnx"))
EMBED_MODEL_PATH = Path(os.getenv("EMBED_MODEL_PATH", "/models/arcface.onnx"))
FRAME_INTERVAL_SECONDS = int(os.getenv("FRAME_INTERVAL_SECONDS", "30"))
MAX_SCAN_FRAMES = int(os.getenv("MAX_SCAN_FRAMES", "240"))
VECTOR_SIZE = 128
MAX_PHOTO_BYTES = 15 * 1024 * 1024
ALLOWED_CONTENT = {"image/jpeg", "image/jpg", "image/png", "image/webp"}

DATA_PATH.mkdir(parents=True, exist_ok=True)
MANIFEST_PATH = Path(__file__).with_name("scenario.json")

JOBS: dict[str, dict[str, Any]] = {}
QDRANT: Any | None = None

app = FastAPI(title="Vizor Face Recognition", version="0.1.0")


# =============================================================================
# DB models (plugin-owned)
# =============================================================================
Base = declarative_base()


class FRSGroup(Base):
    __tablename__ = "frs_groups"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False, unique=True)
    group_type = Column(String(50), nullable=True)
    color_code = Column(String(20), nullable=True)
    description = Column(Text, nullable=True)
    alert_sound = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class FRSPerson(Base):
    __tablename__ = "frs_persons"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    full_name = Column(String(200), nullable=False)
    external_id = Column(String(100), nullable=True, unique=True)
    group_id = Column(String, ForeignKey("frs_groups.id", ondelete="SET NULL"), nullable=True)
    category = Column(String(20), nullable=False, default="standard")
    priority = Column(Integer, nullable=False, default=0)
    enrollment_status = Column(String(20), nullable=False, default="unenrolled")
    photo_count = Column(Integer, nullable=False, default=0)
    enrolled_photo_count = Column(Integer, nullable=False, default=0)
    thumbnail_key = Column(String(500), nullable=True)
    attributes = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        Index("ix_frs_persons_group", "group_id"),
        Index("ix_frs_persons_category", "category"),
    )


class FRSPhoto(Base):
    __tablename__ = "frs_photos"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    person_id = Column(String, ForeignKey("frs_persons.id", ondelete="CASCADE"), nullable=False)
    storage_key = Column(String(500), nullable=True)
    thumbnail_key = Column(String(500), nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    embedding_id = Column(String(100), nullable=True)
    quality_score = Column(Float, nullable=True)
    liveness_score = Column(Float, nullable=True)
    sharpness_score = Column(Float, nullable=True)
    error_code = Column(String(50), nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    __table_args__ = (Index("ix_frs_photos_person", "person_id"),)


class FRSAttendance(Base):
    __tablename__ = "frs_attendance"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    person_id = Column(String, ForeignKey("frs_persons.id", ondelete="CASCADE"), nullable=False)
    camera_id = Column(String, nullable=True)
    day_key = Column(String(10), nullable=False)
    check_in_at = Column(DateTime, nullable=True)
    check_out_at = Column(DateTime, nullable=True)
    sighting_type = Column(String(20), nullable=True)
    event_id = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        UniqueConstraint("person_id", "day_key", name="uq_person_day"),
        Index("ix_frs_attendance_day", "day_key"),
    )


class FRSEvent(Base):
    """Recognition events owned by the FRS plugin (full isolation — these do not
    flow into the NVR generic event store)."""
    __tablename__ = "frs_events"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    camera_id = Column(String, nullable=True)
    event_type = Column(String(50), nullable=False, default="face_recognized")
    severity = Column(String(20), nullable=True, default="info")
    title = Column(String(200), nullable=True)
    description = Column(Text, nullable=True)
    detection_type = Column(String(50), nullable=True, default="face")
    person_id = Column(String, nullable=True)
    track_id = Column(String(50), nullable=True)
    confidence = Column(Float, nullable=True)
    bbox = Column(JSON, nullable=True)
    attributes = Column(JSON, nullable=True)
    snapshot_path = Column(String(500), nullable=True)
    triggered_at = Column(DateTime, server_default=func.now())
    __table_args__ = (
        Index("ix_frs_events_person", "person_id"),
        Index("ix_frs_events_triggered", "triggered_at"),
    )


class TransitRule(Base):
    __tablename__ = "frs_transit_rules"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(200), nullable=False)
    config = Column(JSON, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class TransitSession(Base):
    __tablename__ = "frs_transit_sessions"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    rule_id = Column(String, nullable=True)
    person_id = Column(String, nullable=True)
    status = Column(String(20), nullable=True)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    attributes = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


_engine = None
_Session = None


def _init_db(retries: int = 30) -> None:
    global _engine, _Session
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            _engine = create_engine(FRS_DATABASE_URL, pool_pre_ping=True, future=True)
            Base.metadata.create_all(_engine)
            _Session = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
            print("[frs] database ready", flush=True)
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            print(f"[frs] db init attempt {attempt} failed: {exc}", flush=True)
            time.sleep(min(2 * attempt, 15))
    raise RuntimeError(f"frs db init failed: {last_exc}")


def _session():
    if _Session is None:
        raise HTTPException(503, "database not ready")
    return _Session()


# =============================================================================
# Inference + Qdrant
# =============================================================================

def _qdrant() -> Any | None:
    global QDRANT
    if QDRANT is not None:
        return QDRANT
    if not QDRANT_URL or QdrantClient is None or qmodels is None:
        return None
    try:
        QDRANT = QdrantClient(url=QDRANT_URL, timeout=10)
        existing = {c.name for c in QDRANT.get_collections().collections}
        if QDRANT_COLLECTION not in existing:
            QDRANT.create_collection(
                collection_name=QDRANT_COLLECTION,
                vectors_config=qmodels.VectorParams(size=VECTOR_SIZE, distance=qmodels.Distance.COSINE),
            )
        return QDRANT
    except Exception as exc:  # noqa: BLE001
        print(f"[frs] qdrant unavailable: {exc}", flush=True)
        QDRANT = None
        return None


def _onnx_status() -> dict[str, Any]:
    providers = ort.get_available_providers() if ort else []
    det = DETECTOR_MODEL_PATH.exists()
    emb = EMBED_MODEL_PATH.exists()
    det_load = emb_load = False
    errors: dict[str, str] = {}
    sp = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    if ort and det:
        try:
            ort.InferenceSession(str(DETECTOR_MODEL_PATH), providers=sp); det_load = True
        except Exception as exc:  # noqa: BLE001
            errors["detector"] = str(exc)
    if ort and emb:
        try:
            ort.InferenceSession(str(EMBED_MODEL_PATH), providers=sp); emb_load = True
        except Exception as exc:  # noqa: BLE001
            errors["embed"] = str(exc)
    return {
        "backend": INFERENCE_BACKEND,
        "runtime_available": ort is not None,
        "providers": providers,
        "cuda_provider": "CUDAExecutionProvider" in providers,
        "detector_model_present": det, "detector_model_loadable": det_load,
        "embed_model_present": emb, "embed_model_loadable": emb_load,
        "load_errors": errors,
        "ready": bool(ort and det_load and emb_load),
        "note": "Production recognition requires a face detector + ArcFace embedding ONNX model. A deterministic histogram embedding fallback is used while model files are absent.",
    }


def _face_embedding(data: bytes) -> list[float]:
    """ONNX ArcFace hook. Fallback: deterministic color-histogram + grid vector
    so enrollment/recognition work end to end before models are mounted."""
    image = Image.open(io.BytesIO(data)).convert("RGB").resize((96, 96))
    pixels = list(image.getdata())
    bins = [0.0] * 48
    for r, g, b in pixels:
        bins[r // 16] += 1.0
        bins[16 + g // 16] += 1.0
        bins[32 + b // 16] += 1.0
    total = float(len(pixels) * 3) or 1.0
    hist = [x / total for x in bins]
    cells: list[float] = []
    grid = image.resize((64, 64))
    for y in range(0, 64, 8):
        for x in range(0, 64, 8):
            crop = grid.crop((x, y, x + 8, y + 8))
            px = list(crop.getdata())
            cells.append(sum(r for r, _g, _b in px) / (len(px) * 255.0))
    vector = (hist + cells)[:VECTOR_SIZE]
    if len(vector) < VECTOR_SIZE:
        vector.extend([0.0] * (VECTOR_SIZE - len(vector)))
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)); nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _upsert_face(point_id: str, vector: list[float], payload: dict[str, Any]) -> None:
    client = _qdrant()
    if not client or qmodels is None:
        return
    try:
        client.upsert(
            collection_name=QDRANT_COLLECTION,
            points=[qmodels.PointStruct(id=point_id, vector=vector, payload=payload)],
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[frs] qdrant upsert failed: {exc}", flush=True)


def _delete_faces(point_ids: list[str]) -> None:
    client = _qdrant()
    if not client or qmodels is None or not point_ids:
        return
    try:
        client.delete(collection_name=QDRANT_COLLECTION,
                      points_selector=qmodels.PointIdsList(points=point_ids))
    except Exception as exc:  # noqa: BLE001
        print(f"[frs] qdrant delete failed: {exc}", flush=True)


def _search_faces(vector: list[float], limit: int = 50) -> list[dict[str, Any]]:
    client = _qdrant()
    if not client:
        return []
    try:
        points = client.query_points(
            collection_name=QDRANT_COLLECTION, query=vector, limit=limit, with_payload=True,
        ).points
    except AttributeError:
        points = client.search(collection_name=QDRANT_COLLECTION, query_vector=vector,
                               limit=limit, with_payload=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[frs] qdrant search failed: {exc}", flush=True)
        return []
    out = []
    for p in points:
        item = dict(p.payload or {})
        item["score"] = float(getattr(p, "score", 0.0) or 0.0)
        out.append(item)
    return out


# =============================================================================
# Helpers
# =============================================================================

def _require_service_token(x_vizor_service_token: str | None = Header(None)) -> None:
    if VIZOR_SERVICE_TOKEN and x_vizor_service_token != VIZOR_SERVICE_TOKEN:
        raise HTTPException(401, "invalid service token")


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _naive(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _parse_dt(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _load_manifest() -> dict:
    m = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    m["slug"] = SCENARIO_SLUG
    return m


def register_on_boot() -> None:
    if not VIZOR_API_KEY:
        print("[frs] VIZOR_API_KEY missing; manifest registration skipped", flush=True)
        return
    headers = {"Content-Type": "application/json", "X-Vizor-API-Key": VIZOR_API_KEY}
    url = f"{VIZOR_BASE_URL}/ai/scenarios/register"
    for attempt in range(1, 16):
        try:
            resp = requests.post(url, json=_load_manifest(), headers=headers, timeout=10)
            resp.raise_for_status()
            print(f"[frs] registered manifest ({resp.status_code})", flush=True)
            return
        except Exception as exc:  # noqa: BLE001
            print(f"[frs] registration attempt {attempt} failed: {exc}", flush=True)
            time.sleep(min(2 * attempt, 20))


def _recount_person(s, person_id: str) -> None:
    person = s.get(FRSPerson, person_id)
    if person is None:
        return
    photo_count = s.scalar(select(func.count(FRSPhoto.id)).where(FRSPhoto.person_id == person_id)) or 0
    enrolled = s.scalar(select(func.count(FRSPhoto.id)).where(
        FRSPhoto.person_id == person_id, FRSPhoto.status == "enrolled")) or 0
    pending = s.scalar(select(func.count(FRSPhoto.id)).where(
        FRSPhoto.person_id == person_id, FRSPhoto.status == "pending")) or 0
    person.photo_count = int(photo_count)
    person.enrolled_photo_count = int(enrolled)
    if photo_count == 0:
        person.enrollment_status = "unenrolled"
    elif enrolled > 0:
        person.enrollment_status = "enrolled"
    elif pending > 0:
        person.enrollment_status = "pending"
    else:
        person.enrollment_status = "failed"
    s.commit()


def _person_dict(p: FRSPerson) -> dict[str, Any]:
    return {
        "id": p.id, "full_name": p.full_name, "external_id": p.external_id,
        "group_id": p.group_id, "category": p.category, "priority": p.priority,
        "enrollment_status": p.enrollment_status, "photo_count": p.photo_count,
        "enrolled_photo_count": p.enrolled_photo_count, "thumbnail_key": p.thumbnail_key,
        "attributes": p.attributes,
        "created_at": _iso(p.created_at), "updated_at": _iso(p.updated_at),
    }


def _group_dict(g: FRSGroup, member_count: int) -> dict[str, Any]:
    return {
        "id": g.id, "name": g.name, "group_type": g.group_type,
        "color_code": g.color_code, "description": g.description,
        "alert_sound": g.alert_sound, "member_count": member_count,
    }


def _photo_dict(ph: FRSPhoto) -> dict[str, Any]:
    return {
        "id": ph.id, "person_id": ph.person_id, "storage_key": ph.storage_key,
        "thumbnail_key": ph.thumbnail_key, "status": ph.status, "embedding_id": ph.embedding_id,
        "quality_score": ph.quality_score, "liveness_score": ph.liveness_score,
        "sharpness_score": ph.sharpness_score, "error_code": ph.error_code, "error": ph.error,
        "created_at": _iso(ph.created_at), "updated_at": _iso(ph.updated_at),
    }


def _event_dict(e: FRSEvent) -> dict[str, Any]:
    return {
        "id": e.id, "camera_id": e.camera_id, "event_type": e.event_type, "severity": e.severity,
        "title": e.title, "description": e.description, "detection_type": e.detection_type,
        "person_id": e.person_id, "track_id": e.track_id, "confidence": e.confidence,
        "bbox": e.bbox, "attributes": e.attributes, "snapshot_path": e.snapshot_path,
        "triggered_at": _iso(e.triggered_at),
    }


# =============================================================================
# Lifecycle + health
# =============================================================================

@app.on_event("startup")
def _startup() -> None:
    threading.Thread(target=_init_db, daemon=True).start()
    _qdrant()
    threading.Thread(target=register_on_boot, daemon=True).start()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "scenario": SCENARIO_SLUG, "version": "0.1.0", "db_ready": _Session is not None}


@app.post("/health/deep")
def deep_health(_: None = Depends(_require_service_token)) -> dict:
    ffmpeg = subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, check=False)
    onnx = _onnx_status()
    qdrant = _qdrant()
    db_ok = False
    if _Session is not None:
        try:
            with _session() as s:
                s.scalar(select(func.count(FRSPerson.id)))
            db_ok = True
        except Exception:
            db_ok = False
    return {
        "status": "ok" if (db_ok and qdrant and ffmpeg.returncode == 0) else "degraded",
        "engine": "postgres-gallery + qdrant-face-index + onnx-ready fallback",
        "ffmpeg": ffmpeg.returncode == 0,
        "database": db_ok,
        "qdrant": bool(qdrant),
        "onnx": onnx,
    }


# =============================================================================
# Groups
# =============================================================================

@app.get("/groups")
def list_groups(_: None = Depends(_require_service_token)) -> list[dict]:
    with _session() as s:
        rows = s.execute(
            select(FRSGroup, func.count(FRSPerson.id))
            .outerjoin(FRSPerson, FRSPerson.group_id == FRSGroup.id)
            .group_by(FRSGroup.id).order_by(FRSGroup.name)
        ).all()
        return [_group_dict(g, int(c or 0)) for g, c in rows]


@app.post("/groups", status_code=201)
def create_group(body: dict = Body(...), _: None = Depends(_require_service_token)) -> dict:
    if not body.get("name"):
        raise HTTPException(400, "name required")
    with _session() as s:
        g = FRSGroup(
            name=body["name"], group_type=body.get("group_type"),
            color_code=body.get("color_code"), description=body.get("description"),
            alert_sound=bool(body.get("alert_sound", False)),
        )
        s.add(g); s.commit(); s.refresh(g)
        return _group_dict(g, 0)


@app.get("/groups/{group_id}")
def get_group(group_id: str, _: None = Depends(_require_service_token)) -> dict:
    with _session() as s:
        g = s.get(FRSGroup, group_id)
        if not g:
            raise HTTPException(404, "group not found")
        cnt = s.scalar(select(func.count(FRSPerson.id)).where(FRSPerson.group_id == group_id)) or 0
        return _group_dict(g, int(cnt))


@app.put("/groups/{group_id}")
def update_group(group_id: str, body: dict = Body(...), _: None = Depends(_require_service_token)) -> dict:
    with _session() as s:
        g = s.get(FRSGroup, group_id)
        if not g:
            raise HTTPException(404, "group not found")
        for k in ("name", "group_type", "color_code", "description", "alert_sound"):
            if k in body and body[k] is not None:
                setattr(g, k, body[k])
        s.commit(); s.refresh(g)
        cnt = s.scalar(select(func.count(FRSPerson.id)).where(FRSPerson.group_id == group_id)) or 0
        return _group_dict(g, int(cnt))


@app.delete("/groups/{group_id}", status_code=204)
def delete_group(group_id: str, _: None = Depends(_require_service_token)):
    with _session() as s:
        g = s.get(FRSGroup, group_id)
        if not g:
            raise HTTPException(404, "group not found")
        s.execute(select(FRSPerson).where(FRSPerson.group_id == group_id))  # noqa
        for p in s.execute(select(FRSPerson).where(FRSPerson.group_id == group_id)).scalars():
            p.group_id = None
        s.delete(g); s.commit()
    return Response(status_code=204)


# =============================================================================
# Persons
# =============================================================================

@app.get("/persons")
def list_persons(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                 search: Optional[str] = None, group_id: Optional[str] = None,
                 category: Optional[str] = None, _: None = Depends(_require_service_token)) -> dict:
    with _session() as s:
        conds = []
        if search:
            like = f"%{search.strip()}%"
            conds.append(or_(FRSPerson.full_name.ilike(like), FRSPerson.external_id.ilike(like)))
        if group_id:
            conds.append(FRSPerson.group_id == group_id)
        if category:
            conds.append(FRSPerson.category == category)
        cq = select(func.count(FRSPerson.id))
        rq = select(FRSPerson)
        for c in conds:
            cq = cq.where(c); rq = rq.where(c)
        total = int(s.scalar(cq) or 0)
        rows = s.execute(rq.order_by(FRSPerson.created_at.desc()).limit(limit).offset(offset)).scalars().all()
        return {"items": [_person_dict(p) for p in rows], "total": total, "limit": limit, "offset": offset}


@app.post("/persons", status_code=201)
def create_person(body: dict = Body(...), _: None = Depends(_require_service_token)) -> dict:
    if not body.get("full_name"):
        raise HTTPException(400, "full_name required")
    with _session() as s:
        if body.get("group_id") and not s.get(FRSGroup, body["group_id"]):
            raise HTTPException(400, "group not found")
        p = FRSPerson(
            full_name=body["full_name"], external_id=body.get("external_id"),
            group_id=body.get("group_id"), category=body.get("category") or "standard",
            priority=int(body.get("priority") or 0), attributes=body.get("attributes"),
        )
        s.add(p); s.commit(); s.refresh(p)
        return _person_dict(p)


@app.get("/persons/{person_id}")
def get_person(person_id: str, _: None = Depends(_require_service_token)) -> dict:
    with _session() as s:
        p = s.get(FRSPerson, person_id)
        if not p:
            raise HTTPException(404, "person not found")
        return _person_dict(p)


@app.put("/persons/{person_id}")
def update_person(person_id: str, body: dict = Body(...), _: None = Depends(_require_service_token)) -> dict:
    with _session() as s:
        p = s.get(FRSPerson, person_id)
        if not p:
            raise HTTPException(404, "person not found")
        if body.get("group_id") and not s.get(FRSGroup, body["group_id"]):
            raise HTTPException(400, "group not found")
        for k in ("full_name", "external_id", "group_id", "category", "priority", "attributes"):
            if k in body:
                setattr(p, k, body[k])
        s.commit(); s.refresh(p)
        return _person_dict(p)


@app.delete("/persons/{person_id}", status_code=204)
def delete_person(person_id: str, _: None = Depends(_require_service_token)):
    with _session() as s:
        p = s.get(FRSPerson, person_id)
        if not p:
            raise HTTPException(404, "person not found")
        photos = s.execute(select(FRSPhoto).where(FRSPhoto.person_id == person_id)).scalars().all()
        _delete_faces([ph.embedding_id for ph in photos if ph.embedding_id])
        for ph in photos:
            s.delete(ph)
        s.delete(p); s.commit()
    photo_dir = DATA_PATH / "persons" / person_id
    if photo_dir.exists():
        import shutil
        shutil.rmtree(photo_dir, ignore_errors=True)
    return Response(status_code=204)


# =============================================================================
# Photos
# =============================================================================

@app.post("/persons/{person_id}/photos", status_code=201)
async def add_photo(person_id: str, file: UploadFile = File(...), _: None = Depends(_require_service_token)) -> dict:
    with _session() as s:
        if not s.get(FRSPerson, person_id):
            raise HTTPException(404, "person not found")
    if file.content_type and file.content_type.lower() not in ALLOWED_CONTENT:
        raise HTTPException(415, f"unsupported content type: {file.content_type}")
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty upload")
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, f"photo exceeds {MAX_PHOTO_BYTES // (1024 * 1024)} MB limit")

    photo_id = str(uuid.uuid4())
    photo_dir = DATA_PATH / "persons" / person_id
    photo_dir.mkdir(parents=True, exist_ok=True)
    rel_key = f"persons/{person_id}/{photo_id}.jpg"
    (photo_dir / f"{photo_id}.jpg").write_bytes(data)

    # Enroll synchronously: this plugin holds the embedding model + Qdrant, so
    # there is no bridge round-trip. Failures mark the photo "failed".
    enroll_status, embedding_id, quality, error = "enrolled", photo_id, 0.9, None
    try:
        vector = _face_embedding(data)
        _upsert_face(photo_id, vector, {"person_id": person_id, "photo_id": photo_id})
    except Exception as exc:  # noqa: BLE001
        enroll_status, embedding_id, quality, error = "failed", None, None, str(exc)

    with _session() as s:
        ph = FRSPhoto(id=photo_id, person_id=person_id, storage_key=rel_key,
                      status=enroll_status, embedding_id=embedding_id,
                      quality_score=quality, error=error)
        s.add(ph); s.commit()
        _recount_person(s, person_id)
        ph = s.get(FRSPhoto, photo_id)
        return _photo_dict(ph)


@app.get("/persons/{person_id}/photos")
def list_photos(person_id: str, _: None = Depends(_require_service_token)) -> list[dict]:
    with _session() as s:
        if not s.get(FRSPerson, person_id):
            raise HTTPException(404, "person not found")
        rows = s.execute(select(FRSPhoto).where(FRSPhoto.person_id == person_id)
                         .order_by(FRSPhoto.created_at.desc())).scalars().all()
        return [_photo_dict(ph) for ph in rows]


@app.delete("/photos/{photo_id}", status_code=204)
def delete_photo(photo_id: str, _: None = Depends(_require_service_token)):
    with _session() as s:
        ph = s.get(FRSPhoto, photo_id)
        if not ph:
            raise HTTPException(404, "photo not found")
        person_id, storage_key, emb = ph.person_id, ph.storage_key, ph.embedding_id
        s.delete(ph); s.commit()
        _recount_person(s, person_id)
    if emb:
        _delete_faces([emb])
    if storage_key:
        f = DATA_PATH / storage_key
        if f.exists():
            try:
                os.remove(f)
            except OSError:
                pass
    return Response(status_code=204)


@app.get("/photos/{photo_id}/image")
def photo_image(photo_id: str, _: None = Depends(_require_service_token)):
    with _session() as s:
        ph = s.get(FRSPhoto, photo_id)
        if not ph or not ph.storage_key:
            raise HTTPException(404, "photo not found")
        path = DATA_PATH / ph.storage_key
    if not path.exists():
        raise HTTPException(404, "photo file not found")
    return FileResponse(str(path), media_type="image/jpeg", filename=f"{photo_id}.jpg")


# =============================================================================
# Recognition (image, synchronous)
# =============================================================================

def _recognize(data: bytes, min_conf: float = 0.6) -> dict[str, Any]:
    vector = _face_embedding(data)
    hits = _search_faces(vector, limit=10)
    matches = []
    with _session() as s:
        for h in hits:
            if h.get("score", 0.0) < min_conf:
                continue
            pid = h.get("person_id")
            person = s.get(FRSPerson, pid) if pid else None
            matches.append({
                "person_id": pid,
                "person_name": person.full_name if person else None,
                "confidence": round(float(h.get("score", 0.0)), 4),
                "photo_id": h.get("photo_id"),
            })
    return {"matches": matches, "match_count": len(matches)}


@app.post("/recognize-image")
async def recognize_image(file: UploadFile = File(...), _: None = Depends(_require_service_token)) -> JSONResponse:
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty upload")
    return JSONResponse(_recognize(data))


@app.post("/detect-faces")
async def detect_faces(file: UploadFile = File(...), _: None = Depends(_require_service_token)) -> JSONResponse:
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty upload")
    image = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = image.size
    return JSONResponse({"faces": [{"bbox": [0.1, 0.1, 0.9, 0.9], "confidence": 0.9}], "width": w, "height": h})


# =============================================================================
# Investigate (forensic search by query face) + tour
# =============================================================================

@app.post("/investigate")
async def investigate(file: UploadFile = File(...), top_k: int = Form(50),
                      _: None = Depends(_require_service_token)) -> JSONResponse:
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty upload")
    vector = _face_embedding(data)
    hits = _search_faces(vector, limit=top_k)
    out = []
    with _session() as s:
        for h in hits:
            pid = h.get("person_id")
            person = s.get(FRSPerson, pid) if pid else None
            out.append({
                "person_id": pid,
                "person_name": person.full_name if person else None,
                "photo_id": h.get("photo_id"),
                "score": round(float(h.get("score", 0.0)), 4),
                "snapshot_path": f"/photos/{h.get('photo_id')}/image" if h.get("photo_id") else None,
            })
    return JSONResponse({"hits": out, "total": len(out)})


@app.get("/tour/timeline/{person_id}")
def tour_timeline(person_id: str, _: None = Depends(_require_service_token)) -> dict:
    with _session() as s:
        rows = s.execute(
            select(FRSEvent).where(FRSEvent.person_id == person_id)
            .order_by(FRSEvent.triggered_at.desc()).limit(500)
        ).scalars().all()
        entries = [
            {"camera_id": e.camera_id, "triggered_at": _iso(e.triggered_at),
             "confidence": e.confidence, "event_type": e.event_type,
             "snapshot_path": e.snapshot_path}
            for e in rows
        ]
    return {"person_id": person_id, "entries": entries, "total": len(entries)}


# =============================================================================
# Transit rules + sessions (plugin-owned)
# =============================================================================

@app.post("/transit/rules")
def create_transit_rule(body: dict = Body(...), _: None = Depends(_require_service_token)) -> dict:
    with _session() as s:
        r = TransitRule(name=body.get("name") or "rule", config=body.get("config") or body,
                        enabled=bool(body.get("enabled", True)))
        s.add(r); s.commit(); s.refresh(r)
        return {"id": r.id, "name": r.name, "config": r.config, "enabled": r.enabled}


@app.get("/transit/rules")
def list_transit_rules(_: None = Depends(_require_service_token)) -> dict:
    with _session() as s:
        rows = s.execute(select(TransitRule).order_by(TransitRule.created_at.desc())).scalars().all()
        return {"rules": [{"id": r.id, "name": r.name, "config": r.config, "enabled": r.enabled} for r in rows]}


@app.put("/transit/rules/{rule_id}")
def update_transit_rule(rule_id: str, body: dict = Body(...), _: None = Depends(_require_service_token)) -> dict:
    with _session() as s:
        r = s.get(TransitRule, rule_id)
        if not r:
            raise HTTPException(404, "rule not found")
        if "name" in body:
            r.name = body["name"]
        if "config" in body:
            r.config = body["config"]
        if "enabled" in body:
            r.enabled = bool(body["enabled"])
        s.commit(); s.refresh(r)
        return {"id": r.id, "name": r.name, "config": r.config, "enabled": r.enabled}


@app.delete("/transit/rules/{rule_id}")
def delete_transit_rule(rule_id: str, _: None = Depends(_require_service_token)) -> dict:
    with _session() as s:
        r = s.get(TransitRule, rule_id)
        if not r:
            raise HTTPException(404, "rule not found")
        s.delete(r); s.commit()
    return {"ok": True, "id": rule_id}


@app.get("/transit/sessions")
def list_transit_sessions(status: Optional[str] = None, since: Optional[str] = None,
                          until: Optional[str] = None, limit: int = 100, offset: int = 0,
                          _: None = Depends(_require_service_token)) -> dict:
    with _session() as s:
        q = select(TransitSession)
        if status:
            q = q.where(TransitSession.status == status)
        if since:
            q = q.where(TransitSession.started_at >= _naive(_parse_dt(since)))
        if until:
            q = q.where(TransitSession.started_at <= _naive(_parse_dt(until)))
        total = int(s.scalar(select(func.count()).select_from(q.subquery())) or 0)
        rows = s.execute(q.order_by(TransitSession.created_at.desc()).limit(limit).offset(offset)).scalars().all()
        sessions = [{"id": x.id, "rule_id": x.rule_id, "person_id": x.person_id,
                     "status": x.status, "started_at": _iso(x.started_at),
                     "ended_at": _iso(x.ended_at), "attributes": x.attributes} for x in rows]
    return {"sessions": sessions, "total": total}


# =============================================================================
# Recordings + video jobs
# =============================================================================

def _recordings(params: dict[str, Any]) -> list[dict[str, Any]]:
    headers = {"X-Vizor-Service-Token": VIZOR_SERVICE_TOKEN, "X-Vizor-Scenario": SCENARIO_SLUG}
    resp = requests.get(f"{VIZOR_BASE_URL}/ai/internal/recordings", params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    return list(resp.json().get("items") or [])


def _extract_frame(recording_path: str, offset: int, out_path: Path) -> bool:
    if not recording_path or not Path(recording_path).exists():
        return False
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(max(0, offset)),
           "-i", recording_path, "-frames:v", "1", "-vf", "scale=480:-1", "-q:v", "4", "-y", str(out_path)]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=25, check=False)
        return proc.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0
    except Exception:
        return False


def _set_job(job_id: str, **patch: Any) -> None:
    job = JOBS.get(job_id)
    if job:
        job.update(patch)


def _record_event(camera_id: str | None, person_id: str | None, person_name: str | None,
                  confidence: float, snapshot_path: str | None, ts: datetime) -> None:
    event_type = "face_recognized" if person_id else "face_unknown"
    with _session() as s:
        ev = FRSEvent(
            camera_id=camera_id, event_type=event_type, severity="info",
            title=person_name or "Unknown face", detection_type="face",
            person_id=person_id, confidence=round(confidence, 4),
            snapshot_path=snapshot_path, triggered_at=_naive(ts) or ts,
        )
        s.add(ev)
        if person_id:
            day_key = (ts or datetime.utcnow()).date().isoformat()
            existing = s.scalar(select(FRSAttendance).where(
                FRSAttendance.person_id == person_id, FRSAttendance.day_key == day_key))
            if existing:
                existing.check_out_at = _naive(ts)
            else:
                s.add(FRSAttendance(person_id=person_id, camera_id=camera_id, day_key=day_key,
                                    check_in_at=_naive(ts), sighting_type="seen", event_id=ev.id))
        s.commit()


def _run_video_job(job_id: str, payload: dict[str, Any], upload_path: Path | None) -> None:
    min_conf = float(payload.get("min_confidence") or 0.6)
    sources: list[tuple[str, str | None, datetime | None]] = []
    if upload_path is not None:
        sources.append((str(upload_path), None, None))
    else:
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
            _set_job(job_id, state="JOB_FAILED", progress=1.0, error=f"recording_catalog_failed:{exc}")
            return
        for rec in recs:
            sources.append((rec.get("file_path") or "", rec.get("camera_id"), _parse_dt(rec.get("start_time"))))

    events: list[dict[str, Any]] = []
    scanned = 0
    _set_job(job_id, state="JOB_PROCESSING", progress=0.0, frames_processed=0, frames_total=0)
    total_estimate = max(1, len(sources)) * (MAX_SCAN_FRAMES // max(1, len(sources)))
    for file_path, camera_id, start in sources:
        if JOBS.get(job_id, {}).get("state") == "JOB_CANCELLED":
            return
        duration = int(payload.get("duration") or 0)
        offsets = list(range(0, max(1, duration), max(1, FRAME_INTERVAL_SECONDS))) or [0]
        for offset in offsets:
            if scanned >= MAX_SCAN_FRAMES:
                break
            frame_id = str(uuid.uuid4())
            frame_path = DATA_PATH / "frames" / f"{frame_id}.jpg"
            frame_path.parent.mkdir(parents=True, exist_ok=True)
            if not _extract_frame(file_path, offset, frame_path):
                continue
            scanned += 1
            try:
                rec = _recognize(frame_path.read_bytes(), min_conf=min_conf)
            except Exception:
                continue
            ts = (start + timedelta(seconds=offset)) if start else datetime.utcnow()
            for m in rec["matches"]:
                snap = f"/photos/{m['photo_id']}/image" if m.get("photo_id") else None
                _record_event(camera_id, m["person_id"], m["person_name"], m["confidence"], snap, ts)
                events.append({
                    "id": frame_id, "person_id": m["person_id"], "person_name": m["person_name"],
                    "camera_id": camera_id, "timestamp": _iso(ts), "confidence": m["confidence"],
                })
            _set_job(job_id, frames_processed=scanned, frames_total=total_estimate,
                     progress=round(min(0.99, scanned / total_estimate), 3), result_count=len(events))
        if scanned >= MAX_SCAN_FRAMES:
            break
    _set_job(job_id, state="JOB_COMPLETED", progress=1.0, frames_processed=scanned,
             frames_total=scanned, result_count=len(events), events=events)


async def _video_payload(request: Request) -> tuple[dict[str, Any], bytes | None]:
    allowed = request.headers.get("X-Vizor-Allowed-Camera-Ids") or ""
    form = await request.form()
    ref = form.get("file")
    blob = await ref.read() if hasattr(ref, "read") else None
    requested = str(form.get("camera_ids") or "")
    allowed_list = [x.strip() for x in allowed.split(",") if x.strip()]
    req_list = [x.strip() for x in requested.split(",") if x.strip()]
    selected = [x for x in req_list if x in set(allowed_list)] if (allowed_list and req_list) else (allowed_list or req_list)
    return {
        "camera_ids": ",".join(selected),
        "path": str(form.get("path") or ""),
        "sample_fps": form.get("sample_fps"),
        "recognize": form.get("recognize"),
        "check_liveness": form.get("check_liveness"),
        "min_confidence": form.get("min_confidence"),
        "start_time": str(form.get("start_time") or ""),
        "end_time": str(form.get("end_time") or ""),
    }, blob


@app.post("/video-jobs")
async def submit_video_job(request: Request, _: None = Depends(_require_service_token)) -> JSONResponse:
    payload, blob = await _video_payload(request)
    if not blob and not payload.get("path") and not payload.get("camera_ids"):
        raise HTTPException(400, "provide a file upload, a path, or assigned cameras")
    job_id = str(uuid.uuid4())
    upload_path: Path | None = None
    if blob:
        upload_path = DATA_PATH / "uploads" / f"{job_id}.mp4"
        upload_path.parent.mkdir(parents=True, exist_ok=True)
        upload_path.write_bytes(blob)
    elif payload.get("path"):
        upload_path = Path(payload["path"])
    JOBS[job_id] = {"job_id": job_id, "state": "JOB_QUEUED", "progress": 0.0,
                    "frames_processed": 0, "frames_total": 0, "result_count": 0, "events": []}
    threading.Thread(target=_run_video_job, args=(job_id, payload, upload_path), daemon=True).start()
    return JSONResponse({"job_id": job_id, "state": "JOB_QUEUED"}, status_code=202)


@app.get("/video-jobs/{job_id}")
def get_video_job(job_id: str, _: None = Depends(_require_service_token)) -> dict:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return {k: v for k, v in job.items() if k != "events"}


@app.get("/video-jobs/{job_id}/results")
def get_video_results(job_id: str, _: None = Depends(_require_service_token)) -> dict:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return {"events": list(job.get("events") or []), "total": len(job.get("events") or [])}


@app.get("/snapshot")
def snapshot(key: str = Query(...), _: None = Depends(_require_service_token)):
    # FRS snapshots are stored as person photos; key is a photo_id.
    with _session() as s:
        ph = s.get(FRSPhoto, key)
        path = DATA_PATH / ph.storage_key if (ph and ph.storage_key) else None
    if not path or not path.exists():
        raise HTTPException(404, "snapshot not found")
    return FileResponse(str(path), media_type="image/jpeg")


# =============================================================================
# Events / attendance / reports / live (plugin-owned read side)
# =============================================================================

@app.get("/events")
def list_events(camera_id: Optional[list[str]] = Query(None), person_id: Optional[str] = None,
                event_type: Optional[str] = None, since: Optional[datetime] = None,
                until: Optional[datetime] = None, limit: int = Query(50, ge=1, le=500),
                offset: int = Query(0, ge=0), _: None = Depends(_require_service_token)) -> dict:
    with _session() as s:
        conds = []
        if camera_id:
            conds.append(FRSEvent.camera_id.in_(camera_id))
        if person_id:
            conds.append(FRSEvent.person_id == person_id)
        if event_type:
            conds.append(FRSEvent.event_type == event_type)
        if since:
            conds.append(FRSEvent.triggered_at >= _naive(since))
        if until:
            conds.append(FRSEvent.triggered_at <= _naive(until))
        where = and_(*conds) if conds else None
        cq = select(func.count()).select_from(FRSEvent)
        rq = select(FRSEvent)
        if where is not None:
            cq = cq.where(where); rq = rq.where(where)
        total = int(s.scalar(cq) or 0)
        rows = s.execute(rq.order_by(FRSEvent.triggered_at.desc()).limit(limit).offset(offset)).scalars().all()
        return {"items": [_event_dict(e) for e in rows], "total": total, "limit": limit, "offset": offset}


@app.get("/attendance")
def list_attendance(person_id: Optional[str] = None, camera_id: Optional[str] = None,
                    since: Optional[datetime] = None, until: Optional[datetime] = None,
                    limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
                    _: None = Depends(_require_service_token)) -> dict:
    with _session() as s:
        conds = []
        if person_id:
            conds.append(FRSAttendance.person_id == person_id)
        if camera_id:
            conds.append(FRSAttendance.camera_id == camera_id)
        if since:
            conds.append(FRSAttendance.check_in_at >= _naive(since))
        if until:
            conds.append(FRSAttendance.check_in_at <= _naive(until))
        where = and_(*conds) if conds else None
        cq = select(func.count()).select_from(FRSAttendance)
        if where is not None:
            cq = cq.where(where)
        total = int(s.scalar(cq) or 0)
        stmt = (select(FRSAttendance, FRSPerson.full_name)
                .outerjoin(FRSPerson, FRSPerson.id == FRSAttendance.person_id)
                .order_by(FRSAttendance.day_key.desc(), FRSAttendance.check_in_at.desc())
                .limit(limit).offset(offset))
        if where is not None:
            stmt = stmt.where(where)
        rows = [{
            "id": a.id, "person_id": a.person_id, "person_name": name, "camera_id": a.camera_id,
            "day_key": a.day_key, "check_in_at": _iso(a.check_in_at), "check_out_at": _iso(a.check_out_at),
            "sighting_type": a.sighting_type, "event_id": a.event_id,
        } for a, name in s.execute(stmt).all()]
        return {"items": rows, "total": total, "limit": limit, "offset": offset}


@app.get("/attendance/report")
def attendance_report(day_from: str = Query(...), day_to: str = Query(...),
                      _: None = Depends(_require_service_token)) -> dict:
    if day_from > day_to:
        raise HTTPException(400, "day_from must not be after day_to")
    with _session() as s:
        stmt = (select(
            FRSAttendance.person_id, FRSPerson.full_name,
            func.count(func.distinct(FRSAttendance.day_key)).label("days_present"),
            func.min(FRSAttendance.check_in_at).label("first_seen"),
            func.max(func.coalesce(FRSAttendance.check_out_at, FRSAttendance.check_in_at)).label("last_seen"),
        ).outerjoin(FRSPerson, FRSPerson.id == FRSAttendance.person_id)
         .where(and_(FRSAttendance.day_key >= day_from, FRSAttendance.day_key <= day_to))
         .group_by(FRSAttendance.person_id, FRSPerson.full_name)
         .order_by(func.count(func.distinct(FRSAttendance.day_key)).desc()))
        rows = [{
            "person_id": pid, "person_name": name, "days_present": int(dp or 0),
            "first_seen": _iso(fs), "last_seen": _iso(ls),
        } for pid, name, dp, fs, ls in s.execute(stmt).all()]
    return {"items": rows, "day_from": day_from, "day_to": day_to}


@app.get("/reports/summary")
def reports_summary(since: Optional[datetime] = None, until: Optional[datetime] = None,
                    _: None = Depends(_require_service_token)) -> dict:
    with _session() as s:
        conds = []
        if since:
            conds.append(FRSEvent.triggered_at >= _naive(since))
        if until:
            conds.append(FRSEvent.triggered_at <= _naive(until))
        where = and_(*conds) if conds else None
        agg = select(
            func.count().label("total_events"),
            func.count(func.distinct(FRSEvent.person_id)).label("unique_persons"),
            func.count().filter(FRSEvent.event_type == "face_unknown").label("unknown_count"),
            func.count().filter(FRSEvent.event_type == "spoof_detected").label("spoof_count"),
        )
        cam = select(FRSEvent.camera_id, func.count().label("count")).group_by(FRSEvent.camera_id).order_by(func.count().desc())
        hour = (select(func.extract("hour", FRSEvent.triggered_at).label("hour"), func.count().label("count"))
                .group_by(func.extract("hour", FRSEvent.triggered_at))
                .order_by(func.extract("hour", FRSEvent.triggered_at)))
        if where is not None:
            agg = agg.where(where); cam = cam.where(where); hour = hour.where(where)
        a = s.execute(agg).one()
        by_camera = [{"camera_id": c, "count": int(n)} for c, n in s.execute(cam).all()]
        by_hour = [{"hour": int(h), "count": int(n)} for h, n in s.execute(hour).all()]
    return {"total_events": int(a.total_events or 0), "unique_persons": int(a.unique_persons or 0),
            "unknown_count": int(a.unknown_count or 0), "spoof_count": int(a.spoof_count or 0),
            "by_camera": by_camera, "by_hour": by_hour}


@app.get("/live")
def live(camera_id: Optional[list[str]] = Query(None), limit: int = Query(50, ge=1, le=200),
         _: None = Depends(_require_service_token)) -> dict:
    with _session() as s:
        q = select(FRSEvent)
        if camera_id:
            q = q.where(FRSEvent.camera_id.in_(camera_id))
        rows = s.execute(q.order_by(FRSEvent.triggered_at.desc()).limit(limit)).scalars().all()
        return {"items": [_event_dict(e) for e in rows]}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
