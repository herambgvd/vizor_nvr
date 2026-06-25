"""Control shim — bridge nvr's HTTP camera model to the worker's Redis control plane.

nvr assigns cameras via an HTTP poll (`GET /api/ai/internal/cameras?enabled_only=1`),
not a Redis control stream. The worker framework expects start_camera / stop_camera /
update_config Commands on `ai:frs:control`. This shim closes that gap: it polls the
HTTP camera list on a cadence, diffs it against the last-known desired set, and emits
the minimal Commands to converge the worker:

    HTTP cameras ──poll+diff──▶ start_camera / stop_camera / update_config ──▶ ai:frs:control

It also reports each camera's stream state back to nvr (running/stopped) so the
Cameras tab reflects reality, reusing the manager's existing `_report_state`.

Runs INSIDE the FRS app on a daemon thread with a sync redis client.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time

import config

logger = logging.getLogger("frs.control_shim")

USE_CASE = "frs"
CONTROL_STREAM = f"ai:{USE_CASE}:control"


def _redis_url() -> str:
    return os.environ.get("AI_REDIS_URL", "redis://ai-redis:6379/0")


def _config_sig(cfg: dict) -> str:
    try:
        return json.dumps(cfg or {}, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001
        return str(cfg)


def _rtsp_url(camera_id: str) -> str:
    host = getattr(config, "GO2RTC_RTSP_HOST", "go2rtc")
    port = getattr(config, "GO2RTC_RTSP_PORT", 8554)
    use_sub = os.getenv("FRS_LIVE_USE_SUBSTREAM", "0") not in ("0", "false", "no")
    stream_id = f"{camera_id}_sub" if use_sub else camera_id
    return f"rtsp://{host}:{port}/{stream_id}"


class ControlShim:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # desired[device_id] = (config_sig, config_id)
        self._desired: dict[str, tuple[str, str]] = {}
        self._reassert_every = 6   # re-emit all desired every N polls (~30s) so a
        self._poll_count = 0       # restarted worker re-converges even after acks.

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="frs-control-shim", daemon=True)
        self._thread.start()
        logger.info("[frs-shim] started")

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        import redis
        from .manager import _fetch_cameras, _report_state
        r = redis.from_url(_redis_url(), decode_responses=True)
        poll = float(getattr(config, "LIVE_POLL_SECONDS", 5.0))
        while not self._stop.is_set():
            try:
                self._reconcile(r, _fetch_cameras, _report_state)
            except Exception as e:  # noqa: BLE001
                logger.warning("[frs-shim] reconcile failed: %s", e)
            self._stop.wait(poll)

    def _emit(self, r, action: str, device_id: str, rtsp_url=None, cfg=None) -> None:
        cmd = {
            "action": action,
            "device_id": device_id,
            "rtsp_url": rtsp_url,
            "config": cfg or {},
        }
        r.xadd(CONTROL_STREAM, {"payload": json.dumps(cmd)}, maxlen=10_000, approximate=True)

    def _reconcile(self, r, fetch_cameras, report_state) -> None:
        cams = {c["camera_id"]: c for c in fetch_cameras()}
        current_ids = set(self._desired.keys())
        wanted_ids = set(cams.keys())
        self._poll_count += 1
        reassert = (self._poll_count % self._reassert_every) == 0

        # Stop cameras no longer enabled.
        for device_id in current_ids - wanted_ids:
            self._emit(r, "stop_camera", device_id)
            self._desired.pop(device_id, None)
            logger.info("[frs-shim] stop_camera %s", device_id)

        # Start new + update changed.
        for device_id in wanted_ids:
            cam = cams[device_id]
            cfg = dict(cam.get("config") or {})
            cfg.setdefault("camera_name", cam.get("camera_name", device_id))
            sig = _config_sig(cfg)
            config_id = cam.get("config_id")
            prev = self._desired.get(device_id)
            if prev is None:
                self._emit(r, "start_camera", device_id, _rtsp_url(device_id), cfg)
                self._desired[device_id] = (sig, config_id)
                logger.info("[frs-shim] start_camera %s", device_id)
                try:
                    report_state(config_id, "running", None)
                except Exception:
                    pass
            elif prev[0] != sig:
                self._emit(r, "update_config", device_id, _rtsp_url(device_id), cfg)
                self._desired[device_id] = (sig, config_id)
                logger.info("[frs-shim] update_config %s", device_id)
            elif reassert:
                # Idempotent re-assert so a restarted worker (which missed the
                # already-acked original Command) re-converges. _start_locked treats
                # a running camera as a no-op restart, so this is safe.
                self._emit(r, "start_camera", device_id, _rtsp_url(device_id), cfg)


_SHIM: ControlShim | None = None


def start_control_shim() -> ControlShim:
    global _SHIM
    if _SHIM is None:
        _SHIM = ControlShim()
        _SHIM.start()
    return _SHIM
