"""Shared Qdrant vector store base for vector scenarios.

One generic store backing every embedding scenario: FRS faces, Suspect-Search
ReID bodies, ANPR plate-embeddings. A plugin instantiates it with its own
collection name + vector size; the store owns connect / ensure / upsert / search
/ delete / count.

Same soft-fail philosophy as the FRS store and the Triton client:
`qdrant-client` is an OPTIONAL import (wrapped in try/except). If the lib is
missing or Qdrant is unreachable, every method no-ops — returns None / [] / 0 and
logs a warning — and `.available` is False. A vector plugin must degrade, not
crash, when its backing store blinks.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels
except Exception:  # noqa: BLE001 — qdrant-client is an optional extra
    QdrantClient = None
    qmodels = None

logger = logging.getLogger(__name__)


class QdrantStore:
    """Generic, fail-soft Qdrant collection wrapper.

        store = QdrantStore("http://qdrant:6333", "frs_gallery", vector_size=512)
        store.ensure_collection()
        store.upsert("id-1", embedding, {"person_id": 7})
        hits = store.search(query_vec, limit=10, score_threshold=0.35)

    Distance is "Cosine" (default), "Dot", or "Euclid" — matched to how the
    plugin's embeddings were trained."""

    def __init__(self, url: str, collection: str, vector_size: int,
                 distance: str = "Cosine", timeout: float = 10.0):
        self.url = url
        self.collection = collection
        self.vector_size = int(vector_size)
        self.distance = distance
        self.timeout = timeout
        self._client: Any | None = None
        self._connect_failed = False

    # ── connection ────────────────────────────────────────────────────────────
    def _conn(self) -> Any | None:
        """Lazy client connect. Soft-fails once (latches) so we don't hammer a
        dead Qdrant on every call."""
        if self._client is not None:
            return self._client
        if self._connect_failed or not self.url or QdrantClient is None or qmodels is None:
            return None
        try:
            self._client = QdrantClient(url=self.url, timeout=self.timeout)
            return self._client
        except Exception as exc:  # noqa: BLE001
            logger.warning("qdrant connect '%s' failed: %s", self.url, exc)
            self._connect_failed = True
            self._client = None
            return None

    @property
    def available(self) -> bool:
        """True if qdrant-client is installed and a connection opened."""
        return qmodels is not None and self._conn() is not None

    def _distance(self):
        """Map the string distance to a qmodels.Distance, defaulting to Cosine."""
        try:
            return getattr(qmodels.Distance, self.distance.upper(), qmodels.Distance.COSINE)
        except Exception:  # noqa: BLE001
            return qmodels.Distance.COSINE

    # ── schema ────────────────────────────────────────────────────────────────
    def ensure_collection(self) -> bool:
        """Create the collection if it doesn't exist (idempotent). Returns True if
        the collection exists/was created, False on any failure."""
        c = self._conn()
        if c is None or qmodels is None:
            return False
        try:
            existing = {col.name for col in c.get_collections().collections}
            if self.collection not in existing:
                c.create_collection(
                    collection_name=self.collection,
                    vectors_config=qmodels.VectorParams(
                        size=self.vector_size, distance=self._distance()),
                )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("qdrant ensure_collection '%s' failed: %s", self.collection, exc)
            return False

    # ── writes ────────────────────────────────────────────────────────────────
    def upsert(self, id: Any, vector: list[float], payload: dict) -> bool:
        """Upsert one point. Returns True on success, False on failure — callers
        that need consistency (enrollment) MUST check this."""
        c = self._conn()
        if c is None or qmodels is None:
            return False
        try:
            c.upsert(collection_name=self.collection,
                     points=[qmodels.PointStruct(id=id, vector=vector, payload=payload or {})])
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("qdrant upsert '%s' failed: %s", self.collection, exc)
            return False

    def upsert_batch(self, items: list[tuple[Any, list[float], dict]]) -> bool:
        """Upsert many points at once. `items` is [(id, vector, payload), ...].
        Returns True on success, False on failure."""
        if not items:
            return True  # nothing to do — trivially succeeds, no backend needed
        c = self._conn()
        if c is None or qmodels is None:
            return False
        try:
            points = [qmodels.PointStruct(id=i, vector=v, payload=p or {}) for i, v, p in items]
            c.upsert(collection_name=self.collection, points=points)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("qdrant upsert_batch '%s' failed: %s", self.collection, exc)
            return False

    # ── reads ─────────────────────────────────────────────────────────────────
    def search(self, vector: list[float], limit: int = 10,
               score_threshold: Optional[float] = None,
               query_filter: Any = None) -> list[dict]:
        """Nearest-neighbour search. Returns [{id, score, payload}, ...] sorted by
        score; [] on any failure. `query_filter` is a pre-built qmodels.Filter (or
        None). Uses query_points where available, falling back to the older
        search() API for older client/server pairs."""
        c = self._conn()
        if c is None:
            return []
        try:
            try:
                points = c.query_points(
                    collection_name=self.collection, query=vector, limit=limit,
                    query_filter=query_filter, score_threshold=score_threshold,
                    with_payload=True).points
            except AttributeError:
                points = c.search(
                    collection_name=self.collection, query_vector=vector, limit=limit,
                    query_filter=query_filter, score_threshold=score_threshold,
                    with_payload=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("qdrant search '%s' failed: %s", self.collection, exc)
            return []
        out: list[dict] = []
        for p in points:
            out.append({
                "id": getattr(p, "id", None),
                "score": float(getattr(p, "score", 0.0) or 0.0),
                "payload": dict(getattr(p, "payload", None) or {}),
            })
        return out

    def count(self) -> int:
        """Number of points in the collection, or 0 on failure."""
        c = self._conn()
        if c is None:
            return 0
        try:
            return int(c.count(collection_name=self.collection, exact=True).count)
        except Exception as exc:  # noqa: BLE001
            logger.warning("qdrant count '%s' failed: %s", self.collection, exc)
            return 0

    # ── deletes ───────────────────────────────────────────────────────────────
    def delete(self, ids: list) -> bool:
        """Delete points by id. Returns True on success, False on failure."""
        if not ids:
            return True  # nothing to do — trivially succeeds, no backend needed
        c = self._conn()
        if c is None or qmodels is None:
            return False
        try:
            c.delete(collection_name=self.collection,
                     points_selector=qmodels.PointIdsList(points=list(ids)))
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("qdrant delete '%s' failed: %s", self.collection, exc)
            return False
