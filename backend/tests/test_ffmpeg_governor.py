# =============================================================================
# FFmpeg Resource Governor Unit Tests
# =============================================================================

import asyncio
import pytest
from unittest.mock import patch


@pytest.fixture
def governor():
    from app.services.ffmpeg_governor import FFmpegResourceGovernor
    return FFmpegResourceGovernor()


def test_initial_cap_within_bounds(governor):
    assert 64 <= governor.cap <= 512


def test_available_equals_cap_at_start(governor):
    assert governor.available == governor.cap


def test_used_is_zero_at_start(governor):
    assert governor.used == 0


@pytest.mark.asyncio
async def test_acquire_and_release(governor):
    ok = await governor.acquire("cam-1", "recording", timeout=1.0)
    assert ok is True
    assert governor.used == 1
    governor.release("cam-1", "recording")
    assert governor.used == 0


@pytest.mark.asyncio
async def test_acquire_multiple_slots(governor):
    acquired = []
    for i in range(5):
        ok = await governor.acquire(f"cam-{i}", "recording", timeout=1.0)
        assert ok is True
        acquired.append((f"cam-{i}", "recording"))
    assert governor.used == 5
    for owner, purpose in acquired:
        governor.release(owner, purpose)
    assert governor.used == 0


@pytest.mark.asyncio
async def test_acquire_fails_at_cap(governor):
    """When cap is 1, second acquire should fail."""
    governor._cap = 1
    governor._semaphore = asyncio.Semaphore(1)

    ok1 = await governor.acquire("cam-1", "recording", timeout=0.1)
    assert ok1 is True
    ok2 = await governor.acquire("cam-2", "recording", timeout=0.1)
    assert ok2 is False  # cap reached

    governor.release("cam-1", "recording")


def test_status_returns_dict(governor):
    s = governor.status()
    assert "cap" in s
    assert "used" in s
    assert "available" in s
    assert "active_breakdown" in s


@pytest.mark.asyncio
async def test_status_after_acquire(governor):
    await governor.acquire("cam-1", "motion", timeout=1.0)
    s = governor.status()
    assert s["used"] == 1
    governor.release("cam-1", "motion")


def test_cap_clamped_from_settings():
    with patch("app.services.ffmpeg_governor.settings") as mock_settings:
        mock_settings.FFMPEG_GLOBAL_PROCESS_CAP = "10"  # below minimum of 64
        from app.services.ffmpeg_governor import FFmpegResourceGovernor
        g = FFmpegResourceGovernor()
        assert g.cap == 64  # clamped to minimum


def test_cap_clamped_maximum():
    with patch("app.services.ffmpeg_governor.settings") as mock_settings:
        mock_settings.FFMPEG_GLOBAL_PROCESS_CAP = "9999"  # above maximum of 512
        from app.services.ffmpeg_governor import FFmpegResourceGovernor
        g = FFmpegResourceGovernor()
        assert g.cap == 512  # clamped to maximum
