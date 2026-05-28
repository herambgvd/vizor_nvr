# =============================================================================
# Spot Output Service Unit Tests
# =============================================================================

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def service():
    from app.spot_output.service import SpotOutputService
    return SpotOutputService()


def make_spot(camera_ids=None, layout="2x2", stream_name="spot-1"):
    spot = MagicMock()
    spot.camera_ids = camera_ids or ["cam-1", "cam-2"]
    spot.layout = layout
    spot.stream_name = stream_name
    spot.is_active = True
    return spot


@pytest.mark.asyncio
async def test_create_spot_stream_happy_path(service):
    """Should call go2rtc add_stream with composite URL."""
    spot = make_spot(camera_ids=["cam-1"])

    mock_cam = MagicMock()
    mock_cam.id = "cam-1"
    mock_cam.main_stream_url = "rtsp://cam1/stream"

    mock_g2r = MagicMock()
    mock_g2r.add_stream = AsyncMock(return_value=True)

    with patch("app.spot_output.service.async_session_maker") as mock_session, \
         patch("app.services.go2rtc_manager.go2rtc_manager", mock_g2r), \
         patch.dict("sys.modules", {"app.services.go2rtc_manager": MagicMock(go2rtc_manager=mock_g2r)}):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_cam]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await service.create_spot_stream(spot)

    assert result is True


@pytest.mark.asyncio
async def test_create_spot_stream_no_camera_ids(service):
    """Empty camera list returns False without touching go2rtc."""
    spot = make_spot(camera_ids=[])
    result = await service.create_spot_stream(spot)
    assert result is False


@pytest.mark.asyncio
async def test_create_spot_stream_no_stream_urls(service):
    """If cameras have no main_stream_url, returns False."""
    spot = make_spot(camera_ids=["cam-1"])

    mock_cam = MagicMock()
    mock_cam.id = "cam-1"
    mock_cam.main_stream_url = None

    with patch("app.spot_output.service.async_session_maker") as mock_session:
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_cam]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await service.create_spot_stream(spot)

    assert result is False


@pytest.mark.asyncio
async def test_delete_spot_stream(service):
    mock_g2r = MagicMock()
    mock_g2r.remove_stream = AsyncMock(return_value=True)
    with patch.dict("sys.modules", {"app.services.go2rtc_manager": MagicMock(go2rtc_manager=mock_g2r)}):
        result = await service.delete_spot_stream("spot-1")
    assert result is True


@pytest.mark.asyncio
async def test_update_spot_stream_calls_delete_then_create(service):
    spot = make_spot()
    with patch.object(service, "delete_spot_stream", new_callable=AsyncMock) as mock_del, \
         patch.object(service, "create_spot_stream", new_callable=AsyncMock, return_value=True) as mock_create:
        result = await service.update_spot_stream(spot)
    mock_del.assert_called_once_with(spot.stream_name)
    mock_create.assert_called_once_with(spot)
    assert result is True


def test_get_rtsp_url(service):
    url = service.get_rtsp_url("spot-test")
    assert "spot-test" in url
    assert url.startswith("rtsp://")


@pytest.mark.asyncio
async def test_refresh_all_calls_create_for_each_active_spot(service):
    spot1 = make_spot(stream_name="spot-1")
    spot2 = make_spot(stream_name="spot-2")

    with patch("app.spot_output.service.async_session_maker") as mock_session, \
         patch.object(service, "create_spot_stream", new_callable=AsyncMock) as mock_create:
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [spot1, spot2]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        await service.refresh_all()

    assert mock_create.call_count == 2


@pytest.mark.asyncio
async def test_create_spot_stream_handles_exception(service):
    spot = make_spot()
    with patch("app.spot_output.service.async_session_maker", side_effect=Exception("DB fail")):
        result = await service.create_spot_stream(spot)
    assert result is False
