"""
Integration test fixtures for GVD NVR.

Uses a real PostgreSQL database (via TEST_DATABASE_URL) but mocks:
- FFmpeg subprocess calls (no actual video processes)
- go2rtc HTTP client (httpx mocking)
- ONVIF Zeep client

This gives us realistic DB + API testing without spawning video pipelines.
"""

import os
import sys
import asyncio
import pytest
import pytest_asyncio
from typing import AsyncGenerator
from unittest.mock import MagicMock, AsyncMock, patch

# Ensure backend is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

# Patch FFmpeg manager BEFORE importing app modules so lifespan never spawns processes
_mock_ffmpeg = MagicMock()
_mock_ffmpeg.start_recording = AsyncMock(return_value=True)
_mock_ffmpeg.stop_recording = AsyncMock(return_value=True)
_mock_ffmpeg.is_recording = MagicMock(return_value=False)
_mock_ffmpeg.get_active_pids = MagicMock(return_value=[])
_mock_ffmpeg.restart_recording = AsyncMock(return_value=True)
_mock_ffmpeg.shutdown_all = AsyncMock(return_value=None)

sys.modules["app.services.ffmpeg_manager"] = MagicMock(ffmpeg_manager=_mock_ffmpeg)

from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.main import app
from app.database import Base, get_db, async_session_maker
from app.config import settings

# ── Database setup ───────────────────────────────────────────────────────────

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://nvr:nvr_test_pass@localhost:5432/gvd_nvr_test",
)

async_engine = create_async_engine(TEST_DATABASE_URL, echo=False, future=True)
AsyncTestingSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncTestingSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db


# ── Pytest fixtures ──────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session")
async def db_engine():
    """Create all tables once per test session."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_engine
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await async_engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a clean DB session for each test, with rollback."""
    async with AsyncTestingSessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def async_client(db_engine) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client that talks to the app without spawning lifespan services."""
    transport = ASGITransport(app=app, raise_app_exceptions=True)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def sync_client(db_engine):
    """Synchronous TestClient for non-async test cases."""
    with TestClient(app) as client:
        yield client


@pytest_asyncio.fixture
async def auth_headers(async_client: AsyncClient) -> dict:
    """Register and login to get a valid JWT bearer token."""
    # Register admin
    await async_client.post("/api/auth/register", json={
        "username": "admin",
        "email": "admin@test.com",
        "password": "TestPassword123!",
        "role": "admin",
    })
    # Login
    resp = await async_client.post("/api/auth/login", json={
        "username": "admin",
        "password": "TestPassword123!",
    })
    data = resp.json()
    token = data.get("access_token") or data.get("token", "")
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def test_camera(async_client: AsyncClient, auth_headers: dict) -> dict:
    """Create a single test camera and return its JSON."""
    payload = {
        "name": "Integration Test Camera",
        "main_stream_url": "rtsp://localhost:8554/test_cam_001",
        "sub_stream_url": "rtsp://localhost:8554/test_cam_001_sub",
        "location": "Lab",
        "recording_mode": "manual",
        "recording_fps": 15,
    }
    resp = await async_client.post("/api/cameras", json=payload, headers=auth_headers)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()
