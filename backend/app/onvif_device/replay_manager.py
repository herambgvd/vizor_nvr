# =============================================================================
# Replay Session Manager — manages per-session ffmpeg processes that push
# time-shifted MP4 segments to go2rtc as RTSP streams.
# =============================================================================
# Session lifecycle:
#   start_session(stream_id, file_path, offset_seconds)
#       → spawns ffmpeg, registers session
#   touch_session(stream_id)
#       → updates last_accessed (keep-alive from VMS client)
#   evict_idle()
#       → kills sessions idle for > IDLE_TIMEOUT_SECS
# Background task (run from lifespan) calls evict_idle() every 60 s.
# Hard cap: MAX_SESSIONS concurrent sessions (LRU eviction).
# Hard timeout: HARD_TIMEOUT_SECS (30 min) per session regardless of activity.
# =============================================================================

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger(__name__)

MAX_SESSIONS           = 8
IDLE_TIMEOUT_SECS      = 5 * 60    # 5 minutes idle → evict (overridden by persisted setting)
HARD_TIMEOUT_SECS      = 30 * 60   # 30 minutes absolute hard limit
DEFAULT_SESSION_TIMEOUT = 300      # seconds — fallback when DB setting absent

GO2RTC_INTERNAL_HOST = os.getenv("GO2RTC_INTERNAL_HOST", "go2rtc")
GO2RTC_RTSP_PORT     = int(os.getenv("GO2RTC_RTSP_PORT", "8554"))


@dataclass
class ReplaySession:
    stream_id:     str
    file_path:     str
    offset_seconds: float
    speed_factor:   float
    process:       asyncio.subprocess.Process
    started_at:    datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_accessed: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def is_alive(self) -> bool:
        return self.process.returncode is None

    def idle_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.last_accessed).total_seconds()

    def age_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.started_at).total_seconds()


