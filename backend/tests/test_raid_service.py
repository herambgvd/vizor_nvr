# =============================================================================
# RAID Service Unit Tests (mdadm mocked)
# =============================================================================

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture(autouse=True)
def force_linux(monkeypatch):
    import app.storage.raid_service as mod
    monkeypatch.setattr(mod, "_is_linux", lambda: True)
    monkeypatch.setattr(mod, "_mdadm_available", lambda: True)
    monkeypatch.setattr(mod, "_lsblk_available", lambda: True)


@pytest.fixture
def service():
    from app.storage.raid_service import RAIDService
    return RAIDService()


def make_proc(returncode=0, stdout=b"", stderr=b""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


@pytest.mark.asyncio
async def test_list_arrays_parses_output(service):
    scan_output = b"ARRAY /dev/md0 metadata=1.2 UUID=abc123\n"
    detail_output = (
        b"Raid Level : raid1\n"
        b"State : active\n"
        b"Working Devices : 2\n"
        b"Failed Devices : 0\n"
    )

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.side_effect = [
            make_proc(stdout=scan_output),
            make_proc(stdout=detail_output),
        ]
        arrays = await service.list_arrays()

    assert len(arrays) == 1
    assert arrays[0]["device"] == "/dev/md0"
    assert arrays[0]["level"] == "raid1"


@pytest.mark.asyncio
async def test_list_arrays_handles_mdadm_failure(service):
    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError("mdadm not found")):
        arrays = await service.list_arrays()
    assert arrays == []


@pytest.mark.asyncio
async def test_create_array_happy_path(service):
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.return_value = make_proc(returncode=0)
        result = await service.create_array(
            "/dev/md1", "raid1", ["/dev/sdb", "/dev/sdc"]
        )
    assert result["success"] is True
    # Verify mdadm was called with correct args
    call_args = mock_exec.call_args[0]
    assert "mdadm" in call_args
    assert "--create" in call_args
    assert "--level" in call_args
    assert "1" in call_args


@pytest.mark.asyncio
async def test_create_array_unsupported_level(service):
    result = await service.create_array("/dev/md1", "raid99", ["/dev/sdb"])
    assert result["success"] is False
    assert "Unsupported" in result["message"]


@pytest.mark.asyncio
async def test_create_array_mdadm_error(service):
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.return_value = make_proc(returncode=1, stderr=b"Device already in use")
        result = await service.create_array("/dev/md1", "raid5", ["/dev/sdb", "/dev/sdc", "/dev/sdd"])
    assert result["success"] is False
    assert "Device already in use" in result["message"]


@pytest.mark.asyncio
async def test_stop_array_success(service):
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.return_value = make_proc(returncode=0)
        result = await service.stop_array("/dev/md0")
    assert result["success"] is True


@pytest.mark.asyncio
async def test_stop_array_failure(service):
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.return_value = make_proc(returncode=1, stderr=b"Cannot stop busy array")
        result = await service.stop_array("/dev/md0")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_list_block_devices_parses_lsblk(service):
    lsblk_output = b"sdb 500G disk SAMSUNG SSD\nsdc 2T disk SEAGATE HDD\n"
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.return_value = make_proc(stdout=lsblk_output)
        devices = await service.list_block_devices()

    assert len(devices) >= 1
    assert any(d["name"].endswith("sdb") for d in devices)


def test_extract_helper(service):
    text = "Raid Level : raid5\nState : active\n"
    assert service._extract(text, r"Raid Level : (\S+)") == "raid5"
    assert service._extract(text, r"Nothing : (\S+)") is None
