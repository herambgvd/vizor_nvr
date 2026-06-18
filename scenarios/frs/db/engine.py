"""Database engine + session lifecycle for the FRS plugin's own Postgres."""
from __future__ import annotations

import time

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config import FRS_DATABASE_URL
from db.models import Base

_engine = None
_Session = None


def init_db(retries: int = 30) -> None:
    """Create the engine + tables, retrying while Postgres boots."""
    global _engine, _Session
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            _engine = create_engine(FRS_DATABASE_URL, pool_pre_ping=True, future=True)
            Base.metadata.create_all(_engine)
            _Session = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
            print("[frs] database ready", flush=True)
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            print(f"[frs] db init attempt {attempt} failed: {exc}", flush=True)
            time.sleep(min(2 * attempt, 15))
    raise RuntimeError(f"frs db init failed: {last_exc}")


def db_ready() -> bool:
    return _Session is not None


def session():
    if _Session is None:
        raise HTTPException(503, "database not ready")
    return _Session()
