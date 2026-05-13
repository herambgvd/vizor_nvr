"""Shared pytest fixtures.

Targets unit tests of pure logic + service-layer code with SQLite-in-memory.
Integration tests against the FastAPI app should use httpx.AsyncClient with
the lifespan disabled (it spawns FFmpeg watchdogs and would hang tests)."""
import asyncio
import os
import sys
import pytest

# Make `app` importable when running `pytest backend/`
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-prod-use-only")
os.environ.setdefault("STORAGE_PATH", "/tmp/gvd-nvr-test/recordings")
os.environ.setdefault("DATA_PATH", "/tmp/gvd-nvr-test/data")
os.environ.setdefault("CERT_PATH", "/tmp/gvd-nvr-test/data/certs")


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
