"""Shared data-erasure helpers (right-to-erasure + retention).

Biometric data lives in three places — Postgres rows, on-disk JPEGs, and the
Qdrant snapshots collection — so a real delete must reach all three. Both the
person-delete path and the retention sweeper use these.
"""
from __future__ import annotations

import os

import config
from qdrant import store as qdrant_store


def purge_snapshot_files(events) -> None:
    """Best-effort delete of each event's live snapshot files (full + face crop)."""
    for ev in events:
        attrs = getattr(ev, "attributes", None) or {}
        for path in (getattr(ev, "snapshot_path", None), attrs.get("face_snapshot")):
            if not path or "key=live:" not in str(path):
                continue
            key = str(path).split("key=live:", 1)[1]
            f = config.DATA_PATH / "snapshots" / f"{key}.jpg"
            try:
                if f.exists():
                    os.remove(f)
            except OSError:
                pass


def purge_person_biometrics(s, person_id: str) -> dict:
    """Erase EVERY trace of a person's biometrics (GDPR/BIPA right-to-erasure):
    gallery vectors, live-sighting vectors, snapshot files, events, attendance.
    `s` is an open SQLAlchemy session; the caller commits. Returns a count summary."""
    from sqlalchemy import select
    from db.models import FRSEvent, FRSAttendance, FRSPhoto

    # Delete snapshot files referenced by this person's events first (need the rows).
    events = s.execute(select(FRSEvent).where(FRSEvent.person_id == person_id)).scalars().all()
    purge_snapshot_files(events)
    n_events = len(events)
    for ev in events:
        s.delete(ev)
    n_att = 0
    for a in s.execute(select(FRSAttendance).where(FRSAttendance.person_id == person_id)).scalars().all():
        s.delete(a); n_att += 1
    n_photos = 0
    for ph in s.execute(select(FRSPhoto).where(FRSPhoto.person_id == person_id)).scalars().all():
        s.delete(ph); n_photos += 1

    # Vectors: gallery (main + augments) AND the forensic snapshots collection.
    ok_g = qdrant_store.delete_by("person_id", person_id)
    ok_s = qdrant_store.delete_by("person_id", person_id, collection=qdrant_store.SNAPSHOTS_COLLECTION)
    if not (ok_g and ok_s):
        # Vector store unreachable — record the orphan so a reconcile sweep can
        # finish the erasure. Erasure is NOT complete until vectors are gone.
        _record_pending_vector_erasure(person_id)
    return {"events": n_events, "attendance": n_att, "photos": n_photos,
            "vectors_deleted": bool(ok_g and ok_s)}


# Pending-erasure ledger: person_ids whose DB/files are gone but whose vectors
# could not be deleted (Qdrant down). The reconcile sweep retries these.
_PENDING_FILE = None


def _pending_path():
    return config.DATA_PATH / "pending_vector_erasure.txt"


def _record_pending_vector_erasure(person_id: str) -> None:
    try:
        p = _pending_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as f:
            f.write(person_id + "\n")
    except OSError:
        pass


def reconcile_vector_erasure() -> int:
    """Retry vector deletion for any person recorded as pending. Returns the
    number successfully cleared. Safe to call on a schedule."""
    p = _pending_path()
    if not p.exists():
        return 0
    try:
        pending = [ln.strip() for ln in p.read_text().splitlines() if ln.strip()]
    except OSError:
        return 0
    still: list[str] = []
    cleared = 0
    for pid in dict.fromkeys(pending):  # dedupe, keep order
        ok_g = qdrant_store.delete_by("person_id", pid)
        ok_s = qdrant_store.delete_by("person_id", pid, collection=qdrant_store.SNAPSHOTS_COLLECTION)
        if ok_g and ok_s:
            cleared += 1
        else:
            still.append(pid)
    try:
        if still:
            p.write_text("\n".join(still) + "\n")
        else:
            p.unlink(missing_ok=True)
    except OSError:
        pass
    return cleared
