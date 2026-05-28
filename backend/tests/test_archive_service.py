# =============================================================================
# Archive Service Unit Tests
# =============================================================================

import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call


@pytest.fixture
def service():
    from app.storage.archive_service import ArchiveService
    return ArchiveService()


@pytest.mark.asyncio
async def test_start_stop(service):
    with patch.object(service, "_loop", new_callable=AsyncMock):
        await service.start()
        assert service._running is True
        await service.stop()
        assert service._running is False


@pytest.mark.asyncio
async def test_start_idempotent(service):
    with patch.object(service, "_loop", new_callable=AsyncMock):
        await service.start()
        task1 = service._task
        await service.start()
        assert service._task is task1
        service._running = False
        if service._task:
            service._task.cancel()
            try:
                await service._task
            except (asyncio.CancelledError, Exception):
                pass


def test_should_run_wildcard(service):
    sched = MagicMock()
    sched.schedule = "* * * * *"
    assert service._should_run(sched) is True


def test_should_run_invalid_cron(service):
    sched = MagicMock()
    sched.schedule = "bad cron"
    assert service._should_run(sched) is False


def test_should_run_specific_hour_no_match(service):
    sched = MagicMock()
    now = datetime.now(timezone.utc)
    wrong_hour = (now.hour + 1) % 24
    sched.schedule = f"0 {wrong_hour} * * *"
    assert service._should_run(sched) is False


@pytest.mark.asyncio
async def test_run_backup_now_schedule_not_found(service):
    with patch("app.storage.archive_service.async_session_maker") as mock_session:
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await service.run_backup_now("non-existent-id")

    assert "error" in result


@pytest.mark.asyncio
async def test_run_backup_now_already_running(service):
    sched = MagicMock()
    sched.last_run_status = "running"

    with patch("app.storage.archive_service.async_session_maker") as mock_session:
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=sched)
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await service.run_backup_now("sched-1")

    assert "error" in result
    assert "running" in result["error"].lower()


@pytest.mark.asyncio
async def test_run_backup_now_triggers_task(service):
    sched = MagicMock()
    sched.last_run_status = "success"

    with patch("app.storage.archive_service.async_session_maker") as mock_session, \
         patch.object(service, "_run_backup", new_callable=AsyncMock) as mock_run, \
         patch("asyncio.create_task") as mock_task:
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=sched)
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await service.run_backup_now("sched-1")

    assert result["status"] == "started"
    mock_task.assert_called_once()


@pytest.mark.asyncio
async def test_run_backup_skips_if_target_not_mounted(service):
    """Backup job should fail early if target pool is not mounted."""
    sched = MagicMock()
    sched.is_active = True
    sched.source_pool_id = "pool-src"
    sched.target_pool_id = "pool-dst"
    sched.age_days = 30

    source_pool = MagicMock()
    source_pool.pool_type = "local"
    source_pool.path = "/mnt/recordings"

    target_pool = MagicMock()
    target_pool.pool_type = "nfs"
    target_pool.nas_mount_state = "unmounted"
    target_pool.name = "NAS-1"

    async def mock_get(cls, pk):
        if pk == "sched-1":
            return sched
        if pk == "pool-src":
            return source_pool
        if pk == "pool-dst":
            return target_pool
        return None

    with patch("app.storage.archive_service.async_session_maker") as mock_session:
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(side_effect=lambda cls, pk: {
            "sched-1": sched, "pool-src": source_pool, "pool-dst": target_pool
        }.get(pk))
        mock_db.execute = AsyncMock(return_value=MagicMock())
        mock_db.commit = AsyncMock()
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        await service._run_backup("sched-1")

    assert sched.last_run_status == "failed"
    assert "not mounted" in sched.last_run_message