class ReplayManager:
    """Singleton that manages ffmpeg replay sessions."""

    def __init__(self):
        self._sessions: Dict[str, ReplaySession] = {}
        self._lock = asyncio.Lock()
        self._eviction_task: Optional[asyncio.Task] = None
        # Idle timeout may be overridden by SetReplayConfiguration
        self._session_timeout_secs: int = DEFAULT_SESSION_TIMEOUT

    async def _load_session_timeout(self):
        """Read persisted replay session timeout from settings DB."""
        try:
            from app.database import async_session_maker
            from app.settings.service import SettingsService
            async with async_session_maker() as db:
                val = await SettingsService.get_value(db, "replay_session_timeout_seconds", None)
                if val is not None:
                    self._session_timeout_secs = int(val)
        except Exception as e:
            logger.debug(f"ReplayManager: could not load session timeout: {e}")

    async def get_session_timeout(self) -> int:
        """Return current session timeout in seconds (from DB or default)."""
        await self._load_session_timeout()
        return self._session_timeout_secs

    async def set_session_timeout(self, seconds: int):
        """Persist and activate a new session timeout."""
        self._session_timeout_secs = seconds
        try:
            from app.database import async_session_maker
            from app.settings.service import SettingsService
            async with async_session_maker() as db:
                await SettingsService.set_value(
                    db, "replay_session_timeout_seconds", str(seconds), category="replay"
                )
                await db.commit()
        except Exception as e:
            logger.warning(f"ReplayManager: could not persist session timeout: {e}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start_eviction_loop(self):
        """Start the background eviction loop. Called from lifespan startup."""
        if self._eviction_task and not self._eviction_task.done():
            return
        self._eviction_task = asyncio.create_task(self._eviction_loop(), name="replay_eviction")
        logger.info("ReplayManager: eviction loop started")

    async def stop_eviction_loop(self):
        """Stop the background eviction loop. Called from lifespan shutdown."""
        if self._eviction_task and not self._eviction_task.done():
            self._eviction_task.cancel()
            try:
                await self._eviction_task
            except asyncio.CancelledError:
                pass
        # Kill all remaining sessions
        async with self._lock:
            for sess in list(self._sessions.values()):
                await self._kill_session(sess)
            self._sessions.clear()
        logger.info("ReplayManager: shutdown complete")

    async def _eviction_loop(self):
        while True:
            await asyncio.sleep(60)
            try:
                await self.evict_idle()
            except Exception as e:
                logger.warning(f"ReplayManager eviction error: {e}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start_session(
        self,
        stream_id: str,
        file_path: str,
        offset_seconds: float,
        speed_factor: float = 1.0,
    ) -> bool:
        """
        Spawn an ffmpeg process that reads the MP4 at offset_seconds and pushes
        to go2rtc via RTSP. Returns True if session was successfully started.
        If a session with the same stream_id already exists and is alive, it is
        reused (and touched).

        speed_factor: 1.0 = real-time (copy); 0.25–4.0 = speed change (re-encode).
        """
        # Load the persisted session timeout on each new session creation
        await self._load_session_timeout()

        async with self._lock:
            # Reuse existing live session
            if stream_id in self._sessions:
                sess = self._sessions[stream_id]
                if sess.is_alive():
                    sess.last_accessed = datetime.now(timezone.utc)
                    logger.debug(f"ReplayManager: reusing session {stream_id}")
                    return True
                else:
                    del self._sessions[stream_id]

            # Enforce capacity limit — LRU evict
            if len(self._sessions) >= MAX_SESSIONS:
                await self._evict_lru()

            rtsp_push_url = f"rtsp://{GO2RTC_INTERNAL_HOST}:{GO2RTC_RTSP_PORT}/{stream_id}"

            # Cap speed_factor to safe bounds
            speed_factor = max(0.25, min(4.0, speed_factor))

            # Build ffmpeg command
            # -re: read at native rate (prevent flooding go2rtc)
            # -ss before -i: fast seek (keyframe-accurate is fine for replay)
            if abs(speed_factor - 1.0) < 0.01:
                # Fast path: stream copy (no re-encode)
                cmd = [
                    "ffmpeg",
                    "-nostdin",
                    "-loglevel", "warning",
                    "-ss", str(offset_seconds),
                    "-i", file_path,
                    "-c", "copy",
                    "-f", "rtsp",
                    "-rtsp_transport", "tcp",
                    rtsp_push_url,
                ]
                logger.info(
                    f"ReplayManager: spawning ffmpeg for {stream_id} offset={offset_seconds:.1f}s "
                    f"speed=1.0 (copy) → {rtsp_push_url}"
                )
            else:
                # Re-encode path with setpts filter for speed change.
                # Audio is dropped when changing speed (spec allows; avoids pitch issues).
                # Use hwaccel encoder if available.
                try:
                    from app.services.hwaccel_probe import pick_encoder
                    encoder_flags = pick_encoder("h264")
                except Exception:
                    encoder_flags = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23"]

                cmd = [
                    "ffmpeg",
                    "-nostdin",
                    "-loglevel", "warning",
                    "-ss", str(offset_seconds),
                    "-i", file_path,
                    "-vf", f"setpts=PTS/{speed_factor:.4f}",
                    *encoder_flags,
                    "-an",  # drop audio during speed change
                    "-f", "rtsp",
                    "-rtsp_transport", "tcp",
                    rtsp_push_url,
                ]
                logger.info(
                    f"ReplayManager: spawning ffmpeg for {stream_id} offset={offset_seconds:.1f}s "
                    f"speed={speed_factor:.2f}x (re-encode: {encoder_flags[1]}) → {rtsp_push_url}"
                )
            logger.info(f"ReplayManager: spawning ffmpeg for {stream_id} offset={offset_seconds:.1f}s → {rtsp_push_url}")

            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
            except Exception as e:
                logger.error(f"ReplayManager: failed to spawn ffmpeg for {stream_id}: {e}")
                return False

            sess = ReplaySession(
                stream_id=stream_id,
                file_path=file_path,
                offset_seconds=offset_seconds,
                speed_factor=speed_factor,
                process=proc,
            )
            self._sessions[stream_id] = sess
            logger.info(f"ReplayManager: session {stream_id} started (pid={proc.pid})")
            return True

    def touch_session(self, stream_id: str):
        """Update last_accessed for a session (extend idle timer)."""
        sess = self._sessions.get(stream_id)
        if sess:
            sess.last_accessed = datetime.now(timezone.utc)

    async def evict_idle(self):
        """Kill sessions that have been idle > session_timeout or exceeded HARD_TIMEOUT_SECS."""
        idle_timeout = self._session_timeout_secs  # may be updated by SetReplayConfiguration
        async with self._lock:
            to_evict = []
            for sid, sess in self._sessions.items():
                if not sess.is_alive():
                    to_evict.append(sid)
                elif sess.idle_seconds() > idle_timeout:
                    to_evict.append(sid)
                    logger.info(f"ReplayManager: evicting idle session {sid}")
                elif sess.age_seconds() > HARD_TIMEOUT_SECS:
                    to_evict.append(sid)
                    logger.info(f"ReplayManager: evicting expired session {sid} (hard timeout)")
            for sid in to_evict:
                sess = self._sessions.pop(sid, None)
                if sess:
                    await self._kill_session(sess)

    def get_session_info(self) -> list:
        """Return a summary list of active sessions (for diagnostics)."""
        result = []
        for sid, sess in self._sessions.items():
            result.append({
                "stream_id": sid,
                "file_path": sess.file_path,
                "offset_seconds": sess.offset_seconds,
                "speed_factor": sess.speed_factor,
                "alive": sess.is_alive(),
                "idle_seconds": round(sess.idle_seconds()),
                "age_seconds": round(sess.age_seconds()),
            })
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _evict_lru(self):
        """Evict the least recently used session (caller must hold lock)."""
        if not self._sessions:
            return
        lru_id = min(self._sessions, key=lambda sid: self._sessions[sid].last_accessed)
        sess = self._sessions.pop(lru_id)
        logger.info(f"ReplayManager: LRU evicting {lru_id} to make room")
        await self._kill_session(sess)

    async def _kill_session(self, sess: ReplaySession):
        """Terminate an ffmpeg process gracefully then forcibly."""
        proc = sess.process
        if proc.returncode is not None:
            return  # already dead
        try:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
            logger.debug(f"ReplayManager: killed session {sess.stream_id} (pid={proc.pid})")
        except Exception as e:
            logger.warning(f"ReplayManager: error killing session {sess.stream_id}: {e}")


# Module-level singleton
replay_manager = ReplayManager()
