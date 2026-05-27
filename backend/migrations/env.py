# =============================================================================
# Alembic Migration Environment
# =============================================================================
# Uses a standard synchronous psycopg2 connection — the correct way to run
# Alembic. FastAPI uses asyncpg at runtime; Alembic is a CLI tool that runs
# outside the event loop and must use a sync driver.
#
# Run migrations manually before starting the server:
#   alembic upgrade head
# =============================================================================

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# ---------------------------------------------------------------------------
# Add app to path so we can import models
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ---------------------------------------------------------------------------
# Import all models to ensure they're registered with Base.metadata
# ---------------------------------------------------------------------------
from app.database import Base
from app.config import settings

# Import all model modules so they register with Base
from app.auth import models as auth_models
from app.auth import api_keys as auth_api_keys  # Phase 8 — m2m API keys
from app.cameras import models as camera_models
from app.recordings import models as recording_models
from app.storage import models as storage_models
from app.settings import models as settings_models
from app.audit import models as audit_models
from app.notifications import models as notification_models
from app.events import models as event_models  # Phase 8 — AI columns
# aggregates.py removed in AI-removal migration (20260527_000000)
# app.ai removed in AI-removal refactor

# ---------------------------------------------------------------------------
# Alembic Config
# ---------------------------------------------------------------------------
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_sync_url() -> str:
    """Return a sync-driver URL for Alembic.
    Converts asyncpg → psycopg2, aiosqlite → pysqlite."""
    url = settings.DATABASE_URL
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    elif url.startswith("sqlite+aiosqlite://"):
        url = url.replace("sqlite+aiosqlite://", "sqlite://", 1)
    return url


def run_migrations_offline() -> None:
    """Generate SQL without connecting — useful for audit/review."""
    context.configure(
        url=get_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect with psycopg2 and apply migrations synchronously."""
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = get_sync_url()

    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
