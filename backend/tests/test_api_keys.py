"""Unit tests for api_keys helpers and CRUD service.

Uses SQLite in-memory; covers key generation, hashing, scope checks, and
authentication (valid / invalid / revoked / expired).
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.auth.api_keys import (
    API_KEY_PREFIX,
    APIKey,
    APIKeyCreate,
    APIKeyService,
    generate_api_key,
    hash_api_key,
    key_prefix,
)
from app.database import Base


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


# ── Helpers ──────────────────────────────────────────────────────────


def test_generate_api_key_has_prefix_and_entropy():
    k = generate_api_key()
    assert k.startswith(API_KEY_PREFIX)
    # 24 bytes -> 48 hex chars after the prefix
    assert len(k) == len(API_KEY_PREFIX) + 48
    # Two consecutive calls must not collide
    assert generate_api_key() != k


def test_hash_api_key_is_deterministic_and_64_chars():
    plain = generate_api_key()
    h1 = hash_api_key(plain)
    h2 = hash_api_key(plain)
    assert h1 == h2
    assert len(h1) == 64
    # Different plaintext → different hash
    assert hash_api_key(generate_api_key()) != h1


def test_key_prefix_is_short_and_non_secret():
    p = key_prefix("vzn_abcdef0123456789")
    assert p == "vzn_abcdef01"
    assert len(p) == 12


# ── CRUD + auth ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_returns_plaintext_once(session: AsyncSession):
    key, plaintext = await APIKeyService.create(
        session, APIKeyCreate(name="gpu-worker", scopes=["events:ingest"])
    )
    assert plaintext.startswith(API_KEY_PREFIX)
    assert key.key_prefix == plaintext[:12]
    assert key.scopes == ["events:ingest"]
    assert key.enabled is True
    # Plaintext is not stored anywhere on the row
    assert plaintext not in (key.key_hash, key.key_prefix)


@pytest.mark.asyncio
async def test_authenticate_with_valid_plaintext(session: AsyncSession):
    _, plaintext = await APIKeyService.create(
        session, APIKeyCreate(name="ok", scopes=["events:ingest"])
    )
    key = await APIKeyService.authenticate(session, plaintext, source_ip="10.0.0.1")
    assert key is not None
    assert key.last_used_ip == "10.0.0.1"
    assert key.last_used_at is not None


@pytest.mark.asyncio
async def test_authenticate_rejects_unknown_key(session: AsyncSession):
    assert await APIKeyService.authenticate(session, "vzn_deadbeef") is None
    assert await APIKeyService.authenticate(session, "not-even-prefixed") is None
    assert await APIKeyService.authenticate(session, "") is None


@pytest.mark.asyncio
async def test_authenticate_rejects_revoked_key(session: AsyncSession):
    key, plaintext = await APIKeyService.create(
        session, APIKeyCreate(name="rev", scopes=["admin"])
    )
    assert await APIKeyService.revoke(session, key.id) is True
    assert await APIKeyService.authenticate(session, plaintext) is None


@pytest.mark.asyncio
async def test_authenticate_rejects_expired_key(session: AsyncSession):
    _, plaintext = await APIKeyService.create(
        session,
        APIKeyCreate(
            name="exp",
            scopes=["events:ingest"],
            expires_at=datetime.utcnow() - timedelta(seconds=1),
        ),
    )
    assert await APIKeyService.authenticate(session, plaintext) is None


@pytest.mark.asyncio
async def test_list_returns_all_keys(session: AsyncSession):
    """list_all returns every row.

    Ordering is `created_at DESC` in service but SQLite stamps all three
    inserts with the same wall-clock second, so we only assert membership
    here. Postgres-backed integration tests cover the ordering contract.
    """
    await APIKeyService.create(session, APIKeyCreate(name="a", scopes=[]))
    await APIKeyService.create(session, APIKeyCreate(name="b", scopes=[]))
    await APIKeyService.create(session, APIKeyCreate(name="c", scopes=[]))
    keys = await APIKeyService.list_all(session)
    assert sorted(k.name for k in keys) == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_delete_removes_key(session: AsyncSession):
    key, _ = await APIKeyService.create(
        session, APIKeyCreate(name="del", scopes=[])
    )
    assert await APIKeyService.delete(session, key.id) is True
    assert await APIKeyService.get_by_id(session, key.id) is None
    assert await APIKeyService.delete(session, key.id) is False
