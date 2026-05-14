# =============================================================================
# Graceful Shutdown Coordinator
#
# Tracks in-flight HTTP requests so the FastAPI lifespan shutdown hook
# can wait for them to drain before exiting. Without this, SIGTERM
# kills mid-request handlers — clients see connection resets, ARQ jobs
# leak to a half-committed state.
#
# Usage:
#   1. Install InFlightRequestsMiddleware in main.py
#   2. In lifespan shutdown, call `await wait_for_drain(timeout=30)`
#
# At the same time, the middleware refuses NEW requests when a drain
# is in progress so SIGTERM hosts stop accepting work. Returns 503
# with a Retry-After header.
# =============================================================================

import asyncio
import logging
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


logger = logging.getLogger(__name__)


# Module-level state — process-singleton.
_in_flight: int = 0
_lock = asyncio.Lock()
_drain_event = asyncio.Event()
_draining: bool = False
_zero_inflight_event = asyncio.Event()
_zero_inflight_event.set()  # No in-flight at startup


async def _bump(delta: int) -> None:
    global _in_flight
    async with _lock:
        _in_flight += delta
        if _in_flight == 0:
            _zero_inflight_event.set()
        else:
            _zero_inflight_event.clear()


class InFlightRequestsMiddleware(BaseHTTPMiddleware):
    """Track active requests + refuse new ones during drain."""

    # Paths that bypass the drain (health checks must keep responding so
    # the orchestrator knows when we've finished shedding load).
    PASSTHROUGH_PATHS = ("/api/health", "/metrics")

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        passthrough = any(path.startswith(p) for p in self.PASSTHROUGH_PATHS)

        if _draining and not passthrough:
            return JSONResponse(
                status_code=503,
                content={"detail": "Server is shutting down, retry shortly"},
                headers={"Retry-After": "5", "Connection": "close"},
            )

        if not passthrough:
            await _bump(+1)
        try:
            return await call_next(request)
        finally:
            if not passthrough:
                await _bump(-1)


def start_drain() -> None:
    """Flip the drain flag. New requests get 503 from now on."""
    global _draining
    _draining = True
    _drain_event.set()
    logger.info("Drain initiated — refusing new requests")


async def wait_for_drain(timeout: float = 30.0) -> bool:
    """Block until in-flight count reaches zero or timeout expires.
    Returns True if drained cleanly, False on timeout."""
    if _in_flight == 0:
        return True
    try:
        await asyncio.wait_for(_zero_inflight_event.wait(), timeout=timeout)
        logger.info("Drain complete — 0 in-flight requests")
        return True
    except asyncio.TimeoutError:
        logger.warning(
            "Drain timeout — %d requests still in flight after %.0fs",
            _in_flight, timeout,
        )
        return False


def in_flight_count() -> int:
    return _in_flight


def is_draining() -> bool:
    return _draining
