# Porting the vizor-gpu AI-worker framework into vizor-nvr's PPE scenario

Status: **PLAN**. Drafted against `vizor_nvr` and `vizor-gpu` (`/home/gvd-ai/office/clarify/`).

The vizor-nvr PPE live worker is fragile under multiple cameras; the vizor-gpu
`_base` framework already solved this. This is the port-and-adapt plan.

## 1. Why, and the target architecture

### Why
The PPE live path collapses with multiple cameras because every camera worker is a
`threading.Thread` (`scenarios/ppe/live/worker.py:199`) contending on three
process-wide chokepoints:

1. a single `_INFLIGHT = threading.Semaphore(12)` shared by ALL workers
   (`worker.py:53`),
2. ONE shared blocking Triton HTTP client with a 30s timeout
   (`scenarios/_sdk/vizor_sdk/triton.py:31`, singleton at
   `scenarios/ppe/inference/triton_engine.py:176`),
3. SYNCHRONOUS Postgres inserts on the frame thread inside `_record_event`
   (`scenarios/ppe/db/events.py:99-116`), whose failures are swallowed by the broad
   per-frame `except` (`worker.py:381-386`).

When one camera's Triton call wedges on the shared client, the 12 semaphore slots
drain, the GIL + blocking sockets starve the other ffmpeg-pipe FramePullers, two
cameras never decode a frame, and the third's DB inserts silently fail (counter
climbs, no rows). **GPU at 0% = coordination failure, not compute.**

vizor-gpu solved exactly this with an asyncio framework: one task per camera,
bounded per-model inference, drop-oldest frame queues, an off-thread spooled event
path, and per-camera circuit breakers + watchdog. We port that and adapt it to
vizor-nvr's contract (Postgres events, local snapshot volume, HTTP camera reconcile)
instead of vizor-gpu's (Redis/rustfs/qdrant), **preserving the existing PPE pipeline
untouched**.

### Target architecture (in words)
```
FastAPI startup (scenarios/ppe/app.py)
   └─ start_live_manager()  ── spawns ──▶ dedicated asyncio loop thread
                                              │
                          AsyncSupervisor (ports BaseWorker.run lifecycle)
                                              │
       HTTP reconcile loop  ───────────────▶ start_camera / stop_camera / update_config
       (polls NVR /ai/internal/cameras)        │  (replaces vizor-gpu Redis control stream)
                                              ▼
                              one asyncio.Task PER CAMERA  (_camera_task)
                                              │
                       PyAV async ingest (stream_ingest.rtsp_frames)
                                              │
                       bounded drop-oldest queue (per camera; FrameBus optional)
                                              │
                       existing synchronous PPE pipeline (_process)
                       run via asyncio.to_thread / bounded executor
                            ├─ PPEDetector.detect ─▶ InferenceGateway ─▶ TritonClient
                            │     (per-model bounded inflight + circuit breaker + timeout)
                            ├─ SigLIP / crop stage / ComplianceEngine  (UNCHANGED)
                            └─ on violation ─▶ async event path
                                              │
              event spool (asyncio.Queue + disk fallback) ── drains on writer task ──▶
                            record_event() Postgres insert   (replaces Redis ai:events)
                            + snapshot JPEG to DATA_PATH/snapshots  (replaces rustfs)
                                              │
              per-camera circuit breaker + pipeline watchdog (restarts a silent camera)
              + per-camera last_frame_at liveness  ─▶ worker_logs / live_status (UNCHANGED API)
```

Invariant: **nothing blocking runs on the asyncio loop.** Decode is PyAV-in-thread,
inference + DB inserts via `asyncio.to_thread` / bounded executor.

## 2. Scope — which `_base` modules to port

Legend: **(A)** port mostly as-is · **(B)** port-and-adapt · **(C)** skip.

