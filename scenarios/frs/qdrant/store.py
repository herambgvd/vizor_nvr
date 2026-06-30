"""Vector store for FRS face embeddings — backed by Postgres + pgvector (replaces
the standalone qdrant container). Two logical collections, one table each:

  - QDRANT_COLLECTION  (gallery)   — enrolled person photos + augments. Used by
    enrollment, live recognition matching, the Recognize tab.
  - SNAPSHOTS_COLLECTION (snapshots) — captured live-event face embeddings (one row
    per emitted event). The forensic index the Investigate tab searches.

Both are 512-d, cosine distance. The public interface is UNCHANGED — client(),
upsert(), delete_by(), search() — so every call site stays the same; only the
backend moved from qdrant to pgvector on the FRS Postgres (FRS_DATABASE_URL).

Per-table schema:
    id        text primary key      (point id; gallery uses one id per main/augment)
    embedding vector(512)
    payload   jsonb                  (camera_id, person_id, point_key, ...)
Indexes: ivfflat on embedding (cosine) + a GIN on payload for filtered delete/search.
"""
from __future__ import annotations

import json
import threading
from typing import Any

from config import FRS_DATABASE_URL, QDRANT_COLLECTION, VECTOR_SIZE

# Logical collection names map to physical table names. Keep the historical
# QDRANT_COLLECTION env so deployments don't have to change anything.
GALLERY_COLLECTION = QDRANT_COLLECTION
SNAPSHOTS_COLLECTION = f"{QDRANT_COLLECTION}_snapshots"


def _table(collection: str | None) -> str:
    coll = collection or GALLERY_COLLECTION
    return "vec_" + "".join(ch if ch.isalnum() else "_" for ch in coll)


_ENGINE: Any | None = None
_READY: set[str] = set()
_LOCK = threading.Lock()


def client() -> Any | None:
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


def upsert(point_id: str, vector: list[float], payload: dict[str, Any],
           collection: str | None = None) -> bool:
    """Upsert one point. Returns True on success, False on failure — callers that
    need consistency (enrollment) MUST check this."""
    eng = client()
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


def delete_by(field: str, value: str, collection: str | None = None) -> bool:
    """Delete every point whose payload[field] == value (point_key=photo or
    person_id). Returns True on success, False (logged) on failure."""
    eng = client()
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


def search(vector: list[float], limit: int = 50, collection: str | None = None,
           camera_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """Cosine top-k. Returns payloads with a 'score' (1 - cosine distance, higher =
    closer), matching the qdrant score semantics callers expect."""
    eng = client()
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
