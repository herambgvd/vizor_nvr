"""
Counts writer — buffer + flush per-zone in/out/occupancy/alert counts.

Bridge feeds events here (one call per DeepStream event). We aggregate
into per-minute buckets and upsert into `people_counts` every 30s. This
avoids hammering Postgres on high-throughput cameras.

Thread-safe via single asyncio task. No external queue.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_maker

logger = logging.getLogger(__name__)


def _minute_bucket(ts: Optional[datetime] = None) -> datetime:
    """Return naive UTC minute-aligned bucket. DB columns are naive
    timestamps so we strip tzinfo here to keep asyncpg happy."""
    ts = ts or datetime.utcnow()
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts.replace(second=0, microsecond=0)


# Buffer key = (camera_id, zone_id, bucket_ts). Value = aggregate dict.
_BUFFER: Dict[Tuple[str, str, datetime], Dict[str, int]] = defaultdict(
    lambda: {"in_count": 0, "out_count": 0, "occupancy": 0, "crowd_alerts": 0}
)
_LOCK = asyncio.Lock()


async def record_line_crossing(camera_id: str, zone_id: str, direction: str):
    """Direction is the resolved label ('in'/'out') or zone's a/b label."""
    key = (camera_id, zone_id, _minute_bucket())
    async with _LOCK:
        agg = _BUFFER[key]
        if direction == "in":
            agg["in_count"] += 1
        elif direction == "out":
            agg["out_count"] += 1


async def record_occupancy(camera_id: str, zone_id: str, count: int):
    """Crowd zone — store the max occupancy seen this minute bucket."""
    key = (camera_id, zone_id, _minute_bucket())
    async with _LOCK:
        agg = _BUFFER[key]
        if count > agg["occupancy"]:
            agg["occupancy"] = count


async def record_crowd_alert(camera_id: str, zone_id: str):
    key = (camera_id, zone_id, _minute_bucket())
    async with _LOCK:
        _BUFFER[key]["crowd_alerts"] += 1


async def _flush_once(db: AsyncSession) -> int:
    """Drain buffer to DB. Returns number of (zone, bucket) rows written."""
    async with _LOCK:
        if not _BUFFER:
            return 0
        snapshot = dict(_BUFFER)
        _BUFFER.clear()

    # Upsert each bucket — `in_count` and `out_count` ADD on conflict
    # (so multiple flushes inside the same minute merge correctly).
    # `occupancy` is MAX. `crowd_alerts` is SUM.
    written = 0
    for (camera_id, zone_id, bucket_ts), agg in snapshot.items():
        await db.execute(
            text(
                """
                INSERT INTO people_counts
                  (bucket_ts, zone_id, camera_id, in_count, out_count,
                   occupancy, crowd_alerts)
                VALUES
                  (:bucket_ts, :zone_id, :camera_id, :in_count, :out_count,
                   :occupancy, :crowd_alerts)
                ON CONFLICT (zone_id, bucket_ts) DO UPDATE SET
                  in_count    = people_counts.in_count    + EXCLUDED.in_count,
                  out_count   = people_counts.out_count   + EXCLUDED.out_count,
                  occupancy   = GREATEST(people_counts.occupancy, EXCLUDED.occupancy),
                  crowd_alerts= people_counts.crowd_alerts + EXCLUDED.crowd_alerts
                """
            ),
            {
                "bucket_ts": bucket_ts,
                "zone_id": zone_id,
                "camera_id": camera_id,
                **agg,
            },
        )
        written += 1
    await db.commit()
    return written


_TASK: Optional[asyncio.Task] = None
_RUNNING = False


async def _loop(interval: float):
    global _RUNNING
    while _RUNNING:
        try:
            async with async_session_maker() as db:
                n = await _flush_once(db)
                if n:
                    logger.info(f"counts_writer flushed {n} buckets")
        except Exception as e:
            logger.error(f"counts_writer flush error: {e}")
        await asyncio.sleep(interval)


async def start(interval: float = 30.0):
    """Start the background flusher. Idempotent."""
    global _TASK, _RUNNING
    if _RUNNING:
        return
    _RUNNING = True
    _TASK = asyncio.create_task(_loop(interval), name="counts_writer")
    logger.info(f"counts_writer started (interval={interval}s)")


async def stop():
    """Stop + drain the buffer one last time."""
    global _TASK, _RUNNING
    _RUNNING = False
    if _TASK:
        _TASK.cancel()
        try:
            await _TASK
        except asyncio.CancelledError:
            pass
        _TASK = None
    try:
        async with async_session_maker() as db:
            await _flush_once(db)
    except Exception as e:
        logger.warning(f"counts_writer final flush error: {e}")
    logger.info("counts_writer stopped")