| `vizor-gpu/ai_workers/_base/` | Action | Justification |
|---|---|---|
| `worker.py` (1055) — async supervisor + per-camera task + watchdog | **B** | The crown jewel. Port the lifecycle; REPLACE Redis control with HTTP reconcile, `emit()`→Redis with `record_event()`→Postgres, heartbeat→`_report_state`. |
| `stream_ingest.py` (148) — PyAV async RTSP→BGR | **A** | Direct replacement for the ffmpeg-pipe FramePuller. Decode-in-thread, fps throttle, reconnect backoff. |
| `frame_bus.py` (404) — bounded drop-oldest queues | **B (deferred)** | Source marked for deletion; borrow only the drop-oldest queue in P1. Full decode-once fan-out only in P3. |
| `inference_gateway.py` (436) — per-model bounded inflight | **B** | Replaces the global `_INFLIGHT`. Wrap nvr's SYNC `TritonClient.infer` in `asyncio.to_thread`. |
| `circuit_breaker.py` (~250) | **A** | Pure primitive. One breaker per dependency (`ppe_triton`, `ppe_db`). |
| `event_spool.py` (~200) | **B** | Sink is Postgres, not Redis. Spool only as disk fallback when PG is down; primary is in-mem queue → executor → `record_event`. |
| `observability.py` (460) | **B** | Port loop-lag + per-camera snapshot into `worker_logs`/`/health`. Skip standalone Prometheus initially. |
| `protocol.py` (169) | **B (thin)** | Keep a tiny `Command`-like dataclass fed from HTTP reconcile, not Redis. |
| `scenario.py`, `platform_config.py` | **C / map** | nvr config already in `config/settings.py` + `scenario.json` + `camera_ai_configs`. |
| `rustfs_client.py`, `qdrant_client.py` | **C** | No object store / vector DB in PPE. Snapshots → `DATA_PATH/snapshots`. |
| cpp/gstreamer/ffmpeg frame sources, `cpp_preprocess.py` | **C** | PyAV is sufficient. Revisit only if NVDEC throughput needed. |
| `stream_recovery.py` (84) | **A (small)** | Fold backoff into `stream_ingest`. |
| `dedup.py`, `event_tagging.py`, `geometry.py`, `overlay_publisher.py`, `clip_recorder.py`, `log_setup.py` | **C** | PPE pipeline already owns these. |

## 3. Phased rollout

### Phase 0 — Tier-A stabilizers (NO async rewrite) — RESTORES MULTI-CAMERA STABILITY · DO NOW

Removes the three shared chokepoints in hours, keeping the thread-per-camera model.

**0.1 Per-camera inflight, not one shared semaphore** — `live/worker.py`.
Make `_INFLIGHT` per-`CameraWorker` (`self._inflight = threading.Semaphore(env PPE_PER_CAM_INFLIGHT=2)`); acquire/release in `_on_frame` (`:377`). Optional separate global ceiling via `BoundedSemaphore`, acquired non-blocking. A stuck camera blocks only its own 2 slots. Borrow: `inference_gateway.should_skip()`.

**0.2 Triton timeout + circuit breaker** — `inference/triton_engine.py`, `_sdk/vizor_sdk/triton.py`.
Pass short per-call timeout (`PPE_TRITON_TIMEOUT=4`). Add a SYNC circuit breaker around `PPEDetector.detect/detect_crops` (5 fails/10s → open 30s; while open `detect()` returns `[]`, fail-soft). Borrow: `circuit_breaker.py` (add sync `call`).

**0.3 Async/spooled event writes OFF the frame thread** — NEW `live/event_writer.py`; change `worker.py`, `db/events.py`.
`queue.Queue(maxsize=2000)` + ONE daemon writer thread calling `record_event(**payload)`. On failure, append JSON to `DATA_PATH/spool/ppe_events.jsonl` (bounded, rotate); replay when DB recovers. `_emit`/`_maybe_emit_compliant` call `event_writer.submit(...)` (non-blocking) instead of direct `_record_event`. **Fixes the swallowed-error data loss** + unblocks the frame thread. Borrow: `event_spool.py`.

**0.4 Pipeline-level watchdog restart** — `live/manager.py`, `live/worker.py`.
In manager `_loop`, restart any worker that `is_alive()` but whose `last_frame_ts` is older than `PPE_WATCHDOG_STALE_S=30` (re-use the existing `replaced=True; stop()` path). Catches pipeline-side wedges the byte-level FramePuller watchdog can't. Borrow: `worker.py:_watchdog_loop`.

**Risk:** LOW. Each item env-flag-gated, old behaviour default. **Test:** 3 cams @ fps 8 → all show climbing frames + DB rows; kill Triton → breaker opens, cams keep decoding; stop PG → events spool, drain on recovery; wedge one cam → only it restarts. **Rollback:** flip env flags.

### Phase 1 — Async supervisor + PyAV ingest + bounded queue (PPE only, flagged)
New `live/aio/`: `supervisor.py` (port `BaseWorker.run` minus Redis), `reconcile.py` (existing `manager.py` fetch/sig/report but calls supervisor), `ingest.py` (PyAV `rtsp_frames`), `frame_queue.py` (drop-oldest `asyncio.Queue(maxsize=2)`), `camera_task.py` (`async for frame: await asyncio.to_thread(PpePipeline.process, frame)`), `loop.py` (dedicated loop thread). Refactor `worker.py` `_process`+helpers into reusable `PpePipeline` class (pure move, thresholds preserved). `start_live_manager()` picks async when `PPE_LIVE_ASYNC=1`. `live_status`/`worker_logs` keep same shape. **Risk:** MEDIUM, flag-gated. **3-5 days.**

