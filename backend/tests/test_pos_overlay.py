# =============================================================================
# POS Overlay Service Unit Tests
# =============================================================================

import asyncio
import os
import pytest
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def service(tmp_path):
    import app.services.pos_overlay_service as mod
    original = mod.POS_DIR
    mod.POS_DIR = str(tmp_path)
    from app.services.pos_overlay_service import POSOverlayService
    svc = POSOverlayService()
    yield svc
    mod.POS_DIR = original


def test_set_text_writes_file(service, tmp_path):
    service.set_text("cam-1", "Sale $9.99")
    file_path = os.path.join(str(tmp_path), "cam-1.txt")
    assert os.path.exists(file_path)
    assert open(file_path).read() == "Sale $9.99"


def test_get_text_returns_value(service):
    service.set_text("cam-2", "Hello World")
    assert service.get_text("cam-2") == "Hello World"


def test_get_text_returns_none_for_unknown(service):
    assert service.get_text("not-a-cam") is None


def test_clear_text_removes_from_memory_and_file(service, tmp_path):
    service.set_text("cam-3", "Some text")
    service.clear_text("cam-3")
    assert service.get_text("cam-3") is None
    assert not os.path.exists(os.path.join(str(tmp_path), "cam-3.txt"))


def test_has_overlay_true(service, tmp_path):
    service.set_text("cam-4", "text")
    assert service.has_overlay("cam-4") is True


def test_has_overlay_false_when_not_set(service):
    assert service.has_overlay("cam-9999") is False


def test_resolve_camera_by_ip(service):
    with patch.dict(os.environ, {"POS_CAM_192_168_1_50": "cam-abc"}):
        result = service._resolve_camera_by_ip("192.168.1.50")
        assert result == "cam-abc"


def test_resolve_camera_by_ip_unknown(service):
    result = service._resolve_camera_by_ip("10.0.0.99")
    assert result is None


@pytest.mark.asyncio
async def test_tcp_listener_start_stop(service):
    """TCP server should start and stop cleanly."""
    await service.start_tcp_listener(host="127.0.0.1", port=0)
    assert service._tcp_server is not None
    await service.stop_tcp_listener()
    assert service._tcp_server is None


@pytest.mark.asyncio
async def test_tcp_listener_idempotent_start(service):
    """Calling start_tcp_listener twice should not create second server."""
    await service.start_tcp_listener(host="127.0.0.1", port=0)
    server_ref = service._tcp_server
    await service.start_tcp_listener(host="127.0.0.1", port=0)
    assert service._tcp_server is server_ref
    await service.stop_tcp_listener()
