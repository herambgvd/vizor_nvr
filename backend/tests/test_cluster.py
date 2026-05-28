# =============================================================================
# Cluster Service Unit Tests
# =============================================================================

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def service():
    from app.cluster.service import ClusterService
    return ClusterService()


def test_initial_state(service):
    assert service.is_leader is False
    assert service.node_id is not None


@pytest.mark.asyncio
async def test_start_stop(service):
    with patch.object(service, "_register_node", new_callable=AsyncMock) as mock_reg, \
         patch.object(service, "_loop", new_callable=AsyncMock) as mock_loop:
        mock_loop.return_value = None
        await service.start()
        assert service._running is True
        mock_reg.assert_called_once()
        # stop
        service._is_leader = False
        await service.stop()
        assert service._running is False


@pytest.mark.asyncio
async def test_start_idempotent(service):
    """Calling start twice should not create duplicate tasks."""
    with patch.object(service, "_register_node", new_callable=AsyncMock), \
         patch.object(service, "_loop", new_callable=AsyncMock):
        await service.start()
        task1 = service._task
        await service.start()
        task2 = service._task
        assert task1 is task2
        service._running = False
        if service._task:
            service._task.cancel()
            try:
                await service._task
            except (asyncio.CancelledError, Exception):
                pass


@pytest.mark.asyncio
async def test_promote_sets_leader_flag(service):
    """_promote should flip is_leader to True and update DB."""
    mock_db = AsyncMock()
    mock_node = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_node
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    with patch("app.cluster.service.camera_monitor", create=True) as mock_mon:
        mock_mon.start = AsyncMock()
        with patch("app.cluster.service.linkage_engine", create=True) as mock_le:
            mock_le.fire_event = AsyncMock()
            # Patch imports inside _promote
            with patch("app.cluster.service.async_session_maker"), \
                 patch("app.services.camera_monitor.camera_monitor"):
                await service._promote(mock_db)

    assert service._is_leader is True
    assert mock_node.role == "active"
    assert mock_node.is_leader is True


@pytest.mark.asyncio
async def test_demote_sets_standby_flag(service):
    service._is_leader = True

    with patch("app.cluster.service.async_session_maker") as mock_session:
        mock_db = AsyncMock()
        mock_node = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_node
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("app.cluster.service.ffmpeg_manager", create=True) as mock_ffmpeg:
            mock_ffmpeg.cleanup_all = AsyncMock()
            with patch("app.cluster.service.camera_monitor", create=True) as mock_mon:
                mock_mon.stop = AsyncMock()
                await service._demote("test_reason")

    assert service._is_leader is False


@pytest.mark.asyncio
async def test_force_failover_rejects_non_leader(service):
    service._is_leader = False
    result = await service.force_failover()
    assert result["success"] is False


@pytest.mark.asyncio
async def test_get_status_returns_structure(service):
    with patch("app.cluster.service.async_session_maker") as mock_session:
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        status = await service.get_status()

    assert "this_node" in status
    assert "is_leader" in status
    assert "nodes" in status


@pytest.mark.asyncio
async def test_register_node_handles_db_error(service):
    """Registration failure should be swallowed (logged only)."""
    with patch("app.cluster.service.async_session_maker") as mock_session:
        mock_session.side_effect = Exception("DB unavailable")
        # Should not raise
        await service._register_node()
