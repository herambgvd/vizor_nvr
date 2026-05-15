"""
SSE event stream — /api/events/stream

Subscribers attach via EventSource and receive newline-delimited JSON
events as they fire. Replaces WebSocket for one-way event delivery —
SSE is simpler (HTTP/1.1 chunked), survives proxies better, and the
browser auto-reconnects.

Filter by scenario / event_type / camera_id via query params:
  GET /api/events/stream?scenario=people_counting&camera_id=...
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Optional, Set
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sse_starlette.sse import EventSourceResponse

from app.core.dependencies import get_current_user
from app.core.security import verify_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/events", tags=["Events"])


# ── In-process pub/sub ────────────────────────────────────────────────────
# Each subscriber gets an asyncio.Queue. publish_event() iterates all
# active queues and pushes the payload. Stale queues (full + slow
# consumer) are dropped to avoid back-pressure.

_SUBSCRIBERS: Set[asyncio.Queue] = set()
_MAX_QUEUE = 200


def publish_event(event: dict) -> None:
    """Fan a single event out to all SSE subscribers. Non-blocking —
    drops events for slow consumers rather than back-pressuring the
    bridge."""
    dead = []
    for q in _SUBSCRIBERS:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            dead.append(q)
        except Exception:
            dead.append(q)
    for q in dead:
        _SUBSCRIBERS.discard(q)


# ── SSE endpoint ──────────────────────────────────────────────────────────


async def _user_from_token_query(token: str = Query(...)) -> dict:
    """EventSource can't set Authorization headers, so SSE accepts the
    JWT as a `?token=` query param. Validates the same way as the Bearer
    dependency."""
    payload = verify_token(token, expected_type="access")
    if not payload or not payload.get("sub"):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or expired token"
        )
    return {
        "id": payload["sub"],
        "username": payload.get("username"),
        "email": payload.get("email"),
        "role": payload.get("role", "viewer"),
    }


@router.get("/stream")
async def stream_events(
    request: Request,
    scenario: Optional[str] = Query(None, description="Filter by scenario slug"),
    event_type: Optional[str] = Query(None, description="Filter by event_type"),
    camera_id: Optional[str] = Query(None, description="Filter by camera id"),
    user: dict = Depends(_user_from_token_query),
) -> EventSourceResponse:
    """Server-Sent Events stream of live AI events.

    Connection lifecycle:
      1. Client opens EventSource → 200 with text/event-stream
      2. Server emits `event: connected` once
      3. Server emits `event: ai_event` per match
      4. Periodic `event: ping` every 25s to keep proxies happy
      5. Client disconnects → queue cleaned up
    """
    q: asyncio.Queue = asyncio.Queue(maxsize=_MAX_QUEUE)
    _SUBSCRIBERS.add(q)

    async def _gen() -> AsyncIterator[dict]:
        try:
            # Handshake
            yield {
                "event": "connected",
                "data": json.dumps({"user": user.get("username")}),
            }

            while True:
                if await request.is_disconnected():
                    break

                try:
                    payload = await asyncio.wait_for(q.get(), timeout=25.0)
                except asyncio.TimeoutError:
                    # Keep-alive — proxies kill idle connections
                    yield {"event": "ping", "data": "{}"}
                    continue

                # Apply filters
                if scenario and payload.get("scenario") != scenario:
                    continue
                if event_type and payload.get("event_type") != event_type:
                    continue
                if camera_id and payload.get("camera_id") != camera_id:
                    continue

                yield {
                    "event": "ai_event",
                    "data": json.dumps(payload, default=str),
                }
        finally:
            _SUBSCRIBERS.discard(q)

    return EventSourceResponse(_gen())
