# =============================================================================
# SMS Service Unit Tests
# =============================================================================

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def service():
    from app.notifications.sms_service import SMSService
    svc = SMSService()
    svc._client = None
    return svc


@pytest.mark.asyncio
async def test_send_returns_error_when_twilio_not_configured(service):
    with patch.object(service, "_get_client", return_value=None):
        result = await service.send("+15550001234", "Test message")
    assert result["ok"] is False
    assert "Twilio not configured" in result["error"]


@pytest.mark.asyncio
async def test_send_returns_error_when_from_number_missing(service):
    mock_client = MagicMock()
    with patch.object(service, "_get_client", return_value=mock_client), \
         patch("app.notifications.sms_service.SettingsService", create=True) as mock_ss:
        mock_ss.get_sync.return_value = ""
        result = await service.send("+15550001234", "Test message")
    assert result["ok"] is False
    assert "phone number" in result["error"].lower()


@pytest.mark.asyncio
async def test_send_happy_path(service):
    mock_msg = MagicMock()
    mock_msg.sid = "SM123abc"
    mock_msg.status = "queued"

    mock_client = MagicMock()

    # Patch asyncio.to_thread in the asyncio module (used via 'from asyncio import to_thread')
    with patch.object(service, "_get_client", return_value=mock_client), \
         patch("asyncio.to_thread", new_callable=AsyncMock, return_value=mock_msg):
        # Pass from_number directly to skip SettingsService lookup
        result = await service.send("+15550001234", "Alert: motion detected", from_number="+15555550000")

    assert result["ok"] is True
    assert result["sid"] == "SM123abc"


@pytest.mark.asyncio
async def test_send_catches_twilio_exception(service):
    mock_client = MagicMock()

    with patch.object(service, "_get_client", return_value=mock_client), \
         patch("asyncio.to_thread", side_effect=Exception("Network error")):
        result = await service.send("+15550001234", "Test", from_number="+15555550000")

    assert result["ok"] is False
    assert "Network error" in result["error"]


@pytest.mark.asyncio
async def test_send_bulk_sends_to_all_recipients(service):
    recipients = ["+15550001111", "+15550002222", "+15550003333"]

    async def mock_send(to, msg, from_number=None):
        return {"ok": True, "sid": f"SM-{to[-4:]}", "status": "queued"}

    with patch.object(service, "send", side_effect=mock_send):
        results = await service.send_bulk(recipients, "Bulk alert")

    assert len(results) == 3
    assert all(r["ok"] for r in results)


@pytest.mark.asyncio
async def test_send_bulk_continues_on_failure(service):
    call_count = [0]

    async def mock_send(to, msg, from_number=None):
        call_count[0] += 1
        if call_count[0] == 2:
            return {"ok": False, "error": "Invalid number"}
        return {"ok": True, "sid": "SM-ok", "status": "queued"}

    with patch.object(service, "send", side_effect=mock_send):
        results = await service.send_bulk(
            ["+15550001111", "+15550002222", "+15550003333"], "Test"
        )

    assert len(results) == 3
    assert results[1]["ok"] is False
    assert results[0]["ok"] is True
    assert results[2]["ok"] is True


def test_get_client_returns_none_without_credentials(service):
    with patch("app.notifications.sms_service.SettingsService", create=True) as mock_ss:
        mock_ss.get_sync.return_value = ""
        client = service._get_client()
    assert client is None
