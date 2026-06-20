"""Database engine + session lifecycle for the PPE plugin's own Postgres.

Schema is owned by Alembic migrations (db/migrations), NOT create_all — so a
long-lived install upgrades cleanly when models gain columns. On boot we run
`alembic upgrade head`; if the DB pre-dates Alembic (tables already present, no
alembic_version), we stamp the baseline and continue."""
from __future__ import annotations

import os
import time

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from config import PPE_DATABASE_URL
from db.models import Base  # noqa: F401  (imported so metadata is populated)

_engine = None
_Session = None

_BASELINE_REV = "ppe_0001_baseline"
_ALEMBIC_INI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "alembic.ini")


def _run_migrations(engine) -> None:
    cfg = Config(_ALEMBIC_INI)
    cfg.set_main_option("sqlalchemy.url", PPE_DATABASE_URL)
    insp = inspect(engine)
    has_tables = "ppe_events" in insp.get_table_names()
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    if has_tables and current is None:
        # Pre-Alembic install: adopt the baseline without re-creating tables.
        command.stamp(cfg, _BASELINE_REV)
        print("[ppe] stamped existing schema to baseline", flush=True)
    command.upgrade(cfg, "head")


def init_db(retries: int = 30) -> None:
    """Create the engine, run Alembic migrations, retry while Postgres boots."""
    global _engine, _Session
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            _engine = create_engine(PPE_DATABASE_URL, pool_pre_ping=True, future=True)
            _run_migrations(_engine)
            _Session = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
            print("[ppe] database ready", flush=True)
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            print(f"[ppe] db init attempt {attempt} failed: {exc}", flush=True)
            time.sleep(min(2 * attempt, 15))
    raise RuntimeError(f"ppe db init failed: {last_exc}")


def db_ready() -> bool:
    return _Session is not None


def session():
    if _Session is None:
        raise HTTPException(503, "database not ready")
    return _Session()
