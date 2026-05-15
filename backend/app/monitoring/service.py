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
    __slots__ = (
        "ts", "cpu", "cpu_freq_mhz", "cpu_per_core",
        "memory_percent", "memory_used_mb", "memory_total_mb",
        "disk_percent", "disk_used_gb", "disk_total_gb",
        "network_recv_mbps", "network_sent_mbps",
        "gpu_percent", "gpu_mem_percent", "gpu_mem_used_mb",
        "gpu_mem_total_mb", "gpu_temp_c",
    )

    def __init__(self):
        self.ts = datetime.now(timezone.utc)
        self.cpu = 0.0
        self.cpu_freq_mhz = 0.0
        self.cpu_per_core = []
        self.memory_percent = 0.0
        self.memory_used_mb = 0.0
        self.memory_total_mb = 0.0
        self.disk_percent = 0.0
        self.disk_used_gb = 0.0
        self.disk_total_gb = 0.0
        self.network_recv_mbps = 0.0
        self.network_sent_mbps = 0.0
        self.gpu_percent = 0.0
        self.gpu_mem_percent = 0.0
        self.gpu_mem_used_mb = 0.0
        self.gpu_mem_total_mb = 0.0
        self.gpu_temp_c = 0.0

    def to_dict(self) -> dict:
        return {
            "timestamp": self.ts.isoformat(),
            "cpu_percent": round(self.cpu, 1),
            "cpu_freq_mhz": round(self.cpu_freq_mhz, 0),
            "cpu_per_core": [round(p, 1) for p in self.cpu_per_core],
            "memory_percent": round(self.memory_percent, 1),
            "memory_used_mb": round(self.memory_used_mb, 1),
            "memory_total_mb": round(self.memory_total_mb, 1),
            "disk_percent": round(self.disk_percent, 1),
            "disk_used_gb": round(self.disk_used_gb, 2),
            "disk_total_gb": round(self.disk_total_gb, 2),
            "network_recv_mbps": round(self.network_recv_mbps, 2),
            "network_sent_mbps": round(self.network_sent_mbps, 2),
            "gpu_percent": round(self.gpu_percent, 1),
            "gpu_mem_percent": round(self.gpu_mem_percent, 1),
            "gpu_mem_used_mb": round(self.gpu_mem_used_mb, 1),
            "gpu_mem_total_mb": round(self.gpu_mem_total_mb, 1),
            "gpu_temp_c": round(self.gpu_temp_c, 1),
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
        snap.cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)
        try:
            freq = psutil.cpu_freq()
            if freq:
                snap.cpu_freq_mhz = freq.current
        except Exception:
            pass

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

        # GPU (NVIDIA via pynvml)
        try:
            import pynvml
            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            snap.gpu_percent = util.gpu
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            snap.gpu_mem_used_mb = mem.used / (1024 * 1024)
            snap.gpu_mem_total_mb = mem.total / (1024 * 1024)
            if mem.total > 0:
                snap.gpu_mem_percent = mem.used / mem.total * 100
            try:
                snap.gpu_temp_c = pynvml.nvmlDeviceGetTemperature(
                    handle, pynvml.NVML_TEMPERATURE_GPU,
                )
            except Exception:
                pass
        except Exception:
            pass

        return snap

    # ------------------------------------------------------------------
    # Static system info — doesn't change between snapshots
    # ------------------------------------------------------------------

    def system_info(self) -> dict:
        """One-time host info: CPU model, core counts, GPU model + total mem."""
        info = {
            "cpu_model": None,
            "cpu_cores_physical": None,
            "cpu_cores_logical": None,
            "cpu_freq_max_mhz": None,
            "memory_total_mb": None,
            "gpus": [],
            "platform": None,
        }
        if not _HAS_PSUTIL:
            return info

        try:
            import platform as _platform
            info["platform"] = f"{_platform.system()} {_platform.release()}"
        except Exception:
            pass

        try:
            info["cpu_cores_physical"] = psutil.cpu_count(logical=False)
            info["cpu_cores_logical"] = psutil.cpu_count(logical=True)
            freq = psutil.cpu_freq()
            if freq and freq.max:
                info["cpu_freq_max_mhz"] = round(freq.max, 0)
        except Exception:
            pass

        # CPU model — read /proc/cpuinfo on Linux
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        info["cpu_model"] = line.split(":", 1)[1].strip()
                        break
        except Exception:
            pass
        if not info["cpu_model"]:
            try:
                import platform as _platform
                info["cpu_model"] = _platform.processor() or None
            except Exception:
                pass

        try:
            info["memory_total_mb"] = round(
                psutil.virtual_memory().total / (1024 * 1024), 1,
            )
        except Exception:
            pass

        # GPU list — NVIDIA via pynvml
        try:
            import pynvml
            pynvml.nvmlInit()
            count = pynvml.nvmlDeviceGetCount()
            for idx in range(count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(idx)
                name = pynvml.nvmlDeviceGetName(handle)
                if isinstance(name, bytes):
                    name = name.decode("utf-8", errors="ignore")
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                try:
                    driver = pynvml.nvmlSystemGetDriverVersion()
                    if isinstance(driver, bytes):
                        driver = driver.decode("utf-8", errors="ignore")
                except Exception:
                    driver = None
                info["gpus"].append({
                    "index": idx,
                    "name": name,
                    "memory_total_mb": round(mem.total / (1024 * 1024), 1),
                    "driver_version": driver,
                    "vendor": "NVIDIA",
                })
        except Exception:
            pass

        return info

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
