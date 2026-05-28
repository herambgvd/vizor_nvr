# =============================================================================
# Integration tests for ANR, NAS, SMS/WhatsApp, POS Overlay, Dewarp
# =============================================================================

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


# ── ANR Tests ─────────────────────────────────────────────────────────────────

class TestANRService:
    @pytest.fixture
    def anr_service(self):
        from app.services.anr_service import ANRService
        return ANRService()

    @pytest.mark.asyncio
    async def test_anr_skips_disabled_camera(self, anr_service):
        mock_db = AsyncMock()
        mock_camera = MagicMock()
        mock_camera.anr_enabled = False
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_camera
        mock_db.execute.return_value = mock_result

        with patch("app.services.anr_service.async_session_maker") as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
            await anr_service.on_camera_recovered("cam-1")
            mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_anr_finds_gap(self, anr_service):
        from datetime import timedelta
        mock_db = AsyncMock()
        mock_camera = MagicMock()
        mock_camera.last_online_at = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        mock_camera.anr_enabled = True
        mock_camera.anr_max_gap_hours = 24

        mock_rec = MagicMock()
        mock_rec.end_time = datetime(2024, 1, 1, 9, 30, 0, tzinfo=timezone.utc)

        cam_result = MagicMock()
        cam_result.scalar_one_or_none.return_value = mock_camera
        rec_result = MagicMock()
        rec_result.scalar_one_or_none.return_value = mock_rec

        call_count = [0]
        def side_effect(query):
            call_count[0] += 1
            return cam_result if call_count[0] == 1 else rec_result
        mock_db.execute.side_effect = side_effect

        gap_start, gap_end = await anr_service._find_gap(mock_db, "cam-1")
        assert gap_start == mock_rec.end_time
        assert gap_end is not None


# ── NAS Tests ─────────────────────────────────────────────────────────────────

class TestNASService:
    @pytest.fixture
    def nas_service(self):
        from app.storage.nas_service import NASService
        return NASService()

    def test_is_mounted_no_privileges(self, nas_service):
        with patch.object(nas_service, "_has_mount_privileges", return_value=False):
            mock_pool = MagicMock()
            mock_pool.pool_type = "nfs"
            result = nas_service.mount_pool(mock_pool)
            assert result["ok"] is False
            assert "CAP_SYS_ADMIN" in result["message"]

    def test_check_mount_health_not_mounted(self, nas_service):
        mock_pool = MagicMock()
        mock_pool.id = "p1"
        mock_pool.name = "test"
        mock_pool.path = "/mnt/test"
        with patch.object(nas_service, "_is_mounted", return_value=False):
            result = nas_service.check_mount_health(mock_pool)
            assert result["healthy"] is False
            assert result["mounted"] is False


# ── SMS / WhatsApp Tests ─────────────────────────────────────────────────────

class TestSMSService:
    @pytest.mark.asyncio
    async def test_sms_not_configured(self):
        from app.notifications.sms_service import SMSService
        svc = SMSService()
        result = await svc.send("+1234567890", "test")
        assert result["ok"] is False
        assert "not configured" in result["error"]

    @pytest.mark.asyncio
    async def test_whatsapp_not_configured(self):
        from app.notifications.whatsapp_service import WhatsAppService
        svc = WhatsAppService()
        result = await svc.send("+1234567890", "test")
        assert result["ok"] is False
        assert "not configured" in result["error"]


# ── POS Overlay Tests ─────────────────────────────────────────────────────────

class TestPOSOverlayService:
    @pytest.fixture
    def pos_service(self):
        from app.services.pos_overlay_service import POSOverlayService
        return POSOverlayService()

    def test_set_and_get_text(self, pos_service):
        pos_service.set_text("cam-1", "TXN: $100.00")
        assert pos_service.get_text("cam-1") == "TXN: $100.00"
        assert pos_service.has_overlay("cam-1") is True

    def test_clear_text(self, pos_service):
        pos_service.set_text("cam-1", "TXN: $100.00")
        pos_service.clear_text("cam-1")
        assert pos_service.get_text("cam-1") is None
        assert pos_service.has_overlay("cam-1") is False


# ── Dewarp Tests ──────────────────────────────────────────────────────────────

class TestDewarpService:
    @pytest.fixture
    def dewarp_service(self):
        from app.services.dewarp_service import DewarpService
        return DewarpService()

    def test_build_filter_panoramic(self, dewarp_service):
        f = dewarp_service.build_v360_filter(
            "cam-1", mount_mode="ceiling", view_mode="panoramic"
        )
        assert "v360" in f
        assert "input=equirect" in f
        assert "output=rect" in f

    def test_build_filter_quad(self, dewarp_service):
        f = dewarp_service.build_v360_filter(
            "cam-1", mount_mode="ceiling", view_mode="quad"
        )
        assert "v360" in f
        assert "hstack" in f
        assert "vstack" in f

    def test_invalid_mount_returns_none(self, dewarp_service):
        f = dewarp_service.build_v360_filter("cam-1", mount_mode="invalid")
        assert f is None

    def test_go2rtc_source_url(self, dewarp_service):
        url = dewarp_service.build_go2rtc_source_url(
            "cam-1", "rtsp://cam/stream", "v360=input=equirect:output=rect"
        )
        assert url.startswith("ffmpeg:rtsp://cam/stream")
        assert "v360" in url


# ── Schema Tests ──────────────────────────────────────────────────────────────

class TestCameraSchemas:
    def test_camera_response_has_new_fields(self):
        from app.cameras.models import CameraResponse
        schema = CameraResponse.model_json_schema()
        assert "pos_overlay_config" in schema["properties"]
        assert "dewarp_config" in schema["properties"]

    def test_storage_pool_response_has_nas_fields(self):
        from app.storage.models import StoragePoolResponse
        schema = StoragePoolResponse.model_json_schema()
        assert "nas_server" in schema["properties"]
        assert "nas_mount_state" in schema["properties"]
