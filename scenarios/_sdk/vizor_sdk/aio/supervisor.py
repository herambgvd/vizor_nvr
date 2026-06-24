"""Async camera supervisor — one asyncio task per camera, with a watchdog.

The shared, scenario-agnostic worker core ported from vizor-gpu's BaseWorker,
adapted to vizor-nvr (no Redis): cameras come from the HTTP reconcile loop, events
go to an AsyncEventWriter (Postgres + spool), decode is GStreamer (PyAV fallback).

A scenario supplies a `Pipeline`:
    pipeline = make_pipeline(camera)          # one per camera, holds its state
    events   = pipeline.process(frame)        # SYNC; returns list[dict] events
    pipeline.close()                          # optional cleanup
and an `EventSink` (callable taking one event dict). The supervisor owns:
  * one task per camera: `async for frame: events = to_thread(process); submit each`
  * a per-camera last_frame_at liveness stamp + a watchdog that restarts a task
    that stops yielding frames (pipeline-side wedge the byte-watchdog can't see)
  * graceful start/stop/update from the reconcile diff, under a lock so a config
    change can't race a watchdog restart.

Runs on a DEDICATED asyncio loop thread (see run_supervisor_thread) so a wedged
camera can never stall the FastAPI request loop.
"""
from __future__ import annotations

import asyncio
import gc
import logging
import os
import threading
import time
from typing import Any, Callable, Optional

from .event_sink import AsyncEventWriter, EventSink
from .frame_source import build_frame_source

logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


# Coarse safety net only. The GStreamer frame source self-heals on stream errors
# with its OWN exponential backoff (1→2→…→30s). If this watchdog fired sooner it
# would tear down the source mid-backoff and reset it — the two restart paths
# thrash, which on a high-bitrate camera looks like a permanent restart loop. Keep
# the watchdog window comfortably above the in-pipeline max backoff (30s) so it
# only intervenes when the source is truly wedged, not merely reconnecting.
_WATCHDOG_STALE_S = _env_float("VIZOR_WATCHDOG_STALE_S", 90.0)
_WATCHDOG_PERIOD_S = _env_float("VIZOR_WATCHDOG_PERIOD_S", 15.0)
_GC_EVERY_N = 300


class Pipeline:
    """Scenario pipeline contract. process() is SYNC (run off-loop via to_thread)
    and returns a list of event dicts (may be empty)."""

    def process(self, frame) -> list[dict]:  # noqa: D401
        raise NotImplementedError

    def close(self) -> None:
        return None


