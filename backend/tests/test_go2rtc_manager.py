# =============================================================================
# Tests for Go2RTCManager.add_stream — spurious-400 handling
#
# go2rtc 1.9.x returns HTTP 400 ("yaml: line 1: did not find expected key")
# on the query-param stream-add endpoint even though the stream IS registered.
# add_stream must trust the registry state (verified via GET) over the
# misleading status code, otherwise recording never starts and the camera
# flaps error<->online.
# =============================================================================

import pytest
from unittest.mock import AsyncMock, MagicMock


def _resp(status_code, text=""):
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    return r


@pytest.fixture
def manager():
    from app.services.go2rtc_manager import Go2RTCManager
    return Go2RTCManager()


def _attach_client(manager, put_resp, get_resp):
    client = MagicMock()
    client.is_closed = False
    client.put = AsyncMock(return_value=put_resp)
    client.get = AsyncMock(return_value=get_resp)
    manager._client = client
    return client


@pytest.mark.asyncio
async def test_add_stream_clean_200(manager):
    _attach_client(manager, _resp(200), _resp(200))
    assert await manager.add_stream("cam-1", "rtsp://h/s") is True


@pytest.mark.asyncio
async def test_add_stream_spurious_400_but_registered(manager):
    """The core regression: PUT returns 400 but GET confirms registration."""
    client = _attach_client(
        manager,
        _resp(400, "yaml: line 1: did not find expected key\n"),
        _resp(200),  # GET /api/streams?src=ID → registered
    )
    assert await manager.add_stream("cam-1", "rtsp://h/s") is True
    client.get.assert_awaited()  # verified via GET, not status code


@pytest.mark.asyncio
async def test_add_stream_400_and_not_registered_is_failure(manager):
    """A genuine failure: 400 AND the stream is absent (GET 404)."""
    _attach_client(
        manager,
        _resp(400, "yaml: line 1: did not find expected key\n"),
        _resp(404),
    )
    assert await manager.add_stream("cam-1", "rtsp://h/s", max_retries=1) is False


@pytest.mark.asyncio
async def test_is_registered(manager):
    _attach_client(manager, _resp(200), _resp(200))
    assert await manager.is_registered("cam-1") is True
    _attach_client(manager, _resp(200), _resp(404))
    assert await manager.is_registered("missing") is False
