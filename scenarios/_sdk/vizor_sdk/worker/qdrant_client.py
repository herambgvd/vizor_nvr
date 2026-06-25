"""Single-tenant async Qdrant wrapper (ported from vizor-gpu).

The NVR worker is single-tenant, so collections are named purely from the
use-case: `vizor_{use_case}_faces` (or an explicit name passed in). The old
tenant-scoped `t_{tenant}_{use_case}` naming is gone, and every method drops
its `tenant_id` parameter.

Carries the optional circuit breaker through from vizor-gpu: a Qdrant outage
short-circuits via `breaker.call_async(...)` instead of hammering the backend.

`qdrant-client` is imported defensively (matches the rest of the NVR SDK) so an
environment without the extra can still import this module.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable

try:
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.http import models as qmodels
except Exception:  # noqa: BLE001 — qdrant-client is an optional extra
    AsyncQdrantClient = None  # type: ignore[assignment]
    qmodels = None  # type: ignore[assignment]

from .circuit_breaker import CircuitBreaker, CircuitOpenError  # noqa: F401

logger = logging.getLogger("vizor.worker.qdrant")


_SAFE = re.compile(r"[^a-z0-9_]")


def _safe_part(s: str) -> str:
    s2 = _SAFE.sub("_", s.lower()).strip("_")
    if not s2:
        raise ValueError(f"invalid identifier: {s!r}")
    return s2


class QdrantClientWrapper:
    """Single-tenant, per-use-case vector collections."""

    def __init__(self, url: str, api_key: str | None = None, breaker: CircuitBreaker | None = None):
        if AsyncQdrantClient is None:
            raise RuntimeError("qdrant-client not installed — vector store unavailable")
        self.url = url
        self.api_key = api_key
        self._client = AsyncQdrantClient(url=url, api_key=api_key)
        self._breaker = breaker
        # Collections we've already confirmed exist this process — lets the
        # steady-state path skip the get_collections() round-trip.
        self._ensured: set[str] = set()

    async def _guard(self, coro_fn, *args, **kwargs):
        if self._breaker is None:
            return await coro_fn(*args, **kwargs)
        return await self._breaker.call_async(coro_fn, *args, **kwargs)

    @staticmethod
    def collection_name(use_case: str) -> str:
        return f"vizor_{_safe_part(use_case)}_faces"

    async def ensure_collection(
        self,
        use_case: str,
        vector_size: int,
        distance: "qmodels.Distance | None" = None,
    ) -> str:
        """Create the collection if missing. Returns the collection name.

        Cached per-process: once a collection is known to exist we skip the
        get_collections() round-trip entirely (the steady-state snapshot path
        becomes a single guarded upsert). Routed through the breaker so a
        Qdrant outage short-circuits instead of hammering it per snapshot.

        `use_case` may also be a fully-qualified collection name; it is run
        through `collection_name()` unless it already looks resolved.
        """
        if distance is None:
            distance = qmodels.Distance.COSINE
        name = self.collection_name(use_case)
        if name in self._ensured:
            return name
        await self._guard(self._ensure_inner, name, vector_size, distance)
        self._ensured.add(name)
        return name

    async def _ensure_inner(self, name, vector_size, distance) -> None:
        existing = await self._client.get_collections()
        if any(c.name == name for c in existing.collections):
            return
        await self._client.create_collection(
            collection_name=name,
            vectors_config=qmodels.VectorParams(size=vector_size, distance=distance),
        )
        logger.info("[qdrant] created collection %s (size=%s)", name, vector_size)

    async def _upsert_inner(self, name: str, q_points: list) -> int:
        await self._client.upsert(collection_name=name, points=q_points)
        return len(q_points)

    async def upsert_vectors(
        self,
        use_case: str,
        points: Iterable[dict[str, Any]],
    ) -> int:
        """Upsert points of shape {id, vector, payload}. Returns count."""
        name = self.collection_name(use_case)
        q_points = [
            qmodels.PointStruct(
                id=p["id"],
                vector=p["vector"],
                payload=p.get("payload", {}),
            )
            for p in points
        ]
        if not q_points:
            return 0
        return await self._guard(self._upsert_inner, name, q_points)

    async def _search_inner(self, name, query_vector, top_k, qfilter):
        resp = await self._client.query_points(
            collection_name=name,
            query=query_vector,
            limit=top_k,
            query_filter=qfilter,
            with_payload=True,
        )
        return [
            {"id": h.id, "score": h.score, "payload": h.payload or {}}
            for h in resp.points
        ]

    async def search(
        self,
        use_case: str,
        query_vector: list[float],
        top_k: int = 10,
        filter: "qmodels.Filter | dict | None" = None,
    ) -> list[dict[str, Any]]:
        """Vector similarity search. Returns list of {id, score, payload}."""
        name = self.collection_name(use_case)
        qfilter: "qmodels.Filter | None" = None
        if isinstance(filter, qmodels.Filter):
            qfilter = filter
        elif isinstance(filter, dict):
            qfilter = qmodels.Filter(**filter)
        return await self._guard(self._search_inner, name, query_vector, top_k, qfilter)

    async def delete_by_payload(
        self, use_case: str, key: str, value: str
    ) -> bool:
        """Delete every point whose payload[key] == value. Idempotent."""
        name = self.collection_name(use_case)
        flt = qmodels.Filter(
            must=[qmodels.FieldCondition(key=key, match=qmodels.MatchValue(value=value))]
        )
        try:
            await self._client.delete(
                collection_name=name,
                points_selector=qmodels.FilterSelector(filter=flt),
            )
            return True
        except Exception as e:
            logger.warning("[qdrant] delete_by_payload %s=%s: %s", key, value, e)
            return False

    async def drop_collection(self, use_case: str) -> bool:
        """Delete the use-case collection."""
        name = self.collection_name(use_case)
        try:
            await self._client.delete_collection(collection_name=name)
            logger.info("[qdrant] dropped collection %s", name)
            return True
        except Exception as e:
            logger.warning("[qdrant] drop %s failed: %s", name, e)
            return False

    async def close(self) -> None:
        try:
            await self._client.close()
        except Exception:
            pass
