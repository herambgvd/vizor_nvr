# =============================================================================
# DB Retry Helper — exponential back-off for transient database errors
# =============================================================================
# Use with_db_retry() to wrap any async DB operation that should survive
# brief Postgres unavailability (recovery mode, failover, restart).
# =============================================================================

import asyncio
import logging
from typing import Callable

from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

logger = logging.getLogger(__name__)

_TRANSIENT_MARKERS = (
    "recovery mode",
    "not yet accepting",
    "server closed",
    "connection reset",
    "connection refused",
    "connection timed out",
    "remaining connection slots",
    "the connection is closed",
    "ssl connection has been closed",
)


def _is_transient(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _TRANSIENT_MARKERS)


async def with_db_retry(
    operation: Callable,
    *,
    max_attempts: int = 8,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    op_name: str = "db_op",
):
    """
    Retry *operation* (a zero-arg async callable) on transient SQLAlchemy
    errors with exponential back-off.

    Non-transient errors and the final attempt always re-raise.
    Log levels:
      - attempt 1-2 → DEBUG  (connection flap, almost never interesting)
      - attempt 3+  → WARNING (sustained outage, worth seeing once)
    """
    delay = initial_delay
    for attempt in range(1, max_attempts + 1):
        try:
            return await operation()
        except (OperationalError, InterfaceError, DBAPIError) as exc:
            if not _is_transient(exc) or attempt == max_attempts:
                raise
            level = logging.DEBUG if attempt < 3 else logging.WARNING
            logger.log(
                level,
                "%s: transient DB error attempt %d/%d (%s); retrying in %.1fs",
                op_name,
                attempt,
                max_attempts,
                type(exc).__name__,
                delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)


async def wait_for_db(
    *,
    timeout: float = 60.0,
    poll_interval: float = 2.0,
    op_name: str = "db_startup_gate",
) -> None:
    """
    Block until a simple ``SELECT 1`` succeeds or *timeout* seconds pass.
    Intended as a startup gate in lifespan so background services don't
    start ticking into a non-ready database.
    """
    from sqlalchemy import text
    from app.database import async_session_maker

    deadline = asyncio.get_event_loop().time() + timeout
    attempt = 0
    while True:
        attempt += 1
        try:
            async with async_session_maker() as db:
                await db.execute(text("SELECT 1"))
            if attempt > 1:
                logger.info("%s: database ready after %d attempt(s)", op_name, attempt)
            return
        except Exception as exc:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise RuntimeError(
                    f"{op_name}: database not ready after {timeout}s — last error: {exc}"
                ) from exc
            sleep_for = min(poll_interval, remaining)
            level = logging.DEBUG if attempt < 3 else logging.WARNING
            logger.log(
                level,
                "%s: DB not ready (attempt %d, %.0fs remaining): %s; retrying in %.1fs",
                op_name,
                attempt,
                remaining,
                type(exc).__name__,
                sleep_for,
            )
            await asyncio.sleep(sleep_for)
