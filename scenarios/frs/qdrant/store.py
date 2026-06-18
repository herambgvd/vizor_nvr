"""Qdrant vector store. Two collections:
  - QDRANT_COLLECTION  — the enrolled gallery (person photos + augments). Used by
    enrollment, live recognition matching, and the Recognize tab.
  - SNAPSHOTS_COLLECTION — captured live-event face embeddings (one point per
    emitted event). This is the forensic index the Investigate tab searches:
    "where/when was this face seen", mirroring vizor-app's frs_snapshots.

Both are 512-d cosine. All functions take an optional `collection` arg
(defaults to the gallery) so call sites stay terse.
"""
from __future__ import annotations

from typing import Any

from config import QDRANT_COLLECTION, QDRANT_URL, VECTOR_SIZE

SNAPSHOTS_COLLECTION = f"{QDRANT_COLLECTION}_snapshots"

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels
except Exception:  # noqa: BLE001
    QdrantClient = None
    qmodels = None

_QDRANT: Any | None = None


def client() -> Any | None:
    """Lazy Qdrant client. Creates both collections (cosine, 512-d) if missing."""
    global _QDRANT
    if _QDRANT is not None:
        return _QDRANT
    if not QDRANT_URL or QdrantClient is None or qmodels is None:
        return None
    try:
        _QDRANT = QdrantClient(url=QDRANT_URL, timeout=10)
        existing = {c.name for c in _QDRANT.get_collections().collections}
        for coll in (QDRANT_COLLECTION, SNAPSHOTS_COLLECTION):
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


def upsert(point_id: str, vector: list[float], payload: dict[str, Any],
           collection: str | None = None) -> bool:
    """Upsert one point. Returns True on success, False on failure — callers that
    need consistency (enrollment) MUST check this and not assume success."""
    c = client()
    if not c or qmodels is None:
        return False
    try:
        c.upsert(collection_name=collection or QDRANT_COLLECTION,
                 points=[qmodels.PointStruct(id=point_id, vector=vector, payload=payload)])
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[frs] qdrant upsert failed: {exc}", flush=True)
        return False


def delete_by(field: str, value: str, collection: str | None = None) -> bool:
    """Delete every point matching a payload field (point_key=photo or person_id).
    Enrollment stores 1 main + N augment points per photo, so a single id can't
    remove them all — filter by the shared key instead. Returns True on success;
    False (logged) on failure so erasure callers can retry/reconcile."""
    c = client()
    if not c or qmodels is None or not value:
        return False
    try:
        flt = qmodels.Filter(must=[qmodels.FieldCondition(
            key=field, match=qmodels.MatchValue(value=value))])
        c.delete(collection_name=collection or QDRANT_COLLECTION,
                 points_selector=qmodels.FilterSelector(filter=flt))
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[frs] qdrant filtered delete failed: {exc}", flush=True)
        return False


def search(vector: list[float], limit: int = 50, collection: str | None = None,
           camera_ids: list[str] | None = None) -> list[dict[str, Any]]:
    c = client()
    if not c:
        return []
    coll = collection or QDRANT_COLLECTION
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
