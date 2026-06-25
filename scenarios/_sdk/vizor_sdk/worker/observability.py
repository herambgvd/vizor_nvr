"""Worker healthcheck + Prometheus metrics endpoint.

Each worker process exposes a tiny HTTP server on `WORKER_METRICS_PORT`
(default 9100) with these endpoints:

    GET /healthz            → 200 if the worker has reached the run loop
                              and not stopped; 503 otherwise.
    GET /metrics            → Prometheus exposition format. Counters and
                              gauges defined below cover the questions
                              ops actually asks: are events flowing, are
                              commands hitting the DLQ, how many cameras
                              are active, what's the frame drop rate.
    GET /errors             → JSON of the recent-error ring buffer.
    GET /health             → JSON all-pipeline health snapshot.
    GET /health/<device_id> → JSON per-device health snapshot.

prometheus_client ships its own threaded WSGI server, but we expose the
endpoints from a single stdlib HTTPServer in a daemon thread. That keeps
the asyncio loop unencumbered and avoids pulling in aiohttp just for a
handful of endpoints.

prometheus_client is OPTIONAL: if it cannot be imported, no-op metric
stand-ins are installed so importing this module (and updating metrics)
never hard-fails. The HTTP server start is best-effort so a port clash
never crashes the worker.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Iterator
from urllib.parse import urlparse


logger = logging.getLogger("vizor.worker.observability")


# Bound on the in-memory last-error ring buffer. Operators rarely need
# more than a few minutes of recent failures; bigger sizes inflate
# /errors response payloads.
_ERROR_RING_MAX = int(os.environ.get("WORKER_ERROR_RING_SIZE", "64"))


# ----------------------------------------------------------------------
# Defensive prometheus_client import.
#
# If prometheus_client is importable we use the real metric classes.
# Otherwise we install no-op stand-ins whose `.labels().inc()/.set()/
# .observe()/.time()` calls do nothing, so importing this module and
# updating metrics never hard-fails when the optional dep is absent.
# ----------------------------------------------------------------------
try:
    from prometheus_client import (
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )
    from prometheus_client import CONTENT_TYPE_LATEST

    _PROM_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only without the dep
    _PROM_AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain"

    class _NoopMetric:
        """No-op stand-in for a prometheus metric.

        `.labels(...)` returns self, and `.inc/.set/.observe` do nothing.
        `.time()` returns a no-op context manager so `with m.time():`
        works. This lets metric-update sites stay unconditional when
        prometheus_client is unavailable.
        """

        def __init__(self, *args, **kwargs) -> None:
            pass

        def labels(self, *args, **kwargs) -> "_NoopMetric":
            return self

        def inc(self, *args, **kwargs) -> None:
            pass

        def dec(self, *args, **kwargs) -> None:
            pass

        def set(self, *args, **kwargs) -> None:
            pass

        def observe(self, *args, **kwargs) -> None:
            pass

        @contextlib.contextmanager
        def time(self) -> Iterator[None]:
            yield

    class CollectorRegistry:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs) -> None:
            pass

    def Counter(*args, **kwargs) -> _NoopMetric:  # type: ignore[no-redef]
        return _NoopMetric()

    def Gauge(*args, **kwargs) -> _NoopMetric:  # type: ignore[no-redef]
        return _NoopMetric()

    def Histogram(*args, **kwargs) -> _NoopMetric:  # type: ignore[no-redef]
        return _NoopMetric()

    def generate_latest(*args, **kwargs) -> bytes:  # type: ignore[no-redef]
        return b""


# Buckets tuned for edge inference latency: sub-ms decode steps up to
# seconds-long VLM calls. Covers capture/decode/detect/postprocess/publish
# and full end-to-end frame budgets.
_LATENCY_BUCKETS = (
    0.001, 0.005, 0.010, 0.025, 0.050, 0.100, 0.200, 0.400,
    0.800, 1.5, 3.0, 6.0,
)


def _port() -> int:
    try:
        return int(os.environ.get("WORKER_METRICS_PORT", "9100"))
    except ValueError:
        return 9100


class WorkerMetrics:
    """Per-worker metrics holder + tiny HTTP exposition server.

    One instance per worker process. Subclass workers don't construct
    this directly — `BaseWorker.__init__` does, and exposes the metrics
    via `self._metrics` for pipeline code to update.

    When prometheus_client is unavailable the metric attributes are
    no-op stand-ins, so all of the update sites below remain valid.
    """

    def __init__(self, use_case: str):
        self.use_case = use_case
        self._healthy = False
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        # Last-error ring buffer — populated by `record_error()` from
        # any pipeline catch-and-log site. The HTTP server exposes it
        # as JSON at `/errors` so an admin UI can surface recent
        # failures without operators SSHing into the box.
        self._errors: deque[dict] = deque(maxlen=_ERROR_RING_MAX)
        self._errors_lock = threading.Lock()
        # Per-pipeline health snapshot provider. BaseWorker wires this
        # to a function returning {device_id: {"last_frame_at", "stale",
        # "stale_threshold_s", ...}} so the HTTP server can serve
        # `/health/<device_id>` for admin UI per-camera triage.
        self._pipeline_health_provider = None

        # Per-worker registry — keeps multiple worker processes on the
        # same host from clobbering each other's series during tests.
        # Production runs one worker per container so the default
        # registry would also be fine; explicit is safer.
        self.registry = CollectorRegistry()
        self.events_emitted = Counter(
            "vizor_worker_events_emitted_total",
            "Detection events successfully published to ai:events",
            ["use_case"],
            registry=self.registry,
        )
        self.commands_dispatched = Counter(
            "vizor_worker_commands_dispatched_total",
            "Control commands processed (start/stop/update_config/reload)",
            ["use_case", "kind"],
            registry=self.registry,
        )
        self.commands_dlq = Counter(
            "vizor_worker_commands_dlq_total",
            "Commands moved to the DLQ after dispatch failure",
            ["use_case"],
            registry=self.registry,
        )
        self.frame_drops = Counter(
            "vizor_worker_frame_drops_total",
            "Frames discarded by the fps throttle (downstream too slow)",
            ["use_case", "camera_id"],
            registry=self.registry,
        )
        self.frames_processed = Counter(
            "vizor_worker_frames_processed_total",
            "Frames passed through process_frame (post-throttle)",
            ["use_case", "camera_id"],
            registry=self.registry,
        )
        self.active_cameras = Gauge(
            "vizor_worker_active_cameras",
            "Number of cameras currently running on this worker",
            ["use_case"],
            registry=self.registry,
        )
        self.warmup_ok = Gauge(
            "vizor_worker_warmup_ok",
            "1 if warmup hook finished without raising; 0 otherwise",
            ["use_case"],
            registry=self.registry,
        )
        # Per-stage frame latency. `stage` labels: capture, decode,
        # detect, postprocess, publish, end_to_end. Use the
        # `stage_timer()` context manager below to record.
        self.frame_stage_latency = Histogram(
            "vizor_worker_frame_stage_latency_seconds",
            "Per-stage frame processing latency",
            ["use_case", "camera_id", "stage"],
            buckets=_LATENCY_BUCKETS,
            registry=self.registry,
        )
        # Bounded async queues between stages publish their depth.
        # `queue` labels identify the queue (e.g. vlm_in, event_out).
        self.queue_depth = Gauge(
            "vizor_worker_queue_depth",
            "Current depth of an internal bounded queue",
            ["use_case", "queue"],
            registry=self.registry,
        )
        # Inflight async tasks per logical pool (vlm, publish, ...).
        self.tasks_inflight = Gauge(
            "vizor_worker_tasks_inflight",
            "Concurrent inflight tasks per logical pool",
            ["use_case", "pool"],
            registry=self.registry,
        )
        # asyncio event-loop lag — distance between when a callback
        # was scheduled and when it actually ran. Sampled once per
        # second by `start_loop_lag_sampler`. Histogram so we can
        # alert on p99 lag without losing the long tail.
        self.loop_lag = Histogram(
            "vizor_worker_loop_lag_seconds",
            "Asyncio event-loop scheduling lag (sampled 1Hz)",
            ["use_case"],
            buckets=(0.001, 0.005, 0.010, 0.025, 0.050, 0.100, 0.250, 0.500, 1.0, 2.0),
            registry=self.registry,
        )
        # Slow-callback counter — incremented whenever
        # `loop.slow_callback_duration` triggers a warning. Useful
        # to catch one-off stalls that the lag sampler misses.
        self.slow_callbacks = Counter(
            "vizor_worker_slow_callbacks_total",
            "Coroutines/callbacks exceeding loop.slow_callback_duration",
            ["use_case"],
            registry=self.registry,
        )

    # ------------------------------------------------------------------
    # Stage timing — convenience context manager.
    # ------------------------------------------------------------------

    @contextlib.contextmanager
    def stage_timer(self, camera_id: str, stage: str) -> Iterator[None]:
        """Record the wrapped block's duration into ``frame_stage_latency``.

        Usage::

            with self._metrics.stage_timer(cam_id, "detect"):
                boxes = await detector.detect(frame)

        Cheap (one ``time.perf_counter`` pair + one histogram observe);
        safe to wrap hot paths. Falls through silently if prometheus is
        unavailable so tests don't need the optional dep.
        """
        if not _PROM_AVAILABLE:
            yield
            return
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.frame_stage_latency.labels(
                use_case=self.use_case,
                camera_id=str(camera_id),
                stage=stage,
            ).observe(time.perf_counter() - t0)

    # ------------------------------------------------------------------
    # Loop-lag sampler — 1Hz background task.
    # ------------------------------------------------------------------

    def start_loop_lag_sampler(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Launch a 1Hz coroutine that samples event-loop scheduling lag.

        Schedules a callback for `now + 1.0s`; when it fires, the
        difference between intended and actual fire time is the lag.
        Records to the ``loop_lag`` histogram. Cancellation-safe —
        ``BaseWorker.shutdown`` calls ``stop_loop_lag_sampler``.

        Also sets `loop.slow_callback_duration` so cpython emits its
        own warnings on slow coroutines; we bump the counter from a
        log handler attached separately if desired. Default threshold
        0.1s.
        """
        if not _PROM_AVAILABLE:
            return
        if getattr(self, "_lag_task", None) is not None:
            return
        try:
            loop = loop or asyncio.get_running_loop()
        except RuntimeError:
            return
        # Surface stalls > 100ms in worker logs. Cheap, no false
        # positives in a healthy pipeline. Bump if too noisy.
        try:
            loop.slow_callback_duration = float(
                os.environ.get("WORKER_SLOW_CALLBACK_SECONDS", "0.1")
            )
        except Exception:
            loop.slow_callback_duration = 0.1

        async def _sampler() -> None:
            while True:
                t0 = loop.time()
                await asyncio.sleep(1.0)
                lag = max(0.0, loop.time() - t0 - 1.0)
                self.loop_lag.labels(use_case=self.use_case).observe(lag)
                # Forward to the inference gateway so `should_skip()`
                # can adapt to live load without each pipeline wiring
                # its own lag sampler. The setter is best-effort —
                # workers that never built a gateway just no-op.
                cb = getattr(self, "_lag_observer", None)
                if cb is not None:
                    try:
                        cb(lag)
                    except Exception:
                        pass

        self._lag_task = loop.create_task(_sampler(), name=f"vizor-loop-lag-{self.use_case}")

    def set_lag_observer(self, cb) -> None:
        """Register a callback to receive (lag_seconds: float) once per
        sample tick. Used by `BaseWorker` to bridge live loop-lag into
        the InferenceGateway's `should_skip` heuristic."""
        self._lag_observer = cb

    def stop_loop_lag_sampler(self) -> None:
        task = getattr(self, "_lag_task", None)
        if task is not None and not task.done():
            task.cancel()
        self._lag_task = None

    # ------------------------------------------------------------------

    def record_error(self, category: str, message: str, **extra) -> None:
        """Append an entry to the last-error ring buffer.

        Pipelines call this on any catch-and-log site that an operator
        would want to see — Triton infer failure, VLM timeout, Redis
        publish error, etc. Cheap (one deque append + dict copy).
        """
        entry = {
            "ts": time.time(),
            "category": category,
            "message": str(message)[:512],
            "extra": {k: str(v)[:200] for k, v in extra.items() if v is not None},
        }
        with self._errors_lock:
            self._errors.append(entry)

    def recent_errors(self) -> list[dict]:
        with self._errors_lock:
            return list(self._errors)

    def set_pipeline_health_provider(self, fn) -> None:
        """Register a callable that returns the per-pipeline health
        snapshot. Called from the HTTP server thread, so the callable
        must be thread-safe (read-only access to BaseWorker's dicts is
        fine — a single ``dict()`` copy is atomic enough for our
        purposes; we don't need a lock for an ops endpoint)."""
        self._pipeline_health_provider = fn

    def pipeline_health(self) -> dict:
        fn = self._pipeline_health_provider
        if fn is None:
            return {}
        try:
            return fn() or {}
        except Exception:  # pragma: no cover
            return {}

    def mark_healthy(self) -> None:
        self._healthy = True

    def mark_unhealthy(self) -> None:
        self._healthy = False

    def is_healthy(self) -> bool:
        return self._healthy

    # ------------------------------------------------------------------

    def start_server(self) -> None:
        """Spawn the HTTP server in a daemon thread. Idempotent.

        Best-effort: any failure to bind/start is logged as a warning
        and swallowed so an ops endpoint can never crash the worker.
        """
        if self._thread is not None:
            return

        owner = self

        class Handler(BaseHTTPRequestHandler):
            # Silence the default per-request stderr noise — we have
            # structured logging elsewhere.
            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

            def do_GET(self):  # noqa: N802
                path = urlparse(self.path).path
                if path == "/healthz":
                    code = 200 if owner.is_healthy() else 503
                    body = b"ok" if owner.is_healthy() else b"unhealthy"
                    self.send_response(code)
                    self.send_header("Content-Type", "text/plain")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if path == "/metrics" and _PROM_AVAILABLE:
                    payload = generate_latest(owner.registry)
                    self.send_response(200)
                    self.send_header("Content-Type", CONTENT_TYPE_LATEST)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                if path == "/errors":
                    payload = json.dumps(
                        {"use_case": owner.use_case, "errors": owner.recent_errors()},
                    ).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                if path == "/health":
                    # All-pipeline snapshot. Admin UI calls this once
                    # per refresh; per-cam triage uses `/health/<id>`.
                    snapshot = owner.pipeline_health()
                    payload = json.dumps({
                        "use_case": owner.use_case,
                        "worker_healthy": owner.is_healthy(),
                        "pipelines": snapshot,
                    }).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                if path.startswith("/health/"):
                    device_id = path[len("/health/"):]
                    snapshot = owner.pipeline_health().get(device_id)
                    if snapshot is None:
                        self.send_response(404)
                        self.send_header("Content-Type", "application/json")
                        body = json.dumps({"error": "not_found"}).encode()
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                        return
                    payload = json.dumps({
                        "use_case": owner.use_case,
                        "device_id": device_id,
                        **snapshot,
                    }).encode()
                    code = 200 if not snapshot.get("stale") else 503
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                self.send_response(404)
                self.end_headers()

        port = _port()
        try:
            self._server = HTTPServer(("0.0.0.0", port), Handler)
        except Exception as exc:
            # Port busy (multiple workers in one container, or test
            # parallelism) or any other bind failure. Don't crash the
            # worker over an ops endpoint.
            logger.warning(
                "metrics HTTP server failed to bind on port %d: %s", port, exc
            )
            self._server = None
            return
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name=f"vizor-metrics-{self.use_case}",
            daemon=True,
        )
        self._thread.start()

    def stop_server(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
        self._server = None
        self._thread = None
