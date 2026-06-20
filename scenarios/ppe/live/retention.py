"""Background data-retention sweeper (storage-limitation).

Periodically purges PPE events older than RETENTION_EVENT_DAYS along with their
snapshot files. 0 days disables purging.
"""
from __future__ import annotations

import threading
import time
from datetime import timedelta

from sqlalchemy import select

import config
from db import session
from db.models import PPEEvent
from schemas import utcnow

_started = False


def _snapshot_files(ev) -> list:
    """Resolve an event's stored snapshot JPEG paths (full + crop)."""
    out = []
    key = ev.snapshot_path or ""
    # snapshot_path = "/snapshot?key=live:<frame_id>"
    if "key=" in key:
        frame_id = key.split("key=", 1)[1].split(":", 1)[-1]
        if frame_id and "/" not in frame_id and ".." not in frame_id:
            base = config.DATA_PATH / "snapshots"
            out.append(base / f"{frame_id}.jpg")
            out.append(base / f"{frame_id}_crop.jpg")
    return out


def _purge_old_events() -> int:
    if config.RETENTION_EVENT_DAYS <= 0:
        return 0
    cutoff = utcnow() - timedelta(days=config.RETENTION_EVENT_DAYS)
    total = 0
    while True:
        with session() as s:
            rows = s.execute(
                select(PPEEvent).where(PPEEvent.triggered_at < cutoff)
                .limit(config.RETENTION_BATCH)
            ).scalars().all()
            if not rows:
                break
            for ev in rows:
                for p in _snapshot_files(ev):
                    try:
                        p.unlink(missing_ok=True)
                    except Exception:  # noqa: BLE001
                        pass
                s.delete(ev)
            s.commit()
            total += len(rows)
        if len(rows) < config.RETENTION_BATCH:
            break
    return total


def _loop() -> None:
    time.sleep(60)  # stagger first run so boot isn't hammered
    interval = max(1.0, config.RETENTION_SWEEP_HOURS) * 3600
    while True:
        try:
            purged = _purge_old_events()
            if purged:
                print(f"[ppe-retention] purged {purged} old events", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[ppe-retention] sweep error: {exc}", flush=True)
        time.sleep(interval)


def start_retention_sweeper() -> None:
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="ppe-retention").start()
    print("[ppe-retention] sweeper started", flush=True)
