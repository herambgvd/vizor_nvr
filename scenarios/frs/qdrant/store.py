"""Vector store for FRS face embeddings — DUAL backend, auto-selected at import:

  - QDRANT_URL set (legacy infra, e.g. SMCC's gvd_ai_qdrant container)  → Qdrant
  - QDRANT_URL empty (consolidated infra)                               → Postgres + pgvector
    on the FRS Postgres (FRS_DATABASE_URL)

One image therefore runs unmodified on BOTH infrastructures — a deployment that
still ships the qdrant container just keeps its existing QDRANT_URL env and its
enrolled vectors stay valid; new deployments leave it unset and get pgvector.

Two logical collections in either backend:

  - QDRANT_COLLECTION  (gallery)   — enrolled person photos + augments. Used by
    enrollment, live recognition matching, the Recognize tab.
  - SNAPSHOTS_COLLECTION (snapshots) — captured live-event face embeddings (one
    point/row per emitted event). The forensic index the Investigate tab searches.

Both are 512-d, cosine. Public interface identical across backends — client(),
upsert(), delete_by(), search() — search returns payload dicts + 'score'
(higher = closer) in qdrant semantics.
"""
from __future__ import annotations

import json
import threading
from typing import Any

from config import FRS_DATABASE_URL, QDRANT_COLLECTION, QDRANT_URL, VECTOR_SIZE

# Logical collection names. Keep the historical QDRANT_COLLECTION env so
# deployments don't have to change anything.
GALLERY_COLLECTION = QDRANT_COLLECTION
SNAPSHOTS_COLLECTION = f"{QDRANT_COLLECTION}_snapshots"

_USE_QDRANT = bool(QDRANT_URL)

# --------------------------------------------------------------------------- #
# Qdrant backend (legacy infra: QDRANT_URL set)
# --------------------------------------------------------------------------- #

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels
except Exception:  # noqa: BLE001
    QdrantClient = None
    qmodels = None

_QDRANT: Any | None = None


def _qdrant_client() -> Any | None:
    """Lazy Qdrant client. Creates both collections (cosine, 512-d) if missing."""
    global _QDRANT
    if _QDRANT is not None:
        return _QDRANT
    if not QDRANT_URL or QdrantClient is None or qmodels is None:
        return None
    try:
        _QDRANT = QdrantClient(url=QDRANT_URL, timeout=10)
        existing = {c.name for c in _QDRANT.get_collections().collections}
        for coll in (GALLERY_COLLECTION, SNAPSHOTS_COLLECTION):
            if coll not in existing:
                _QDRANT.create_collection(
                    collection_name=coll,
                    vectors_config=qmodels.VectorParams(size=VECTOR_SIZE, distance=qmodels.Distance.COSINE),
                )
        return _QDRANT
    except Exception as exc:  # noqa: BLE001
        print(f"[frs] qdrant unavailable: {exc}", flush=True)
        _QDRANT = None
        return None


def _qdrant_upsert(point_id: str, vector: list[float], payload: dict[str, Any],
                   collection: str | None = None) -> bool:
    c = _qdrant_client()
    if not c or qmodels is None:
        return False
    try:
        c.upsert(collection_name=collection or GALLERY_COLLECTION,
                 points=[qmodels.PointStruct(id=point_id, vector=vector, payload=payload)])
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[frs] qdrant upsert failed: {exc}", flush=True)
        return False


def _qdrant_delete_by(field: str, value: str, collection: str | None = None) -> bool:
    c = _qdrant_client()
    if not c or qmodels is None or not value:
        return False
    try:
        flt = qmodels.Filter(must=[qmodels.FieldCondition(
            key=field, match=qmodels.MatchValue(value=value))])
        c.delete(collection_name=collection or GALLERY_COLLECTION,
                 points_selector=qmodels.FilterSelector(filter=flt))
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[frs] qdrant filtered delete failed: {exc}", flush=True)
        return False


