# =============================================================================
# ONVIF Device Server Tests
# =============================================================================

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Patch engine creation before any app import to avoid SQLite pool arg issues
with patch("sqlalchemy.ext.asyncio.create_async_engine") as _mock_engine:
    from app.onvif_device.service import onvif_device_service


class _MockCam:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


@pytest.fixture
def mock_camera():
    return _MockCam(
        id="cam-1",
        name="Test Camera",
        main_stream_url="rtsp://cam1/stream1",
        resolution="1920x1080",
        fps=25,
        bitrate="4096 kbps",
        codec="h264",
        is_enabled=True,
        is_recording=True,
        location="Lab",
        description="Test",
    )


def _soap_request(body: bytes, action: str, host: str = "192.168.1.100"):
    req = MagicMock()
    req.body = AsyncMock(return_value=body)
    req.headers = {"host": host, "soapaction": action}
    return req


@pytest.mark.asyncio
async def test_get_device_information():
    body = b"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
               xmlns:tds="http://www.onvif.org/ver10/device/wsdl">
  <soap:Body><tds:GetDeviceInformation/></soap:Body>
</soap:Envelope>"""
    req = _soap_request(body, "http://www.onvif.org/ver10/device/wsdl/GetDeviceInformation")
    resp = await onvif_device_service.handle("/onvif/device_service", req)
    assert resp.status_code == 200
    text = resp.body.decode("utf-8")
    assert "GVD" in text
    assert "NVR" in text


@pytest.mark.asyncio
async def test_get_capabilities(mock_camera):
    body = b"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
               xmlns:tds="http://www.onvif.org/ver10/device/wsdl">
  <soap:Body><tds:GetCapabilities/></soap:Body>
</soap:Envelope>"""
    req = _soap_request(body, "http://www.onvif.org/ver10/device/wsdl/GetCapabilities")

    with patch("app.onvif_device.service._get_cameras", new=AsyncMock(return_value=[mock_camera])):
        resp = await onvif_device_service.handle("/onvif/device_service", req)

    assert resp.status_code == 200
    text = resp.body.decode("utf-8")
    assert "/onvif/media_service" in text
    assert "/onvif/recording_service" in text


@pytest.mark.asyncio
async def test_media_get_profiles(mock_camera):
    body = b"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
               xmlns:trt="http://www.onvif.org/ver10/media/wsdl">
  <soap:Body><trt:GetProfiles/></soap:Body>
</soap:Envelope>"""
    req = _soap_request(body, "http://www.onvif.org/ver10/media/wsdl/GetProfiles")

    with patch("app.onvif_device.service._get_cameras", new=AsyncMock(return_value=[mock_camera])):
        resp = await onvif_device_service.handle("/onvif/media_service", req)

    assert resp.status_code == 200
    text = resp.body.decode("utf-8")
    assert "profile_cam-1" in text
    assert "Test Camera" in text


@pytest.mark.asyncio
async def test_media_get_stream_uri(mock_camera):
    body = b"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
               xmlns:trt="http://www.onvif.org/ver10/media/wsdl">
  <soap:Body>
    <trt:GetStreamUri>
      <trt:ProfileToken>profile_cam-1</trt:ProfileToken>
    </trt:GetStreamUri>
  </soap:Body>
</soap:Envelope>"""
    req = _soap_request(body, "http://www.onvif.org/ver10/media/wsdl/GetStreamUri")

    with patch("app.onvif_device.service._get_camera_by_id", new=AsyncMock(return_value=mock_camera)):
        resp = await onvif_device_service.handle("/onvif/media_service", req)

    assert resp.status_code == 200
    text = resp.body.decode("utf-8")
    assert "rtsp://192.168.1.100:8554/cam-1" in text


@pytest.mark.asyncio
async def test_recording_get_recordings(mock_camera):
    body = b"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
               xmlns:trc="http://www.onvif.org/ver10/recording/wsdl">
  <soap:Body><trc:GetRecordings/></soap:Body>
</soap:Envelope>"""
    req = _soap_request(body, "http://www.onvif.org/ver10/recording/wsdl/GetRecordings")

    with patch("app.onvif_device.service._get_cameras", new=AsyncMock(return_value=[mock_camera])):
        resp = await onvif_device_service.handle("/onvif/recording_service", req)

    assert resp.status_code == 200
    text = resp.body.decode("utf-8")
    assert "rec_cam-1" in text
    assert "track_cam-1" in text


@pytest.mark.asyncio
async def test_search_find_recordings(mock_camera):
    body = b"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
               xmlns:tse="http://www.onvif.org/ver10/search/wsdl">
  <soap:Body><tse:FindRecordings/></soap:Body>
</soap:Envelope>"""
    req = _soap_request(body, "http://www.onvif.org/ver10/search/wsdl/FindRecordings")

    with patch("app.onvif_device.service._get_cameras", new=AsyncMock(return_value=[mock_camera])):
        resp = await onvif_device_service.handle("/onvif/search_service", req)

    assert resp.status_code == 200
    text = resp.body.decode("utf-8")
    assert "SearchToken" in text
