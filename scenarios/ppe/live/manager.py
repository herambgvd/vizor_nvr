"""Live worker manager.

Polls the NVR's enabled-camera catalogue for this scenario and reconciles a set
of per-camera workers: a camera that gets the scenario enabled starts a worker;
one that is disabled/unassigned stops it. Reports each worker's stream state back
to the NVR so the Cameras tab shows running / stopped / error.
"""
from __future__ import annotations

import json
import threading
import time

import requests

import config
from .worker import CameraWorker

_WORKERS: dict[str, CameraWorker] = {}   # camera_id -> worker
_LOCK = threading.Lock()


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
        print(f"[ppe-live] state report failed ({state}) for {config_id}: {exc}", flush=True)


def _reconcile():
    cams = {c["camera_id"]: c for c in _fetch_cameras()}
    with _LOCK:
        # Stop workers for cameras no longer enabled.
        for cam_id in list(_WORKERS):
            if cam_id not in cams:
                w = _WORKERS.pop(cam_id)
                w.stop()
                print(f"[ppe-live] stopped worker for {cam_id}", flush=True)
        # Start / refresh workers for enabled cameras.
        for cam_id, cam in cams.items():
            existing = _WORKERS.get(cam_id)
            if existing and existing.is_alive():
                # Restart ONLY on a genuine config change (stable JSON compare) so
                # key-order / null-vs-missing API differences don't churn the stream
                # every poll.
                if _cfg_sig(existing.config) != _cfg_sig(cam.get("config")):
                    existing.replaced = True   # suppress its late "stopped" report
                    existing.stop()
                    nw = CameraWorker(cam, _report_state)
                    _WORKERS[cam_id] = nw
                    nw.start()
                    print(f"[ppe-live] restarted worker (config change) for {cam_id}", flush=True)
                continue
            w = CameraWorker(cam, _report_state)
            _WORKERS[cam_id] = w
            w.start()
            print(f"[ppe-live] started worker for {cam_id}", flush=True)


def _loop():
    while True:
        try:
            _reconcile()
        except Exception as exc:  # noqa: BLE001
            print(f"[ppe-live] reconcile failed: {exc}", flush=True)
        time.sleep(config.LIVE_POLL_SECONDS)


def live_status() -> dict:
    """Snapshot of worker liveness for /health: how many workers exist, how many
    are alive, and how many decoded a frame within the last 60s ("active")."""
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
    now = time.time()
    with _LOCK:
        w = _WORKERS.get(camera_id)
    if w is None:
        return {"camera_id": camera_id, "running": False, "logs": [],
                "stats": {}, "detail": "no worker for this camera"}
    last = getattr(w, "last_frame_ts", 0.0)
    return {
        "camera_id": camera_id,
        "running": w.is_alive(),
        "active": w.is_alive() and (now - last) < 60.0,
        "stats": {
            "frames": getattr(w, "_frame_no", 0),
            "persons_last": getattr(w, "_dbg_persons", 0),
            "violations_total": getattr(w, "_dbg_violations", 0),
            "fps": w.config.get("fps") if getattr(w, "config", None) else None,
            "last_frame_secs_ago": round(now - last, 1) if last else None,
        },
        "logs": w.logs() if hasattr(w, "logs") else [],
    }


def start_live_manager():
    """Launch the reconcile loop on a daemon thread (no-op if disabled)."""
    if not config.LIVE_ENABLED:
        print("[ppe-live] live compliance disabled (PPE_LIVE_ENABLED=false)", flush=True)
        return
    threading.Thread(target=_loop, daemon=True, name="ppe-live-manager").start()
    print("[ppe-live] live manager started", flush=True)
