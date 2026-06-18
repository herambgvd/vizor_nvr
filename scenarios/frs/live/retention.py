"""Background data-retention sweeper (GDPR storage-limitation).

Periodically purges FRS events older than RETENTION_EVENT_DAYS along with their
snapshot files and forensic snapshot vectors, and retries any pending
vector-erasure recorded by the right-to-erasure path. Enrolled gallery
photos/persons are never touched — only time-series sightings/events.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

from sqlalchemy import select

import config
from db import session
from db.models import FRSEvent
from deps import purge_snapshot_files
from deps.purge import reconcile_vector_erasure
from schemas import utcnow
from qdrant import store as qdrant_store

_started = False


def _purge_old_events() -> int:
    if config.RETENTION_EVENT_DAYS <= 0:
        return 0
    cutoff = utcnow() - timedelta(days=config.RETENTION_EVENT_DAYS)
    total = 0
    while True:
        with session() as s:
            rows = s.execute(
                select(FRSEvent).where(FRSEvent.triggered_at < cutoff)
                .limit(config.RETENTION_BATCH)
            ).scalars().all()
            if not rows:
                break
            purge_snapshot_files(rows)                       # snapshot JPEGs
            for ev in rows:
                # Drop the forensic snapshot vector (point id == event id).
                qdrant_store.delete_by("event_id", str(ev.id),
                                       collection=qdrant_store.SNAPSHOTS_COLLECTION)
                s.delete(ev)
            s.commit()
            total += len(rows)
        if len(rows) < config.RETENTION_BATCH:
            break
    return total


def _loop() -> None:
    # Stagger first run so boot isn't hammered.
    time.sleep(60)
    interval = max(1.0, config.RETENTION_SWEEP_HOURS) * 3600
    while True:
        try:
            purged = _purge_old_events()
            cleared = reconcile_vector_erasure()
            if purged or cleared:
                print(f"[frs-retention] purged {purged} old events, "
                      f"reconciled {cleared} pending erasures", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[frs-retention] sweep error: {exc}", flush=True)
        time.sleep(interval)


def start_retention_sweeper() -> None:
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="frs-retention").start()
    print("[frs-retention] sweeper started", flush=True)
