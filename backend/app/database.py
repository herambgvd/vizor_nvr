# =============================================================================
# Database Engine, Session, Base  (PostgreSQL / asyncpg only)
# =============================================================================
# FastAPI uses asyncpg for all runtime queries.
# Alembic uses psycopg2 (sync) separately — run `alembic upgrade head` before
# starting the server.  The server never runs migrations on startup.
# =============================================================================

import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import text

from app.config import settings

logger = logging.getLogger(__name__)

if not settings.DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Add it to backend/.env — "
        "e.g. postgresql+asyncpg://user:pass@localhost:5432/gvd_nvr"
    )

# ---------------------------------------------------------------------------
# Async engine (asyncpg for production, aiosqlite for tests)
# ---------------------------------------------------------------------------
# Pool-tuning kwargs (pool_size, max_overflow, etc.) are only valid for
# server-side pooling dialects such as asyncpg/psycopg.  SQLite uses
# StaticPool and rejects those kwargs, so we only pass them for non-SQLite
# URLs (detected by the scheme prefix).
_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

_engine_kwargs: dict = {
    "echo": False,
    "future": True,
}
if not _is_sqlite:
    _engine_kwargs.update(
        {
            "pool_pre_ping": True,
            "pool_size": 40,
            "max_overflow": 60,
            "pool_timeout": 30,
            "pool_recycle": 1800,
        }
    )

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
async_session_maker = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False,
    autoflush=False, autocommit=False,
)

Base = declarative_base()


async def init_db() -> None:
    """
    Verify the database is reachable.  Schema management is handled
    exclusively by Alembic — run `alembic upgrade head` before starting
    the server for the first time or after adding new migrations.
    """
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))

    safe = settings.DATABASE_URL.split("@")[-1]
    logger.info(f"Database ready ({safe})")


async def get_db():
    """FastAPI dependency — yields an AsyncSession."""
    async with async_session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
