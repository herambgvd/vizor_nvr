"""BaseWorker — abstract base for nvr AI use-case workers (ported from vizor-gpu,
single-tenant).

Every concrete scenario (FRS, PPE) subclasses `BaseWorker`, implements
`process_frame`, and launches via `await worker.run()`.

## Architecture

The control plane is a Redis Stream (`ai:{use_case}:control`) read via a consumer
group, so a crashed worker resumes from its last acknowledged ID and never loses a
command.

    Control plane ──XADD──▶ ai:{use_case}:control ──XREADGROUP──▶ Worker
                                                                    ├ start_camera → spawn task per device
                                                                    ├ stop_camera  → cancel task
                                                                    ├ update_config→ on_config_update()
                                                                    └ reload       → restart all tasks

    Worker ──XADD──▶ ai:events               (detections; an events bridge maps
                                              these onto nvr's record_event())
    Worker ──XADD──▶ ai:{use_case}:status    (heartbeat every 15s)

Why this exists: nvr's previous live path could wedge when Triton stalled (HTTP
infer with no timeout). This framework uses gRPC + hard-timeout infer, a watchdog
that restarts silent cameras, and a Redis event bus with disk-spool fallback so
events never break.

## Implementing a use-case

```python
class MyWorker(BaseWorker):
    use_case = "frs"
    async def process_frame(self, cmd, frame):
        yield Event(...)
```
"""
from __future__ import annotations

import abc
import asyncio
import json
import logging
import os
import signal
import socket
import uuid
from typing import Any, AsyncIterator

import redis.asyncio as aioredis

from .protocol import Command, Event, Status

logger = logging.getLogger("vizor.worker")

EVENTS_STREAM = "ai:events"
HEARTBEAT_INTERVAL_SECONDS = 15.0
CONTROL_BLOCK_MS = 5_000
DLQ_MAX_LEN = 10_000
STATUS_MAX_LEN = 10_000
EVENTS_MAX_LEN = 100_000


def control_stream(use_case: str) -> str:
    return f"ai:{use_case}:control"


def status_stream(use_case: str) -> str:
    return f"ai:{use_case}:status"


def dlq_stream(use_case: str) -> str:
    return f"ai:{use_case}:control:dlq"