class CameraSupervisor:
    """One per scenario process. Manages per-camera asyncio tasks + a watchdog.
    Cross-thread queries (status/logs) read plain dicts, safe from any thread."""

    def __init__(self, *, name: str, make_pipeline: Callable[[dict], Pipeline],
                 sink: EventSink, rtsp_url_for: Callable[[str], str],
                 spool_dir: str,
                 on_state: Optional[Callable[[dict, str, Optional[str]], None]] = None) -> None:
        self.name = name
        self._make_pipeline = make_pipeline
        self._rtsp_url_for = rtsp_url_for
        # Optional state-report hook: on_state(cam_dict, state, error). The scenario
        # uses it to push stream_state (starting/running/stopped/error) back to the NVR
        # so the Cameras tab shows the real worker status.
        self._on_state = on_state
        self._writer = AsyncEventWriter(name, sink, spool_dir=spool_dir)
        self._tasks: dict[str, asyncio.Task] = {}
        self._cams: dict[str, dict] = {}                 # camera_id -> config dict
        self._cfg_sig: dict[str, str] = {}
        self._last_frame_at: dict[str, float] = {}
        self._frames: dict[str, int] = {}
        self._violations: dict[str, int] = {}
        self._states: dict[str, str] = {}                # running/stopped/error
        self._logs: dict[str, list] = {}                 # camera_id -> recent lines
        self._pipelines: dict[str, Pipeline] = {}
        self._lock = asyncio.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._watchdog: Optional[asyncio.Task] = None

    def _set_state(self, cid: str, state: str, error: Optional[str] = None) -> None:
        """Record a camera's state and fire the optional NVR report hook (off the
        loop, so a slow HTTP report never blocks decode)."""
        self._states[cid] = state
        if self._on_state is not None:
            cam = self._cams.get(cid)
            if cam is not None:
                try:
                    self._on_state(cam, state, error)
                except Exception:  # noqa: BLE001 — reporting must never break the worker
                    pass

    # ── lifecycle (called from the reconcile loop, ON the supervisor loop) ────
    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._watchdog = asyncio.create_task(self._watchdog_loop(), name=f"{self.name}-watchdog")

    async def reconcile(self, cameras: list[dict]) -> None:
        """Diff the desired camera set against running tasks; start/stop/update."""
        desired = {str(c.get("camera_id")): c for c in cameras if c.get("camera_id")}
        async with self._lock:
            # stop removed
            for cid in list(self._tasks):
                if cid not in desired:
                    await self._stop_locked(cid)
            # start / update
            for cid, cam in desired.items():
                sig = _cfg_sig(cam.get("config"))
                if cid in self._tasks and self._tasks[cid].done() is False:
                    if self._cfg_sig.get(cid) != sig:
                        await self._stop_locked(cid)
                        await self._start_locked(cid, cam, sig)
                else:
                    await self._start_locked(cid, cam, sig)

    async def _start_locked(self, cid: str, cam: dict, sig: str) -> None:
        self._cams[cid] = cam
        self._cfg_sig[cid] = sig
        self._frames.setdefault(cid, 0)
        self._violations.setdefault(cid, 0)
        self._last_frame_at[cid] = time.monotonic()
        self._set_state(cid, "starting")
        self._log(cid, "info", "Starting worker")
        self._pipelines[cid] = self._make_pipeline(cam)
        self._tasks[cid] = asyncio.create_task(self._camera_task(cid), name=f"{self.name}-cam-{cid[:8]}")

    async def _stop_locked(self, cid: str) -> None:
        t = self._tasks.pop(cid, None)
        if t and not t.done():
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        p = self._pipelines.pop(cid, None)
        if p:
            try:
                p.close()
            except Exception:  # noqa: BLE001
                pass
        self._set_state(cid, "stopped")
        self._log(cid, "info", "Stopped worker")

    # ── per-camera task ───────────────────────────────────────────────────────
    async def _camera_task(self, cid: str) -> None:
        cam = self._cams[cid]
        fps = int((cam.get("config") or {}).get("fps", 5))
        rtsp = self._rtsp_url_for(cid)
        pipeline = self._pipelines[cid]
        source = build_frame_source(rtsp, fps=fps)
        self._set_state(cid, "running")
        self._log(cid, "info", f"Stream running ({source.backend}, fps={fps})")
        frame_no = 0
        try:
            async for frame in source.frames():
                frame_no += 1
                self._frames[cid] = frame_no
                self._last_frame_at[cid] = time.monotonic()
                try:
                    events = await asyncio.to_thread(pipeline.process, frame)
                except Exception as e:  # noqa: BLE001 — one bad frame must not kill the cam
                    if frame_no % 50 == 0:
                        self._log(cid, "error", f"Frame error: {str(e)[:120]}")
                    events = None
                if events:
                    for ev in events:
                        self._writer.submit(ev)
                        self._violations[cid] = self._violations.get(cid, 0) + 1
                        self._log(cid, "warn", ev.get("_log") or f"Event: {ev.get('event_type','?')}")
                if frame_no % 100 == 0:
                    self._log(cid, "info",
                              f"Analysing — frames={frame_no} violations={self._violations.get(cid,0)}")
                del frame
                if frame_no % _GC_EVERY_N == 0:
                    gc.collect()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            self._set_state(cid, "error", str(e)[:200])
            self._log(cid, "error", f"Camera task crashed: {str(e)[:160]}")
            logger.exception("[%s] camera %s crashed", self.name, cid)
        finally:
            try:
                await source.close()
            except Exception:  # noqa: BLE001
                pass

    # ── watchdog ──────────────────────────────────────────────────────────────
    async def _watchdog_loop(self) -> None:
        while True:
            await asyncio.sleep(_WATCHDOG_PERIOD_S)
            now = time.monotonic()
            async with self._lock:
                for cid in list(self._tasks):
                    t = self._tasks.get(cid)
                    stale = now - self._last_frame_at.get(cid, now) > _WATCHDOG_STALE_S
                    dead = t is None or t.done()
                    if (dead or stale) and cid in self._cams:
                        self._log(cid, "warn", "Watchdog: restarting stale/dead worker")
                        logger.warning("[%s] watchdog restart camera %s (stale=%s dead=%s)",
                                       self.name, cid, stale, dead)
                        cam, sig = self._cams[cid], self._cfg_sig.get(cid, "")
                        await self._stop_locked(cid)
                        await self._start_locked(cid, cam, sig)

    # ── introspection (thread-safe plain-dict reads) ─────────────────────────
    def _log(self, cid: str, level: str, msg: str) -> None:
        buf = self._logs.setdefault(cid, [])
        buf.append({"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
                    "level": level, "msg": msg})
        if len(buf) > 80:
            del buf[:-80]

    def status(self) -> dict:
        now = time.monotonic()
        active = sum(1 for cid in self._tasks
                     if (now - self._last_frame_at.get(cid, 0)) < 60.0)
        return {"expected": len(self._tasks), "alive": len(self._tasks),
                "active": active, "writer": self._writer.stats()}

    def camera_logs(self, cid: str) -> dict:
        now = time.monotonic()
        running = cid in self._tasks and not self._tasks[cid].done()
        last = self._last_frame_at.get(cid, 0)
        stats = {
            "frames": self._frames.get(cid, 0),
            "persons_last": None,
            "violations_total": self._violations.get(cid, 0),
            "fps": (self._cams.get(cid, {}).get("config") or {}).get("fps"),
            "last_frame_secs_ago": round(now - last, 1) if last else None,
        }
        # Let the scenario pipeline contribute its own counters (e.g. FRS faces /
        # recognized) so the worker-logs panel shows meaningful numbers.
        p = self._pipelines.get(cid)
        if p is not None and hasattr(p, "stats"):
            try:
                stats.update(p.stats() or {})
            except Exception:  # noqa: BLE001
                pass
        return {
            "camera_id": cid, "running": running,
            "active": running and (now - last) < 60.0,
            "stats": stats,
            "logs": list(self._logs.get(cid, [])),
        }

    async def stop_all(self) -> None:
        async with self._lock:
            for cid in list(self._tasks):
                await self._stop_locked(cid)
        if self._watchdog:
            self._watchdog.cancel()


