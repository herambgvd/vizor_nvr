# =============================================================================
# WhatsApp Service Unit Tests
# =============================================================================

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def service():
    from app.notifications.whatsapp_service import WhatsAppService
    svc = WhatsAppService()
    svc._client = None
    return svc


@pytest.mark.asyncio
async def test_send_returns_error_when_not_configured(service):
    with patch.object(service, "_get_client", return_value=None):
        result = await service.send("+15550001234", "Test")
    assert result["ok"] is False
    assert "Twilio not configured" in result["error"]


@pytest.mark.asyncio
async def test_send_returns_error_when_from_number_missing(service):
    mock_client = MagicMock()
    with patch.object(service, "_get_client", return_value=mock_client), \
         patch("app.notifications.whatsapp_service.SettingsService", create=True) as mock_ss:
        mock_ss.get_sync.return_value = ""
        result = await service.send("+15550001234", "Test")
    assert result["ok"] is False
    assert "number" in result["error"].lower()


@pytest.mark.asyncio
async def test_send_prepends_whatsapp_prefix(service):
    mock_msg = MagicMock()
    mock_msg.sid = "SM456"
    mock_msg.status = "queued"
    mock_client = MagicMock()

    with patch.object(service, "_get_client", return_value=mock_client), \
         patch("asyncio.to_thread", new_callable=AsyncMock, return_value=mock_msg):
        # Pass from_number directly to skip SettingsService lookup
        result = await service.send("+15550001234", "Hello via WhatsApp", from_number="+15555550000")

    assert result["ok"] is True


@pytest.mark.asyncio
async def test_send_does_not_double_prefix(service):
    """Numbers already prefixed with 'whatsapp:' should not be double-prefixed."""
    mock_msg = MagicMock()
    mock_msg.sid = "SM789"
    mock_msg.status = "queued"
    mock_client = MagicMock()

    with patch.object(service, "_get_client", return_value=mock_client), \
         patch("asyncio.to_thread", new_callable=AsyncMock, return_value=mock_msg):
        result = await service.send("whatsapp:+15550001234", "Test", from_number="whatsapp:+15555550000")

    assert result["ok"] is True


@pytest.mark.asyncio
async def test_send_catches_exception(service):
    mock_client = MagicMock()

    with patch.object(service, "_get_client", return_value=mock_client), \
         patch("asyncio.to_thread", side_effect=Exception("Connection refused")):
        result = await service.send("+15550001234", "Test", from_number="+15555550000")

    assert result["ok"] is False
    assert "Connection refused" in result["error"]


@pytest.mark.asyncio
async def test_send_bulk_sends_to_all(service):
    recipients = ["+15550001111", "+15550002222"]

    async def mock_send(to, msg, from_number=None):
        return {"ok": True, "sid": f"SM-{to[-4:]}", "status": "queued"}

    with patch.object(service, "send", side_effect=mock_send):
        results = await service.send_bulk(recipients, "Bulk alert")

    assert len(results) == 2
    assert all(r["ok"] for r in results)


@pytest.mark.asyncio
async def test_send_bulk_continues_on_individual_failure(service):
    call_n = [0]

    async def mock_send(to, msg, from_number=None):
        call_n[0] += 1
        if call_n[0] == 1:
            return {"ok": False, "error": "Rate limited"}
        return {"ok": True, "sid": "SMok", "status": "queued"}

    with patch.object(service, "send", side_effect=mock_send):
        results = await service.send_bulk(["+1111", "+2222"], "Test")

    assert len(results) == 2
    assert results[0]["ok"] is False
    assert results[1]["ok"] is True


def test_get_client_returns_none_without_credentials(service):
    with patch("app.notifications.whatsapp_service.SettingsService", create=True) as mock_ss:
        mock_ss.get_sync.return_value = ""
        client = service._get_client()
    assert client is None
