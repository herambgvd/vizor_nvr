#!/usr/bin/env python3
# =============================================================================
# One-shot migration: NVR-owned FRS gallery  ->  FRS plugin (own DB + Qdrant +
# photo volume).
#
# Run this ONCE, after the `frs` plugin + `frs-db` are up but BEFORE dropping the
# frs_* tables from the NVR database. It is idempotent (upsert by primary key),
# so a re-run is safe.
#
# What it moves:
#   - frs_groups, frs_persons, frs_photos, frs_attendance rows  (NVR PG -> FRS PG)
#   - photo files  (NVR DATA_PATH/frs/persons/...  ->  FRS DATA_PATH/persons/...)
#   - face vectors are re-derived from the copied photo bytes and upserted into
#     the plugin Qdrant collection (embedding_id is preserved from the row).
#
# Usage (from a host with access to both DBs + the NVR media volume), e.g.:
#   docker compose -f docker-compose.yml -f docker-compose.ai.yml run --rm \
#       -v <nvr_data_volume>:/nvr-data:ro \
#       -e NVR_DATABASE_URL=postgresql+psycopg2://nvr:***@db:5432/gvd_nvr \
#       -e NVR_FRS_PHOTO_ROOT=/nvr-data/frs \
#       frs python migrate_from_nvr.py
#
# Environment:
#   NVR_DATABASE_URL    source NVR Postgres (read-only use)
#   FRS_DATABASE_URL    target plugin Postgres (defaults to the app's env)
#   NVR_FRS_PHOTO_ROOT  source dir holding `persons/<id>/<photo>.jpg` (mount ro)
#   DATA_PATH           target plugin photo root (defaults to /data/frs)
#   QDRANT_URL / QDRANT_COLLECTION  target face index (defaults to app's env)
# =============================================================================
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

# Reuse the plugin's models, embedding + qdrant helpers so schema/vectors match.
import app as frs_app


NVR_DATABASE_URL = os.getenv("NVR_DATABASE_URL", "")
NVR_FRS_PHOTO_ROOT = Path(os.getenv("NVR_FRS_PHOTO_ROOT", "/nvr-data/frs"))


def _rows(engine, table: str) -> list[dict]:
    with engine.connect() as conn:
        try:
            res = conn.execute(text(f"SELECT * FROM {table}"))
        except Exception as exc:  # noqa: BLE001
            print(f"  ! could not read {table}: {exc}")
            return []
        cols = res.keys()
        return [dict(zip(cols, r)) for r in res.fetchall()]


def main() -> int:
    if not NVR_DATABASE_URL:
        print("NVR_DATABASE_URL is required (source NVR Postgres).")
        return 2

    print("[migrate] initialising plugin DB ...")
    frs_app._init_db()
    frs_app._qdrant()

    src = create_engine(NVR_DATABASE_URL, future=True)

    groups = _rows(src, "frs_groups")
    persons = _rows(src, "frs_persons")
    photos = _rows(src, "frs_photos")
    attendance = _rows(src, "frs_attendance")
    print(f"[migrate] source rows: groups={len(groups)} persons={len(persons)} "
          f"photos={len(photos)} attendance={len(attendance)}")

    target_root = frs_app.DATA_PATH
    copied_files = 0
    enrolled = 0

    with frs_app._session() as s:
        # Groups
        for g in groups:
            obj = s.get(frs_app.FRSGroup, g["id"]) or frs_app.FRSGroup(id=g["id"])
            for k in ("name", "group_type", "color_code", "description", "alert_sound",
                      "created_at", "updated_at"):
                if k in g:
                    setattr(obj, k, g[k])
            s.merge(obj)
        # Persons
        for p in persons:
            obj = s.get(frs_app.FRSPerson, p["id"]) or frs_app.FRSPerson(id=p["id"])
            for k in ("full_name", "external_id", "group_id", "category", "priority",
                      "enrollment_status", "photo_count", "enrolled_photo_count",
                      "thumbnail_key", "attributes", "created_at", "updated_at"):
                if k in p:
                    setattr(obj, k, p[k])
            s.merge(obj)
        # Photos (+ copy file, + re-enroll vector)
        for ph in photos:
            obj = s.get(frs_app.FRSPhoto, ph["id"]) or frs_app.FRSPhoto(id=ph["id"])
            for k in ("person_id", "thumbnail_key", "status", "embedding_id",
                      "quality_score", "liveness_score", "sharpness_score",
                      "error_code", "error", "created_at", "updated_at"):
                if k in ph:
                    setattr(obj, k, ph[k])
            # storage_key in NVR was "frs/persons/<pid>/<id>.jpg"; the plugin root
            # already IS the frs dir, so strip the leading "frs/".
            old_key = ph.get("storage_key") or ""
            new_key = old_key[4:] if old_key.startswith("frs/") else old_key
            obj.storage_key = new_key
            s.merge(obj)

            if new_key:
                src_file = NVR_FRS_PHOTO_ROOT / (old_key[4:] if old_key.startswith("frs/") else old_key)
                dst_file = target_root / new_key
                if src_file.exists():
                    dst_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_file, dst_file)
                    copied_files += 1
                    try:
                        vec = frs_app._face_embedding(dst_file.read_bytes())
                        frs_app._upsert_face(ph["id"], vec,
                                             {"person_id": ph.get("person_id"), "photo_id": ph["id"]})
                        enrolled += 1
                    except Exception as exc:  # noqa: BLE001
                        print(f"  ! enroll failed for photo {ph['id']}: {exc}")
                else:
                    print(f"  ! photo file missing: {src_file}")
        # Attendance
        for a in attendance:
            obj = s.get(frs_app.FRSAttendance, a["id"]) or frs_app.FRSAttendance(id=a["id"])
            for k in ("person_id", "camera_id", "day_key", "check_in_at", "check_out_at",
                      "sighting_type", "event_id", "created_at", "updated_at"):
                if k in a:
                    setattr(obj, k, a[k])
            s.merge(obj)
        s.commit()

    print(f"[migrate] done. photos copied={copied_files} vectors enrolled={enrolled}")
    print("[migrate] verify the plugin gallery, then drop frs_* tables from the NVR DB.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
