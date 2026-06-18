"""Qdrant face-vector store: collection bootstrap + upsert / search / delete."""
from __future__ import annotations

from typing import Any

from config import QDRANT_COLLECTION, QDRANT_URL, VECTOR_SIZE

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels
except Exception:  # noqa: BLE001
    QdrantClient = None
    qmodels = None

_QDRANT: Any | None = None


def client() -> Any | None:
    """Lazy Qdrant client. Creates the collection (cosine, 512-d) if missing."""
    global _QDRANT
    if _QDRANT is not None:
        return _QDRANT
    if not QDRANT_URL or QdrantClient is None or qmodels is None:
        return None
    try:
        _QDRANT = QdrantClient(url=QDRANT_URL, timeout=10)
        existing = {c.name for c in _QDRANT.get_collections().collections}
        if QDRANT_COLLECTION not in existing:
            _QDRANT.create_collection(
                collection_name=QDRANT_COLLECTION,
                vectors_config=qmodels.VectorParams(size=VECTOR_SIZE, distance=qmodels.Distance.COSINE),
            )
        return _QDRANT
    except Exception as exc:  # noqa: BLE001
        print(f"[frs] qdrant unavailable: {exc}", flush=True)
        _QDRANT = None
        return None


def upsert(point_id: str, vector: list[float], payload: dict[str, Any]) -> None:
    c = client()
    if not c or qmodels is None:
        return
    try:
        c.upsert(collection_name=QDRANT_COLLECTION,
                 points=[qmodels.PointStruct(id=point_id, vector=vector, payload=payload)])
    except Exception as exc:  # noqa: BLE001
        print(f"[frs] qdrant upsert failed: {exc}", flush=True)


def delete_by(field: str, value: str) -> None:
    """Delete every point matching a payload field (point_key=photo or person_id).
    Enrollment stores 1 main + N augment points per photo, so a single id can't
    remove them all — filter by the shared key instead."""
    c = client()
    if not c or qmodels is None or not value:
        return
    try:
        flt = qmodels.Filter(must=[qmodels.FieldCondition(
            key=field, match=qmodels.MatchValue(value=value))])
        c.delete(collection_name=QDRANT_COLLECTION,
                 points_selector=qmodels.FilterSelector(filter=flt))
    except Exception as exc:  # noqa: BLE001
        print(f"[frs] qdrant filtered delete failed: {exc}", flush=True)


def search(vector: list[float], limit: int = 50) -> list[dict[str, Any]]:
    c = client()
    if not c:
        return []
    try:
        points = c.query_points(collection_name=QDRANT_COLLECTION, query=vector,
                                limit=limit, with_payload=True).points
    except AttributeError:
        points = c.search(collection_name=QDRANT_COLLECTION, query_vector=vector,
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