### Phase 2 — InferenceGateway + observability
Port `inference_gateway.py` (wrap SYNC `infer` in `to_thread`, per-model inflight + coalescing + `should_skip`) and loop-lag/health snapshots into `worker_logs`. Flag `PPE_INFER_GATEWAY=1`. **2-3 days.**

### Phase 3 — Factor into reusable `vizor_sdk` base
Move scenario-agnostic plumbing to `_sdk/vizor_sdk/aio/`; FRS/ANPR/SS adopt incrementally. FrameBus decode-once for multi-scenario-on-one-RTSP. **4-6 days + per-scenario.**

## 4. Mapping table — vizor-gpu → vizor-nvr

| vizor-gpu | vizor-nvr equivalent | nvr location |
|---|---|---|
| `emit(Event)` → Redis `ai:events` XADD | `record_event(...)` Postgres + `EventBus.publish` | `db/events.py:81` via `live/event_writer.py` |
| rustfs object storage | local snapshot volume + `/snapshot?key=live:<id>` | `worker.py:_snapshot`, `routers/snapshot.py` |
| Redis control stream + `Command` | HTTP `GET /ai/internal/cameras` + reconcile diff | `live/manager.py:_fetch_cameras/_reconcile` |
| Redis status heartbeat | HTTP `PUT /ai/internal/camera-configs/{id}/state` | `live/manager.py:_report_state` |
| `platform_config.py`/`scenario.py` | `config/settings.py` + `scenario.json` | — |
| per-camera `Command.config` | `camera["config"]` from `/ai/internal/cameras` | `worker.py:_cfg_num/roi_config` |
| `build_frame_source` (ffmpeg/gst/pyav) | `stream_ingest.rtsp_frames` (PyAV) | new `live/aio/ingest.py` |
| `InferenceGateway` → async `triton.infer` | gateway wrapping SYNC `infer` via `to_thread` | `_sdk/vizor_sdk/triton.py:69` |
| `WorkerMetrics` Prometheus | `/health` + `worker_logs()` panel | `routers/health.py`, `manager.py:worker_logs` |
| `EventSpool` (Redis-down JSONL) | spool for Postgres-down → replay | new `live/event_writer.py` |
| qdrant | (none) | skip |

## 5. Risks + where the asyncio loop lives

**Loop placement (chosen): dedicated asyncio loop thread.** `start_live_manager()`
spawns one daemon thread running `asyncio.new_event_loop()` →
`supervisor.run()`. Isolates the live worker from uvicorn's request loop (a wedged
pipeline can't stall `/health`/`/snapshot`), matches today's "manager on a daemon
thread" model, avoids the multi-uvicorn-worker N-supervisors problem. Cross-thread
`live_status`/`worker_logs` read plain dicts.

**Sync-pipeline-on-async-loop:** `_process` (detector + SigLIP + cv2 + DB) MUST run
via `asyncio.to_thread` / bounded `ThreadPoolExecutor` (`PPE_PIPELINE_WORKERS`).
Never on the loop. Decode already in-thread (PyAV), DB off-loop via event writer.

**Per-camera state isolation:** Tracker/StableIdMapper/EvidenceSmoother/Engine stay
one-instance-per-camera in the refactored `PpePipeline`.

**GIL:** heavy work (Triton infer, imencode, PG socket) releases the GIL → real
parallelism recovered, unlike today's serialised shared client.

**PyAV vs NVDEC:** PyAV defaults to software decode (higher CPU on many-camera
boxes). Honour `LIVE_HWACCEL` or fall back to `_base/ffmpeg_frame_source.py` later.

**Double-emit on watchdog restart:** track ids reset; engine cooldown prevents
storms.

## 6. Effort + cut line

| Phase | Scope | Estimate | Ship? |
|---|---|---|---|
| 0 | per-cam inflight, triton timeout+breaker, off-thread spooled writer, pipeline watchdog | 0.5–1.5 days | **DO NOW** |
| 1 | async supervisor + PyAV ingest + bounded queue + pipeline refactor (flagged) | 3–5 days | next sprint |
| 2 | inference gateway + observability | 2–3 days | after P1 soak |
| 3 | factor into `vizor_sdk` base; FRS/ANPR/SS adoption | 4–6 days + per-scenario | later |

**Cut line: ship Phase 0 immediately** — removes all three chokepoints + the
swallowed-error data loss within the existing thread model, trivial rollback. Build
Phase 1 behind `PPE_LIVE_ASYNC`, soak against the Phase-0 baseline, then layer 2–3.
Do NOT attempt the async rewrite before Phase 0 lands.
