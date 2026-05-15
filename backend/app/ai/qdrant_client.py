"""
Qdrant async client wrapper — FRS embeddings collection.

Single collection `frs_faces` (single-tenant install). Vector dim 512,
cosine distance. Each point payload carries:
  person_id    str  — FK to frs_persons
  photo_id     str  — FK to frs_photos
"""

from __future__ import annotations

import asyncio
import logging
import uuid as _uuid
from typing import List, Optional

import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)

COLLECTION = "frs_faces"
VECTOR_SIZE = 512

try:
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.http import models as qm
    _HAS_QDRANT = True
except ImportError:
    _HAS_QDRANT = False
    AsyncQdrantClient = None  # type: ignore
    qm = None  # type: ignore


_client: Optional["AsyncQdrantClient"] = None
_lock = asyncio.Lock()


async def get_client() -> "AsyncQdrantClient":
    global _client
    if not _HAS_QDRANT:
        raise RuntimeError("qdrant-client not installed")
    if not settings.QDRANT_URL:
        raise RuntimeError("QDRANT_URL not configured")
    async with _lock:
        if _client is None:
            _client = AsyncQdrantClient(url=settings.QDRANT_URL, prefer_grpc=False)
        return _client


async def ensure_collection() -> None:
    """Create the FRS faces collection if missing. Idempotent."""
    try:
        client = await get_client()
        existing = await client.get_collections()
        names = {c.name for c in existing.collections}
        if COLLECTION in names:
            return
        await client.create_collection(
            collection_name=COLLECTION,
            vectors_config=qm.VectorParams(
                size=VECTOR_SIZE, distance=qm.Distance.COSINE,
            ),
        )
        logger.info("Created Qdrant collection '%s'", COLLECTION)
    except Exception as e:
        logger.warning("ensure_collection failed: %s", e)


def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(vec)
    return vec if n == 0 else (vec / n)


async def upsert_embedding(
    person_id: str,
    photo_id: str,
    vector: np.ndarray,
) -> str:
    """Insert/update a face embedding. Returns the Qdrant point id."""
    client = await get_client()
    point_id = str(_uuid.uuid4())
    vec = _l2_normalize(vector.astype(np.float32))
    await client.upsert(
        collection_name=COLLECTION,
        points=[
            qm.PointStruct(
                id=point_id,
                vector=vec.tolist(),
                payload={"person_id": person_id, "photo_id": photo_id},
            )
        ],
    )
    return point_id


async def delete_point(point_id: str) -> None:
    try:
        client = await get_client()
        await client.delete(
            collection_name=COLLECTION,
            points_selector=qm.PointIdsList(points=[point_id]),
        )
    except Exception as e:
        logger.warning("delete_point %s failed: %s", point_id, e)


async def search(
    vector: np.ndarray,
    top_k: int = 5,
    score_threshold: float = 0.55,
) -> List[dict]:
    """Cosine search. Returns [{point_id, score, person_id, photo_id}]."""
    client = await get_client()
    vec = _l2_normalize(vector.astype(np.float32))
    hits = await client.search(
        collection_name=COLLECTION,
        query_vector=vec.tolist(),
        limit=top_k,
        score_threshold=score_threshold,
    )
    return [
        {
            "point_id": h.id,
            "score": h.score,
            "person_id": (h.payload or {}).get("person_id"),
            "photo_id": (h.payload or {}).get("photo_id"),
        }
        for h in hits
    ]


async def health() -> bool:
    """Cheap is-up probe used by /api/ai/health."""
    if not _HAS_QDRANT or not settings.QDRANT_URL:
        return False
    try:
        client = await get_client()
        await client.get_collections()
        return True
    except Exception:
        return False
