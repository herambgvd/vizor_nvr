"""Live worker manager.

Polls the NVR's enabled-camera catalogue for this scenario and reconciles a set
of per-camera workers: a camera that gets the scenario enabled starts a worker;
one that is disabled/unassigned stops it. Reports each worker's stream state back
to the NVR so the Cameras tab shows running / stopped / error instead of a static
"stopped".
"""
from __future__ import annotations

import json
import os
import threading
import time

import requests

import config
from .worker import CameraWorker

_WORKERS: dict[str, CameraWorker] = {}   # camera_id -> worker
_LOCK = threading.Lock()

# Async supervisor handle (set when FRS_LIVE_ASYNC is on) so live_status / worker_logs
# read from it instead of the legacy thread workers.
_ASYNC_SUP = None


def _async_enabled() -> bool:
    import os
    return os.getenv("FRS_LIVE_ASYNC", "false").lower() in ("1", "true", "yes", "on")


def _cfg_sig(cfg) -> str:
    """Order-stable signature of a config dict for change detection."""
    try:
        return json.dumps(cfg or {}, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001
        return str(cfg)


def _headers() -> dict:
    return {"X-Vizor-Service-Token": config.VIZOR_SERVICE_TOKEN, "X-Vizor-Scenario": config.SCENARIO_SLUG}


def _fetch_cameras() -> list[dict]:
    resp = requests.get(f"{config.VIZOR_BASE_URL}/ai/internal/cameras",
                        params={"enabled_only": "true"}, headers=_headers(), timeout=15)
    resp.raise_for_status()
    return list(resp.json().get("items") or [])


def _report_state(config_id, state, error):
    if not config_id:
        return
    try:
        requests.put(
            f"{config.VIZOR_BASE_URL}/ai/internal/camera-configs/{config_id}/state",
            json={"state": state, "error": error}, headers=_headers(), timeout=10,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[frs-live] state report failed ({state}) for {config_id}: {exc}", flush=True)


def _reconcile():
    cams = {c["camera_id"]: c for c in _fetch_cameras()}
    with _LOCK:
        # Stop workers for cameras no longer enabled.
        for cam_id in list(_WORKERS):
            if cam_id not in cams:
                w = _WORKERS.pop(cam_id)
                w.stop()
                print(f"[frs-live] stopped worker for {cam_id}", flush=True)
        # Start / refresh workers for enabled cameras.
        for cam_id, cam in cams.items():
            existing = _WORKERS.get(cam_id)
            if existing and existing.is_alive():
                # Restart ONLY on a genuine config change. Compare via stable
                # JSON (sorted keys) so key-order / null-vs-missing differences
                # from the API don't trigger a restart every poll — that churn
                # was killing the stream before it processed any frame.
                if _cfg_sig(existing.config) != _cfg_sig(cam.get("config")):
                    existing.stop()
                    nw = CameraWorker(cam, _report_state)
                    _WORKERS[cam_id] = nw
                    nw.start()
                    print(f"[frs-live] restarted worker (config change) for {cam_id}", flush=True)
                continue
            w = CameraWorker(cam, _report_state)
            _WORKERS[cam_id] = w
            w.start()
            print(f"[frs-live] started worker for {cam_id}", flush=True)


def _sweep_loop():
    """Periodic transit overdue sweep — flips open sessions past their deadline to
    overdue. Used by the async path (the legacy path folds this into _loop)."""
    while True:
        try:
            from live.transit_engine import sweep_overdue
            sweep_overdue()
        except Exception as exc:  # noqa: BLE001
            print(f"[frs-live] transit sweep failed: {exc}", flush=True)
        time.sleep(config.LIVE_POLL_SECONDS)


def _loop():
    while True:
        try:
            _reconcile()
        except Exception as exc:  # noqa: BLE001
            print(f"[frs-live] reconcile failed: {exc}", flush=True)
        # Flip past-deadline transit sessions to overdue.
        try:
            from live.transit_engine import sweep_overdue
            sweep_overdue()
        except Exception as exc:  # noqa: BLE001
            print(f"[frs-live] transit sweep failed: {exc}", flush=True)
        time.sleep(config.LIVE_POLL_SECONDS)


def live_status() -> dict:
    """Snapshot of worker liveness for /health: how many workers exist, how many
    are alive, and how many decoded a frame within the last 60s ("active")."""
    if _ASYNC_SUP is not None:
        s = _ASYNC_SUP.status()
        s.setdefault("enabled", config.LIVE_ENABLED)
        return s
    now = time.time()
    with _LOCK:
        workers = list(_WORKERS.values())
    alive = sum(1 for w in workers if w.is_alive())
    active = sum(1 for w in workers
                 if w.is_alive() and (now - getattr(w, "last_frame_ts", 0.0)) < 60.0)
    return {"enabled": config.LIVE_ENABLED, "expected": len(workers),
            "alive": alive, "active": active}


def worker_logs(camera_id: str) -> dict:
    """Live worker diagnostics for one camera — recent log lines + current stats,
    for the operator's in-UI 'worker logs' panel."""
    if _ASYNC_SUP is not None:
        return _ASYNC_SUP.camera_logs(camera_id)
    now = time.time()
    with _LOCK:
        w = _WORKERS.get(camera_id)
    if w is None:
        return {"camera_id": camera_id, "running": False, "active": False,
                "logs": [], "stats": {}, "detail": "no worker for this camera"}
    last = getattr(w, "last_frame_ts", 0.0)
    return {
        "camera_id": camera_id,
        "running": w.is_alive(),
        "active": w.is_alive() and (now - last) < 60.0,
        "stats": {
            "frames": getattr(w, "_frame_no", 0),
            "faces_last": getattr(w, "_dbg_faces", 0),
            "recognized_total": getattr(w, "_dbg_recognized", 0),
            "fps": w.config.get("fps") if getattr(w, "config", None) else None,
            "last_frame_secs_ago": round(now - last, 1) if last else None,
        },
        "logs": w.logs() if hasattr(w, "logs") else [],
    }


def _worker_v2_enabled() -> bool:
    return os.getenv("FRS_WORKER_V2", "false").lower() in ("1", "true", "yes", "on")


def start_live_manager():
    """Launch the reconcile loop on a daemon thread (no-op if disabled). With
    FRS_LIVE_ASYNC the GStreamer async supervisor runs instead of the legacy ffmpeg
    thread workers. With FRS_WORKER_V2 the in-process supervisor is REPLACED by the
    out-of-process Redis worker: the app only runs the control shim (HTTP cameras ->
    Redis Commands), the events bridge (ai:events -> Postgres), and the transit
    sweep."""
    if not config.LIVE_ENABLED:
        print("[frs-live] live recognition disabled (FRS_LIVE_ENABLED=false)", flush=True)
        return
    if _worker_v2_enabled():
        # New architecture: recognition runs in the separate FRS worker process
        # (gRPC Triton, watchdog, Redis control). The app side only bridges.
        from .events_bridge import start_events_bridge
        from .control_shim import start_control_shim
        start_events_bridge()
        start_control_shim()
        threading.Thread(target=_sweep_loop, daemon=True,
                         name="frs-transit-sweep").start()
        print("[frs-live] live manager started (worker-v2: bridge + shim + sweep)", flush=True)
        return
    if _async_enabled():
        global _ASYNC_SUP
        from .async_pipeline import build_async_manager
        _ASYNC_SUP, _ = build_async_manager()
        # The async supervisor owns camera decode, but the transit overdue sweep
        # lived in the legacy reconcile loop — under async it would never run, so
        # past-deadline sessions stayed "open" forever. Run the sweep on its own
        # lightweight thread here.
        threading.Thread(target=_sweep_loop, daemon=True,
                         name="frs-transit-sweep").start()
        print("[frs-live] live manager started (async / GStreamer) + transit sweep", flush=True)
        return
    threading.Thread(target=_loop, daemon=True, name="frs-live-manager").start()
    print("[frs-live] live manager started", flush=True)