def _qdrant_search(vector: list[float], limit: int = 50, collection: str | None = None,
                   camera_ids: list[str] | None = None) -> list[dict[str, Any]]:
    c = _qdrant_client()
    if not c:
        return []
    coll = collection or GALLERY_COLLECTION
    flt = None
    if camera_ids and qmodels is not None:
        flt = qmodels.Filter(must=[qmodels.FieldCondition(
            key="camera_id", match=qmodels.MatchAny(any=list(camera_ids)))])
    try:
        points = c.query_points(collection_name=coll, query=vector, limit=limit,
                                query_filter=flt, with_payload=True).points
    except AttributeError:
        points = c.search(collection_name=coll, query_vector=vector, limit=limit,
                          query_filter=flt, with_payload=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[frs] qdrant search failed: {exc}", flush=True)
        return []
    out = []
    for p in points:
        item = dict(p.payload or {})
        item["score"] = float(getattr(p, "score", 0.0) or 0.0)
        out.append(item)
    return out


# --------------------------------------------------------------------------- #
# pgvector backend (consolidated infra: QDRANT_URL empty)
#
# Per-table schema:
#     id        text primary key      (point id; gallery uses one id per main/augment)
#     embedding vector(512)
#     payload   jsonb                  (camera_id, person_id, point_key, ...)
# Indexes: ivfflat on embedding (cosine) + a GIN on payload for filtered delete/search.
# --------------------------------------------------------------------------- #


def _table(collection: str | None) -> str:
    coll = collection or GALLERY_COLLECTION
    return "vec_" + "".join(ch if ch.isalnum() else "_" for ch in coll)


_ENGINE: Any | None = None
_READY: set[str] = set()
_LOCK = threading.Lock()


def _pg_client() -> Any | None:
    """Lazy SQLAlchemy engine on the FRS Postgres, with pgvector enabled and both
    vector tables created. Returns the engine (truthy) or None if unavailable."""
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    with _LOCK:
        if _ENGINE is not None:
            return _ENGINE
        try:
            from sqlalchemy import create_engine, text
            eng = create_engine(FRS_DATABASE_URL, pool_pre_ping=True, future=True)
            with eng.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            _ENGINE = eng
            for coll in (GALLERY_COLLECTION, SNAPSHOTS_COLLECTION):
                _ensure_table(coll)
            return _ENGINE
        except Exception as exc:  # noqa: BLE001
            print(f"[frs] pgvector unavailable: {exc}", flush=True)
            _ENGINE = None
            return None


def _ensure_table(collection: str) -> None:
    if collection in _READY or _ENGINE is None:
        return
    from sqlalchemy import text
    t = _table(collection)
    with _ENGINE.begin() as conn:
        conn.execute(text(
            f"CREATE TABLE IF NOT EXISTS {t} ("
            f"  id text PRIMARY KEY,"
            f"  embedding vector({VECTOR_SIZE}),"
            f"  payload jsonb NOT NULL DEFAULT '{{}}'::jsonb)"))
        conn.execute(text(
            f"CREATE INDEX IF NOT EXISTS {t}_emb_idx ON {t} "
            f"USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"))
        conn.execute(text(
            f"CREATE INDEX IF NOT EXISTS {t}_payload_idx ON {t} USING gin (payload)"))
    _READY.add(collection)


def _vec_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


def _pg_upsert(point_id: str, vector: list[float], payload: dict[str, Any],
               collection: str | None = None) -> bool:
    eng = _pg_client()
    if not eng:
        return False
    try:
        from sqlalchemy import text
        _ensure_table(collection or GALLERY_COLLECTION)
        t = _table(collection)
        with eng.begin() as conn:
            conn.execute(text(
                f"INSERT INTO {t} (id, embedding, payload) "
                f"VALUES (:id, :emb, :pl) "
                f"ON CONFLICT (id) DO UPDATE SET embedding = EXCLUDED.embedding, "
                f"payload = EXCLUDED.payload"),
                {"id": point_id, "emb": _vec_literal(vector), "pl": json.dumps(payload)})
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[frs] pgvector upsert failed: {exc}", flush=True)
        return False


def _pg_delete_by(field: str, value: str, collection: str | None = None) -> bool:
    eng = _pg_client()
    if not eng or not value:
        return False
    try:
        from sqlalchemy import text
        t = _table(collection)
        with eng.begin() as conn:
            conn.execute(text(
                f"DELETE FROM {t} WHERE payload ->> :field = :value"),
                {"field": field, "value": value})
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[frs] pgvector filtered delete failed: {exc}", flush=True)
        return False


def _pg_search(vector: list[float], limit: int = 50, collection: str | None = None,
               camera_ids: list[str] | None = None) -> list[dict[str, Any]]:
    eng = _pg_client()
    if not eng:
        return []
    try:
        from sqlalchemy import text
        _ensure_table(collection or GALLERY_COLLECTION)
        t = _table(collection)
        params: dict[str, Any] = {"q": _vec_literal(vector), "lim": int(limit)}
        where = ""
        if camera_ids:
            where = " WHERE payload ->> 'camera_id' = ANY(:cams)"
            params["cams"] = list(camera_ids)
        with eng.connect() as conn:
            rows = conn.execute(text(
                f"SELECT payload, 1 - (embedding <=> :q) AS score "
                f"FROM {t}{where} ORDER BY embedding <=> :q LIMIT :lim"), params).all()
        out = []
        for payload, score in rows:
            item = dict(payload or {})
            item["score"] = float(score or 0.0)
            out.append(item)
        return out
    except Exception as exc:  # noqa: BLE001
        print(f"[frs] pgvector search failed: {exc}", flush=True)
        return []


# --------------------------------------------------------------------------- #
# Public interface — dispatches on the backend selected at import.
# --------------------------------------------------------------------------- #


def client() -> Any | None:
    """Lazy backend handle (truthy when the store is reachable), or None."""
    return _qdrant_client() if _USE_QDRANT else _pg_client()


def upsert(point_id: str, vector: list[float], payload: dict[str, Any],
           collection: str | None = None) -> bool:
    """Upsert one point. Returns True on success, False on failure — callers that
    need consistency (enrollment) MUST check this."""
    if _USE_QDRANT:
        return _qdrant_upsert(point_id, vector, payload, collection)
    return _pg_upsert(point_id, vector, payload, collection)


def delete_by(field: str, value: str, collection: str | None = None) -> bool:
    """Delete every point whose payload[field] == value (point_key=photo or
    person_id). Returns True on success, False (logged) on failure."""
    if _USE_QDRANT:
        return _qdrant_delete_by(field, value, collection)
    return _pg_delete_by(field, value, collection)


def search(vector: list[float], limit: int = 50, collection: str | None = None,
           camera_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """Cosine top-k. Returns payloads with a 'score' (higher = closer)."""
    if _USE_QDRANT:
        return _qdrant_search(vector, limit, collection, camera_ids)
    return _pg_search(vector, limit, collection, camera_ids)
