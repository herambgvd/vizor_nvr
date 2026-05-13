# =============================================================================
# Monitoring Service — system resources, per-camera bandwidth, alerts
# =============================================================================

import os
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional
from collections import deque

logger = logging.getLogger(__name__)

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


class ResourceSnapshot:
    __slots__ = ("ts", "cpu", "memory_percent", "memory_used_mb", "memory_total_mb",
                 "disk_percent", "disk_used_gb", "disk_total_gb",
                 "network_recv_mbps", "network_sent_mbps", "gpu_percent")

    def __init__(self):
        self.ts = datetime.now(timezone.utc)
        self.cpu = 0.0
        self.memory_percent = 0.0
        self.memory_used_mb = 0.0
        self.memory_total_mb = 0.0
        self.disk_percent = 0.0
        self.disk_used_gb = 0.0
        self.disk_total_gb = 0.0
        self.network_recv_mbps = 0.0
        self.network_sent_mbps = 0.0
        self.gpu_percent = 0.0

    def to_dict(self) -> dict:
        return {
            "timestamp": self.ts.isoformat(),
            "cpu_percent": round(self.cpu, 1),
            "memory_percent": round(self.memory_percent, 1),
            "memory_used_mb": round(self.memory_used_mb, 1),
            "memory_total_mb": round(self.memory_total_mb, 1),
            "disk_percent": round(self.disk_percent, 1),
            "disk_used_gb": round(self.disk_used_gb, 2),
            "disk_total_gb": round(self.disk_total_gb, 2),
            "network_recv_mbps": round(self.network_recv_mbps, 2),
            "network_sent_mbps": round(self.network_sent_mbps, 2),
            "gpu_percent": round(self.gpu_percent, 1),
        }


class MonitoringService:
    """Collects system resource metrics at configurable intervals."""

    def __init__(self, history_size: int = 360, interval: int = 10):
        self._history: deque[ResourceSnapshot] = deque(maxlen=history_size)
        self._interval = interval
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._prev_net_io = None
        self._prev_net_time = None

        # Per-camera bandwidth tracking
        self._camera_bandwidth: Dict[str, dict] = {}  # camera_id → {kbps, last_size, last_time, history}
        self._bandwidth_history: Dict[str, deque] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._collect_loop())
        logger.info(f"Monitoring started (interval={self._interval}s)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Monitoring stopped")

    async def _collect_loop(self):
        while self._running:
            try:
                snap = await asyncio.to_thread(self._collect_snapshot)
                self._history.append(snap)
            except Exception as e:
                logger.error(f"Monitoring error: {e}")
            await asyncio.sleep(self._interval)

    # ------------------------------------------------------------------
    # Collect
    # ------------------------------------------------------------------

    def _collect_snapshot(self) -> ResourceSnapshot:
        snap = ResourceSnapshot()
        if not _HAS_PSUTIL:
            return snap

        snap.cpu = psutil.cpu_percent(interval=1)

        mem = psutil.virtual_memory()
        snap.memory_percent = mem.percent
        snap.memory_used_mb = mem.used / (1024 * 1024)
        snap.memory_total_mb = mem.total / (1024 * 1024)

        disk = psutil.disk_usage("/")
        snap.disk_percent = disk.percent
        snap.disk_used_gb = disk.used / (1024 ** 3)
        snap.disk_total_gb = disk.total / (1024 ** 3)

        # Network
        net = psutil.net_io_counters()
        now = time.time()
        if self._prev_net_io and self._prev_net_time:
            elapsed = now - self._prev_net_time
            if elapsed > 0:
                snap.network_recv_mbps = (net.bytes_recv - self._prev_net_io.bytes_recv) / elapsed / 125_000
                snap.network_sent_mbps = (net.bytes_sent - self._prev_net_io.bytes_sent) / elapsed / 125_000
        self._prev_net_io = net
        self._prev_net_time = now

        # GPU (nvidia-smi via pynvml if available)
        try:
            import pynvml
            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            snap.gpu_percent = util.gpu
        except Exception:
            pass

        return snap

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def current(self) -> dict:
        if self._history:
            return self._history[-1].to_dict()
        return ResourceSnapshot().to_dict()

    def history(self, minutes: int = 60) -> List[dict]:
        count = min(len(self._history), minutes * 60 // self._interval)
        return [s.to_dict() for s in list(self._history)[-count:]]

    # ------------------------------------------------------------------
    # Per-camera bandwidth tracking
    # ------------------------------------------------------------------

    def update_camera_bandwidth(self, camera_id: str, recording_dir: str):
        """
        Called periodically by camera_monitor to track per-camera bandwidth
        by measuring file growth rate in the recording directory.
        """
        try:
            total = sum(
                os.path.getsize(os.path.join(dp, f))
                for dp, _, fn in os.walk(recording_dir)
                for f in fn
            )
        except Exception:
            return

        now = time.time()
        prev = self._camera_bandwidth.get(camera_id)

        if prev and prev["last_time"]:
            elapsed = now - prev["last_time"]
            if elapsed > 0:
                bytes_delta = total - prev["last_size"]
                kbps = (bytes_delta * 8) / elapsed / 1000
                kbps = max(0, kbps)

                self._camera_bandwidth[camera_id] = {
                    "kbps": round(kbps, 1),
                    "last_size": total,
                    "last_time": now,
                }

                # Maintain history
                if camera_id not in self._bandwidth_history:
                    self._bandwidth_history[camera_id] = deque(maxlen=360)
                self._bandwidth_history[camera_id].append({
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "kbps": round(kbps, 1),
                })
        else:
            self._camera_bandwidth[camera_id] = {
                "kbps": 0, "last_size": total, "last_time": now,
            }

    def get_camera_bandwidth(self, camera_id: str) -> dict:
        return self._camera_bandwidth.get(camera_id, {"kbps": 0})

    def get_all_bandwidth(self) -> Dict[str, dict]:
        return dict(self._camera_bandwidth)

    def get_bandwidth_history(self, camera_id: str, minutes: int = 60) -> List[dict]:
        hist = self._bandwidth_history.get(camera_id, deque())
        count = min(len(hist), minutes * 60 // self._interval)
        return list(hist)[-count:]


# Module singleton
monitoring_service = MonitoringService()
