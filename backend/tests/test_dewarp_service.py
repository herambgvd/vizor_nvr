# =============================================================================
# Dewarp Service Unit Tests
# =============================================================================

import pytest
from app.services.dewarp_service import DewarpService


@pytest.fixture
def service():
    return DewarpService()


def test_build_v360_filter_basic(service):
    result = DewarpService.build_v360_filter("cam-1", mount_mode="ceiling", view_mode="panoramic")
    assert result is not None
    assert "v360" in result
    assert "equirect" in result


def test_build_v360_filter_invalid_mount(service):
    result = DewarpService.build_v360_filter("cam-1", mount_mode="unknown")
    assert result is None


def test_build_v360_filter_invalid_view_mode(service):
    result = DewarpService.build_v360_filter("cam-1", view_mode="flying_saucer")
    assert result is None


def test_build_v360_filter_quad_mode(service):
    result = DewarpService.build_v360_filter(
        "cam-1", mount_mode="ceiling", view_mode="quad", output_w=1920, output_h=1080
    )
    assert result is not None
    # Quad mode returns a filter_complex with multiple views
    assert "hstack" in result
    assert "vstack" in result


def test_build_v360_filter_ptz_mode(service):
    result = DewarpService.build_v360_filter("cam-1", view_mode="ptz", pan=45.0, tilt=-20.0)
    assert result is not None
    assert "v360" in result


def test_build_v360_filter_custom_fov(service):
    result = DewarpService.build_v360_filter(
        "cam-1", fov_x=120.0, fov_y=80.0, pan=30.0, tilt=10.0, roll=5.0
    )
    assert result is not None
    assert "120.0" in result or "120" in result


def test_build_go2rtc_source_url(service):
    url = DewarpService.build_go2rtc_source_url(
        "cam-1",
        "rtsp://cam1/stream",
        "v360=input=equirect:output=rect"
    )
    assert "ffmpeg:" in url
    assert "rtsp://cam1/stream" in url


def test_get_default_params_ceiling(service):
    params = DewarpService.get_default_params("ceiling")
    assert params["tilt"] == -90
    assert "fov_x" in params


def test_get_default_params_wall(service):
    params = DewarpService.get_default_params("wall")
    assert params["tilt"] == 0
    assert params["fov_x"] == 90


def test_get_default_params_unknown_falls_back_to_ceiling(service):
    params = DewarpService.get_default_params("rooftop")
    # Falls back to ceiling defaults
    assert params == DewarpService.get_default_params("ceiling")


def test_all_mount_modes_produce_valid_filters(service):
    for mount in DewarpService.MOUNT_MODES:
        result = DewarpService.build_v360_filter("cam-1", mount_mode=mount, view_mode="single")
        assert result is not None, f"Expected filter for mount_mode={mount}"
