"""Redis stream PEL recovery helpers.

A consumer group leaves messages in the Pending-Entries List (PEL) when
the consumer crashes mid-handle. Without periodic recovery they live
there forever and never reach a different consumer. This module gives
the NVR worker two small helpers:

  * :func:`xautoclaim_pending` — atomically claim entries idle longer
    than `min_idle_ms` to the current consumer. Run periodically from
    the consume loop.
  * :func:`xack_safe` — XACK that swallows transient errors so a
    failed ack doesn't poison the consumer.
"""
from __future__ import annotations

import logging
from typing import Iterable

logger = logging.getLogger("vizor.worker.stream_recovery")


async def xautoclaim_pending(
    redis,
    stream: str,
    group: str,
    consumer: str,
    *,
    min_idle_ms: int = 60_000,
    count: int = 32,
) -> list[tuple[str, dict]]:
    """Claim up to ``count`` PEL entries idle ≥ min_idle_ms and return
    them as `(message_id, fields)` tuples."""
    try:
        _next_id, claimed, _deleted = await redis.xautoclaim(
            stream, group, consumer, min_idle_time=min_idle_ms, count=count,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[stream_recovery] xautoclaim %s: %s", stream, e)
        return []
    out: list[tuple[str, dict]] = []
    for entry in claimed or []:
        try:
            msg_id, fields = entry
            out.append((msg_id, fields))
        except Exception:
            continue
    return out


async def xack_safe(redis, stream: str, group: str, msg_id: str) -> None:
    """XACK that never raises. Failure is logged at warning and
    swallowed — the message will resurface via XAUTOCLAIM later."""
    try:
        await redis.xack(stream, group, msg_id)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "[stream_recovery] xack failed stream=%s id=%s: %s",
            stream, msg_id, e,
        )


async def xack_batch(
    redis, stream: str, group: str, msg_ids: Iterable[str],
) -> int:
    """XACK a batch; return count of successfully-acked ids."""
    ids = [m for m in msg_ids if m]
    if not ids:
        return 0
    try:
        await redis.xack(stream, group, *ids)
        return len(ids)
    except Exception as e:  # noqa: BLE001
        logger.warning("[stream_recovery] xack batch failed: %s — fallback", e)
        acked = 0
        for m in ids:
            try:
                await redis.xack(stream, group, m)
                acked += 1
            except Exception:
                pass
        return acked
