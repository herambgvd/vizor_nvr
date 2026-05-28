# =============================================================================
# FFmpeg Watchdog — process health loop
# Extracted from ffmpeg_manager.py for maintainability.
#
# This module is NOT meant to be used standalone — it is imported by
# FFmpegManager and the methods are injected via mixin or direct delegation.
# =============================================================================

import asyncio
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.ffmpeg_manager import FFmpegManager

from app.config import settings

logger = logging.getLogger(__name__)


async def watchdog_loop(manager: "FFmpegManager") -> None:
    """Poll every manager._watchdog_interval seconds.

    Two failure modes:
    1. Dead PID — stderr reader should already fire restart, but if it
       somehow missed, the watchdog kicks one off.
    2. Hung PID — process alive but ``last_health`` older than
       stall_factor * segment_duration.  Force-kill so stderr-reader →
       _auto_restart fires.
    """
    while not manager._shutting_down:
        try:
            await asyncio.sleep(manager._watchdog_interval)
            if manager._shutting_down:
                break
            now = time.time()
            for camera_id, ff in list(manager._processes.items()):
                if camera_id in manager._stopped or camera_id in manager._failed_cameras:
                    continue
                rc = ff.process.returncode
                if rc is not None:
                    if (
                        settings.FFMPEG_RECOVERY_ENABLED
                        and ff.stderr_task
                        and ff.stderr_task.done()
                    ):
                        logger.warning(
                            f"[{camera_id}] Watchdog detected dead PID {ff.pid} "
                            f"(rc={rc}) — scheduling restart"
                        )
                        asyncio.create_task(manager._auto_restart(ff))
                    continue
                stall_threshold = max(60, ff.segment_duration * manager._stall_factor)
                if now - ff.last_health > stall_threshold:
                    stall_age = int(now - ff.last_health)
                    logger.warning(
                        f"[{camera_id}] Watchdog: FFmpeg hung "
                        f"(no segment for {stall_age}s, PID {ff.pid}) — force-killing"
                    )
                    try:
                        ff.process.kill()
                    except ProcessLookupError:
                        pass
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Watchdog loop error: {e}")