class BaseWorker(abc.ABC):
    """Abstract base for AI workers.

    Subclass contract:
        class_attr  use_case  (str)    — required
        async def process_frame(cmd, frame) -> AsyncIterator[Event]   — required
        async def on_config_update(cmd) -> None                        — optional

    Lifecycle:
        worker = MyWorker(redis_url="redis://ai-redis:6379/0")
        await worker.run()             # blocks until SIGTERM/SIGINT
    """

    use_case: str = ""
    #: 0 == unbounded. WORKER_MAX_CAMERAS env overrides.
    max_cameras: int = 0

    def __init__(
        self,
        redis_url: str,
        worker_id: str | None = None,
        consumer_group: str | None = None,
        heartbeat_interval: float = HEARTBEAT_INTERVAL_SECONDS,
        redis_client: aioredis.Redis | None = None,
    ):
        if not self.use_case:
            raise ValueError("Subclass must set `use_case` class attribute")

        self.redis_url = redis_url
        # STABLE consumer id (hostname only, no pid/uuid) so a worker restart resumes
        # the SAME consumer and re-reads its pending control Commands. With a random
        # id per restart, each restart spawned a fresh consumer and the previously
        # delivered start_camera Commands stayed parked on the now-dead consumer's
        # PEL — the new worker saw lag=0 and started no cameras.
        self.worker_id = worker_id or f"{self.use_case}-{socket.gethostname()}"
        self.consumer_group = consumer_group or f"{self.use_case}-workers"
        self.heartbeat_interval = heartbeat_interval

        self._redis: aioredis.Redis = redis_client or aioredis.from_url(
            redis_url, decode_responses=True)

        self._control = control_stream(self.use_case)
        self._status = status_stream(self.use_case)

        self._camera_tasks: dict[str, asyncio.Task] = {}
        self._camera_cmds: dict[str, Command] = {}
        # Serializes all camera lifecycle mutations so the watchdog and the control
        # loop can't race a cancel against a restart.
        self._cam_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()

        # Local event spool — disk fallback for emit() when Redis is unreachable.
        from .event_spool import EventSpool
        self._spool = EventSpool(self.use_case)
        self._spool_replay_task: asyncio.Task | None = None

        # Watchdog liveness: last monotonic ts a camera task yielded a frame.
        self._last_frame_at: dict[str, float] = {}
        self._watchdog_task: asyncio.Task | None = None

        self._warmup_done = False
        self._warmup_ok = False

        from .observability import WorkerMetrics
        self._metrics = WorkerMetrics(self.use_case)

        # Inference gateway — lazy. Concrete workers expose a Triton client at
        # self._triton; _get_inference() wraps it (coalesce + adaptive skip).
        self._inference = None

    # ── subclass hooks ─────────────────────────────────────────────────────
    @abc.abstractmethod
    async def process_frame(self, cmd: Command, frame: Any) -> AsyncIterator[Event]:
        """Inference entry point. Yield zero or more Events per frame. `cmd` is the
        most recent start/update Command for the device; `frame` is a numpy BGR
        array from the frame source."""
        if False:  # pragma: no cover - satisfies AsyncIterator typing
            yield

    async def on_config_update(self, cmd: Command) -> None:
        """Swap the cached Command so subsequent process_frame sees new config."""
        self._camera_cmds[cmd.device_id] = cmd

    def _on_loop_lag_sample(self, lag_s: float) -> None:
        gw = self._inference
        if gw is not None:
            try:
                gw.update_loop_lag(lag_s)
            except Exception:
                pass

    def _get_inference(self):
        gw = self._inference
        if gw is None:
            triton = getattr(self, "_triton", None) or getattr(self, "triton", None)
            if triton is None:
                return None
            from .inference_gateway import InferenceGateway
            gw = InferenceGateway(triton, metrics=self._metrics)
            self._inference = gw
        return gw

    async def on_warmup(self) -> None:
        """Optional: pre-load models / dummy infer. Failures logged, not raised."""
        return None

    async def wait_for_models(
        self, triton, models: list[str], *,
        timeout_s: float = 180.0, poll_interval_s: float = 3.0,
    ) -> set[str]:
        """Poll Triton until each model is ready or timeout. Returns ready set."""
        deadline = asyncio.get_running_loop().time() + max(0.0, timeout_s)
        remaining = set(models)
        ready: set[str] = set()
        while remaining and asyncio.get_running_loop().time() < deadline:
            for name in list(remaining):
                try:
                    if await triton.model_ready(name):
                        ready.add(name)
                        remaining.discard(name)
                except Exception:  # noqa: BLE001
                    pass
            if not remaining:
                break
            await asyncio.sleep(poll_interval_s)
        if remaining:
            logger.warning("[%s] wait_for_models timed out after %ss; still missing: %s",
                           self.use_case, timeout_s, sorted(remaining))
        return ready

    async def on_shutdown(self) -> None:
        """Optional: release per-pipeline resources. Must not raise."""
        return None

    # ── public entry point ─────────────────────────────────────────────────
    async def run(self) -> None:
        await self._ensure_group()
        self._install_signal_handlers()
        logger.info("[%s] worker started (id=%s, group=%s)",
                    self.use_case, self.worker_id, self.consumer_group)

        self._metrics.start_server()
        try:
            self._metrics.set_lag_observer(self._on_loop_lag_sample)
        except Exception:
            pass
        try:
            self._metrics.start_loop_lag_sampler()
        except Exception:
            pass
        try:
            self._metrics.set_pipeline_health_provider(self._pipeline_health_snapshot)
        except Exception:
            pass

        # Heartbeat BEFORE warmup so the bridge sees the worker alive while it polls
        # Triton for model readiness.
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(), name="heartbeat")
        self._metrics.mark_healthy()

        warmup_ok = True
        try:
            await self.on_warmup()
        except Exception as e:  # noqa: BLE001
            warmup_ok = False
            logger.warning("[%s] warmup hook failed (non-fatal): %s", self.use_case, e)
        self._warmup_ok = warmup_ok
        self._warmup_done = True
        try:
            if hasattr(self._metrics, "warmup_ok"):
                self._metrics.warmup_ok.labels(use_case=self.use_case).set(1.0 if warmup_ok else 0.0)
        except Exception:
            pass

        control_task = asyncio.create_task(self._control_loop(), name="control")
        self._watchdog_task = asyncio.create_task(
            self._watchdog_loop(), name=f"{self.use_case}:watchdog")
        self._spool_replay_task = asyncio.create_task(
            self._spool_replay_loop(), name=f"{self.use_case}:spool-replay")

        try:
            await self._stop_event.wait()
        finally:
            heartbeat_task.cancel()
            control_task.cancel()
            if self._watchdog_task is not None:
                self._watchdog_task.cancel()
            if self._spool_replay_task is not None:
                self._spool_replay_task.cancel()
            for t in (heartbeat_task, control_task, self._watchdog_task,
                      self._spool_replay_task):
                if t is None:
                    continue
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
            await self._shutdown_cameras()
            try:
                await self.on_shutdown()
            except Exception as e:  # noqa: BLE001
                logger.warning("[%s] on_shutdown failed: %s", self.use_case, e)
            self._metrics.mark_unhealthy()
            try:
                self._metrics.stop_loop_lag_sampler()
            except Exception:
                pass
            self._metrics.stop_server()
            try:
                await self._redis.aclose()
            except Exception:
                pass
            logger.info("[%s] worker stopped", self.use_case)

    def stop(self) -> None:
        """Request graceful shutdown (safe from a signal handler)."""
        self._stop_event.set()

    # ── event emission ─────────────────────────────────────────────────────
    async def emit(self, event: Event) -> str:
        """Publish to ai:events. On ANY Redis failure, spool to disk so the event
        isn't lost; _spool_replay_loop drains it once Redis recovers."""
        serialized = event.to_json()
        payload = {"data": serialized}
        try:
            entry_id = await self._redis.xadd(
                EVENTS_STREAM, payload, maxlen=EVENTS_MAX_LEN, approximate=True)
            try:
                self._metrics.events_emitted.labels(use_case=self.use_case).inc()
            except Exception:
                pass
            return entry_id
        except Exception as e:
            await self._spool.append(serialized)
            logger.warning("[%s] emit failed (%s), spooled: %s",
                           self.use_case, type(e).__name__, e)
            try:
                self._metrics.record_error("redis_emit", str(e))
            except Exception:
                pass
            return ""

    async def _spool_replay_loop(self) -> None:
        interval = 30.0
        try:
            while not self._stop_event.is_set():
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
                    return
                except asyncio.TimeoutError:
                    pass
                if self._spool.disabled():
                    return

                async def _replay_one(line: str) -> None:
                    await self._redis.xadd(EVENTS_STREAM, {"data": line},
                                           maxlen=EVENTS_MAX_LEN, approximate=True)
                try:
                    await self._spool.replay(_replay_one)
                except Exception as e:
                    logger.debug("[%s] spool replay deferred: %s", self.use_case, e)
        except asyncio.CancelledError:
            raise

    # ── control plane ──────────────────────────────────────────────────────
    async def _ensure_group(self) -> None:
        try:
            await self._redis.xgroup_create(
                self._control, self.consumer_group, id="0", mkstream=True)
        except aioredis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                return
            raise

    async def _claim_stale(self) -> None:
        """On startup, claim control Commands left pending on OTHER (dead) consumers
        and replay our own pending, so a restarted worker converges to the current
        desired camera set instead of waiting for the next config change. Without
        this, Commands delivered to a previous worker instance were stranded."""
        try:
            start = "0-0"
            while True:
                res = await self._redis.xautoclaim(
                    self._control, self.consumer_group, self.worker_id,
                    min_idle_time=0, start_id=start, count=64)
                # redis-py returns (next_start, claimed, deleted) or (next_start, claimed)
                next_start = res[0]
                claimed = res[1] if len(res) > 1 else []
                for entry_id, fields in claimed:
                    try:
                        await self._dispatch(fields)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("[%s] claim dispatch failed (%s): %s",
                                       self.use_case, entry_id, e)
                    try:
                        await self._redis.xack(self._control, self.consumer_group, entry_id)
                    except Exception:
                        pass
                if not claimed or next_start in ("0-0", "0"):
                    break
                start = next_start
        except Exception as e:  # noqa: BLE001
            logger.debug("[%s] claim_stale skipped: %s", self.use_case, e)

    async def _control_loop(self) -> None:
        # First converge to any already-issued Commands stranded on old consumers.
        await self._claim_stale()
        while not self._stop_event.is_set():
            try:
                resp = await self._redis.xreadgroup(
                    groupname=self.consumer_group, consumername=self.worker_id,
                    streams={self._control: ">"}, count=16, block=CONTROL_BLOCK_MS)
            except asyncio.CancelledError:
                raise
            except (asyncio.TimeoutError, TimeoutError) as e:
                logger.debug("[%s] control read idle: %s", self.use_case, e)
                continue
            except Exception as e:
                if "Timeout reading from" in str(e):
                    logger.debug("[%s] control read idle: %s", self.use_case, e)
                    continue
                logger.exception("[%s] xreadgroup failed: %s", self.use_case, e)
                await asyncio.sleep(1.0)
                continue

            if not resp:
                continue
            for _stream, entries in resp:
                for entry_id, fields in entries:
                    failed = False
                    err_text: str | None = None
                    try:
                        await self._dispatch(fields)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:  # noqa: BLE001
                        failed = True
                        err_text = repr(e)
                        logger.exception("[%s] command dispatch failed (%s): %s",
                                         self.use_case, entry_id, e)
                    if failed:
                        try:
                            self._metrics.commands_dlq.labels(use_case=self.use_case).inc()
                        except Exception:
                            pass
                        try:
                            dlq_fields = {
                                "original_id": str(entry_id),
                                "error": err_text or "unknown",
                                "use_case": self.use_case,
                                "worker_id": self.worker_id,
                            }
                            for k, v in (fields or {}).items():
                                dlq_fields[f"orig_{k}"] = (
                                    v if isinstance(v, (str, bytes)) else json.dumps(v))
                            await self._redis.xadd(
                                dlq_stream(self.use_case), dlq_fields,
                                maxlen=DLQ_MAX_LEN, approximate=True)
                        except Exception as dlq_err:  # noqa: BLE001
                            logger.exception("[%s] DLQ write failed for %s: %s",
                                             self.use_case, entry_id, dlq_err)
                    try:
                        await self._redis.xack(self._control, self.consumer_group, entry_id)
                    except Exception:
                        pass

    async def _dispatch(self, fields: dict[str, str]) -> None:
        raw = fields.get("payload") or fields.get("data") or fields.get("command")
        if not raw:
            raw = json.dumps(fields)
        cmd = Command.from_json(raw)
        try:
            self._metrics.commands_dispatched.labels(
                use_case=self.use_case, kind=cmd.action).inc()
        except Exception:
            pass

        if cmd.action == "start_camera":
            await self._handle_start(cmd)
        elif cmd.action == "stop_camera":
            await self._handle_stop(cmd)
        elif cmd.action == "update_config":
            await self._handle_update(cmd)
        elif cmd.action == "reload":
            await self._handle_reload(cmd)
        else:  # pragma: no cover
            logger.warning("[%s] unknown action: %s", self.use_case, cmd.action)
        try:
            self._metrics.active_cameras.labels(use_case=self.use_case).set(
                float(len(self._camera_tasks)))
        except Exception:
            pass

    def _max_cameras(self) -> int:
        try:
            env = os.environ.get("WORKER_MAX_CAMERAS")
            if env is not None:
                return int(env)
        except ValueError:
            pass
        return int(self.max_cameras or 0)

    async def _handle_start(self, cmd: Command) -> None:
        async with self._cam_lock:
            await self._start_locked(cmd)

    async def _start_locked(self, cmd: Command) -> None:
        """Start a camera. CALLER MUST HOLD self._cam_lock."""
        if cmd.device_id in self._camera_tasks:
            logger.info("[%s] device %s already running; restarting",
                        self.use_case, cmd.device_id)
            await self._cancel_camera(cmd.device_id)
        else:
            cap = self._max_cameras()
            if cap > 0 and len(self._camera_tasks) >= cap:
                logger.error("[%s] camera limit reached (%d/%d); rejecting %s",
                             self.use_case, len(self._camera_tasks), cap, cmd.device_id)
                try:
                    self._metrics.record_error(
                        "camera_limit", f"limit {cap} reached, rejected {cmd.device_id}")
                except Exception:
                    pass
                return
        self._camera_cmds[cmd.device_id] = cmd
        task = asyncio.create_task(
            self._camera_task(cmd), name=f"{self.use_case}:{cmd.device_id}")
        prev = self._camera_tasks.get(cmd.device_id)
        if prev is not None and prev is not task and not prev.done():
            prev.cancel()
        self._camera_tasks[cmd.device_id] = task

    async def _handle_stop(self, cmd: Command) -> None:
        async with self._cam_lock:
            await self._cancel_camera(cmd.device_id)
            self._camera_cmds.pop(cmd.device_id, None)
        try:
            await self.on_camera_stopped(cmd.device_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("[%s] on_camera_stopped hook failed for %s: %s",
                           self.use_case, cmd.device_id, e)

    async def on_camera_stopped(self, device_id: str) -> None:
        """Subclass hook — release per-device state."""
        return None

    async def _handle_update(self, cmd: Command) -> None:
        await self.on_config_update(cmd)

    async def _handle_reload(self, cmd: Command) -> None:
        async with self._cam_lock:
            existing = list(self._camera_cmds.values())
            for device_id in list(self._camera_tasks.keys()):
                await self._cancel_camera(device_id)
            for prev in existing:
                await self._start_locked(prev)

    async def _cancel_camera(self, device_id: str) -> None:
        task = self._camera_tasks.pop(device_id, None)
        if not task:
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    async def _shutdown_cameras(self) -> None:
        for device_id in list(self._camera_tasks.keys()):
            await self._cancel_camera(device_id)

    # ── camera task ────────────────────────────────────────────────────────
    async def _camera_task(self, cmd: Command) -> None:
        """Default per-camera driver. Builds a FrameSource and drives
        process_frame -> emit per frame, stamping watchdog liveness."""
        from .frame_source import build_frame_source

        if not cmd.rtsp_url:
            logger.warning("[%s] start_camera without rtsp_url for device %s",
                           self.use_case, cmd.device_id)
            return

        fps = int(cmd.config.get("fps", 5))
        source = build_frame_source(cmd.rtsp_url, fps=fps)
        try:
            import time as _time
            import gc as _gc
            frame_count = 0
            GC_EVERY_N_FRAMES = 300
            async for frame in source.frames():
                live = self._camera_cmds.get(cmd.device_id, cmd)
                async for event in self.process_frame(live, frame):
                    await self.emit(event)
                self._last_frame_at[cmd.device_id] = _time.monotonic()
                try:
                    self._metrics.frames_processed.labels(
                        use_case=self.use_case, camera_id=cmd.device_id).inc()
                except Exception:
                    pass
                del frame
                frame_count += 1
                if frame_count % GC_EVERY_N_FRAMES == 0:
                    _gc.collect()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("[%s] camera task %s crashed: %s",
                             self.use_case, cmd.device_id, e)
        finally:
            try:
                await source.close()
            except Exception:
                pass
            try:
                import gc as _gc_exit
                _gc_exit.collect()
            except Exception:
                pass

    # ── watchdog ───────────────────────────────────────────────────────────
    def _pipeline_health_snapshot(self) -> dict:
        """Per-camera health for the metrics HTTP server. Read-only; called from
        the metrics thread, not the loop."""
        import time as _time
        try:
            stale_threshold = float(os.environ.get("WORKER_WATCHDOG_STALE_S", "30"))
        except (TypeError, ValueError):
            stale_threshold = 30.0
        now = _time.monotonic()
        out: dict[str, dict] = {}
        for device_id, task in dict(self._camera_tasks).items():
            last = self._last_frame_at.get(device_id)
            age = (now - last) if last is not None else None
            stale = age is not None and stale_threshold > 0 and age > stale_threshold
            out[device_id] = {
                "task_done": bool(task.done()) if task is not None else True,
                "last_frame_age_s": (round(age, 2) if age is not None else None),
                "stale": bool(stale),
                "stale_threshold_s": stale_threshold,
            }
        return out

    async def _watchdog_loop(self) -> None:
        """Restart device tasks that stopped yielding frames (stale) or crashed.
        Disabled when WORKER_WATCHDOG_STALE_S=0."""
        import time as _time
        try:
            stale_threshold = float(os.environ.get("WORKER_WATCHDOG_STALE_S", "30"))
        except ValueError:
            stale_threshold = 30.0
        if stale_threshold <= 0:
            return
        check_every = max(1.0, stale_threshold / 3.0)
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=check_every)
                return
            except asyncio.TimeoutError:
                pass
            now = _time.monotonic()
            stale_devices: list[str] = []
            for device_id, task in list(self._camera_tasks.items()):
                last = self._last_frame_at.get(device_id)
                if last is None:
                    self._last_frame_at[device_id] = now
                    continue
                if task.done():
                    stale_devices.append(device_id)
                elif (now - last) > stale_threshold:
                    stale_devices.append(device_id)
            for device_id in stale_devices:
                async with self._cam_lock:
                    if self._stop_event.is_set():
                        break
                    task = self._camera_tasks.get(device_id)
                    last = self._last_frame_at.get(device_id)
                    if task is not None and not task.done():
                        if last is not None and (now - last) <= stale_threshold:
                            continue
                    reason = "crashed" if (task is not None and task.done()) else (
                        f"stale {now - last:.1f}s" if last is not None else "stale")
                    await self._cancel_camera(device_id)
                    self._last_frame_at.pop(device_id, None)
                    cmd = self._camera_cmds.get(device_id)  # re-read under lock
                    if cmd is None or self._stop_event.is_set():
                        continue  # operator stopped it — do not resurrect
                    logger.warning("[%s] watchdog: device %s %s — restarting",
                                   self.use_case, device_id, reason)
                    try:
                        await self._start_locked(cmd)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("[%s] watchdog restart failed for %s: %s",
                                       self.use_case, device_id, e)

    # ── heartbeat ──────────────────────────────────────────────────────────
    def _health_phase(self) -> tuple[bool, str]:
        import time as _time
        if not self._warmup_done:
            return True, "warming"
        if not self._warmup_ok:
            return False, "unhealthy"
        expected = list(self._camera_tasks.keys())
        if not expected:
            return True, "healthy"
        try:
            stale_threshold = float(os.environ.get("WORKER_WATCHDOG_STALE_S", "30"))
        except ValueError:
            stale_threshold = 30.0
        now = _time.monotonic()
        producing = any(
            (last is not None and (now - last) <= max(stale_threshold, 1.0))
            for last in (self._last_frame_at.get(d) for d in expected))
        if producing:
            return True, "healthy"
        return False, "degraded"

    async def _heartbeat_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                healthy, phase = self._health_phase()
                status = Status(
                    worker_id=self.worker_id, use_case=self.use_case,
                    healthy=healthy, phase=phase,
                    active_cameras=list(self._camera_tasks.keys()))
                await self._redis.xadd(self._status, {"data": status.to_json()},
                                       maxlen=STATUS_MAX_LEN, approximate=True)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("[%s] heartbeat publish failed: %s", self.use_case, e)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.heartbeat_interval)
            except asyncio.TimeoutError:
                continue

    # ── signals ────────────────────────────────────────────────────────────
    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.stop)
            except (NotImplementedError, RuntimeError):
                pass