def _cfg_sig(config: Any) -> str:
    import json
    try:
        return json.dumps(config or {}, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001
        return str(config)


# ── dedicated loop thread + HTTP reconcile driver ────────────────────────────
def run_supervisor_thread(supervisor: CameraSupervisor, *, fetch_cameras: Callable[[], list[dict]],
                          poll_secs: float = 5.0) -> threading.Thread:
    """Spawn a daemon thread that owns a fresh asyncio loop, starts the supervisor,
    and runs an HTTP reconcile loop (calls fetch_cameras() each poll, feeds the diff
    to supervisor.reconcile). Returns the thread. Isolated from uvicorn's loop."""

    def _main() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _run() -> None:
            await supervisor.start()
            while True:
                try:
                    cams = await asyncio.to_thread(fetch_cameras)
                    await supervisor.reconcile(cams)
                except Exception as e:  # noqa: BLE001 — reconcile must never die
                    logger.warning("[%s] reconcile failed: %s", supervisor.name, e)
                await asyncio.sleep(poll_secs)

        try:
            loop.run_until_complete(_run())
        except Exception:  # noqa: BLE001
            logger.exception("[%s] supervisor loop crashed", supervisor.name)

    th = threading.Thread(target=_main, name=f"{supervisor.name}-supervisor", daemon=True)
    th.start()
    return th
