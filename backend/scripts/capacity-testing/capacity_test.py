#!/usr/bin/env python3
# =============================================================================
# capacity_test.py — NVR capacity testing framework
# =============================================================================
# Usage:
#   python capacity_test.py --api-url http://localhost:8000 --username admin \
#       --password secret --cameras 32 --duration 600
#
# This script:
#   1. Authenticates with the NVR API
#   2. Creates N fake cameras (pointing at simulated RTSP streams)
#   3. Starts recording on all cameras simultaneously
#   4. Collects system / FFmpeg / DB metrics every 5 seconds
#   5. Logs to a JSONL file
#   6. Generates a summary report on exit
# =============================================================================

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import psutil

# ---------------------------------------------------------------------------
# Optional deps — degrade gracefully if missing
# ---------------------------------------------------------------------------
try:
    import psycopg2
    _HAS_PSYCOPG2 = True
except ImportError:
    _HAS_PSYCOPG2 = False

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_API_URL = os.getenv("NVR_API_URL", "http://localhost:8000")
DEFAULT_RTSP_BASE = os.getenv("NVR_RTSP_BASE", "rtsp://localhost:8554")
DEFAULT_DB_URL = os.getenv("DATABASE_URL", "")
METRIC_INTERVAL = 5  # seconds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("capacity_test")


# ═══════════════════════════════════════════════════════════════════════════
# API Client
# ═══════════════════════════════════════════════════════════════════════════

class NvrApiClient:
    """Thin async HTTP client for the NVR REST API."""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout)
        self._token: Optional[str] = None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def login(self, username: str, password: str) -> str:
        resp = self._client.post(
            f"{self.base_url}/api/auth/login",
            json={"username": username, "password": password},
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        logger.info(f"Logged in as {data['user']['username']} (role={data['user'].get('role','?')})")
        return self._token

    def _headers(self) -> Dict[str, str]:
        if not self._token:
            raise RuntimeError("Not authenticated — call login() first")
        return {"Authorization": f"Bearer {self._token}"}

    # ------------------------------------------------------------------
    # Cameras
    # ------------------------------------------------------------------

    def create_camera(self, name: str, main_stream_url: str) -> str:
        """Create a camera and return its ID."""
        payload = {
            "name": name,
            "main_stream_url": main_stream_url,
            "sub_stream_url": None,
            "recording_mode": "continuous",
            "is_enabled": True,
        }
        resp = self._client.post(
            f"{self.base_url}/api/cameras",
            json=payload,
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()["id"]

    def delete_camera(self, camera_id: str) -> None:
        resp = self._client.delete(
            f"{self.base_url}/api/cameras/{camera_id}",
            headers=self._headers(),
        )
        if resp.status_code != 204:
            logger.warning(f"Failed to delete camera {camera_id}: {resp.status_code}")

    def list_cameras(self) -> List[dict]:
        resp = self._client.get(
            f"{self.base_url}/api/cameras",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def start_recording(self, camera_id: str) -> dict:
        resp = self._client.post(
            f"{self.base_url}/api/cameras/{camera_id}/start-recording",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def stop_recording(self, camera_id: str) -> dict:
        resp = self._client.post(
            f"{self.base_url}/api/cameras/{camera_id}/stop-recording",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # System / Monitoring
    # ------------------------------------------------------------------

    def health(self) -> dict:
        resp = self._client.get(f"{self.base_url}/api/health")
        resp.raise_for_status()
        return resp.json()

    def monitoring_health(self) -> dict:
        resp = self._client.get(
            f"{self.base_url}/api/monitoring/health",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def monitoring_resources(self) -> dict:
        resp = self._client.get(
            f"{self.base_url}/api/monitoring/resources",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def bandwidth(self) -> dict:
        resp = self._client.get(
            f"{self.base_url}/api/monitoring/bandwidth",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def close(self) -> None:
        self._client.close()


# ═══════════════════════════════════════════════════════════════════════════
# Metrics Collector
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class MetricSample:
    ts: str
    system: dict
    ffmpeg: dict
    database: dict
    api: dict
    network: dict
    disk_io: dict


class MetricsCollector(threading.Thread):
    """Background thread that samples metrics every *interval* seconds."""

    def __init__(
        self,
        api: NvrApiClient,
        db_url: Optional[str],
        interval: int,
        out_path: Path,
    ):
        super().__init__(daemon=True)
        self.api = api
        self.db_url = db_url
        self.interval = interval
        self.out_path = out_path
        self.samples: List[MetricSample] = []
        self._stop_event = threading.Event()
        self._disk_io_prev: Optional[Any] = None
        self._disk_io_time_prev: Optional[float] = None
        self._net_io_prev: Optional[Any] = None
        self._net_io_time_prev: Optional[float] = None

    def run(self) -> None:
        # Warm-up CPU percent
        psutil.cpu_percent(interval=None)
        time.sleep(0.5)

        while not self._stop_event.is_set():
            try:
                sample = self._collect()
                self.samples.append(sample)
                self._write_jsonl(sample)
            except Exception as exc:
                logger.warning(f"Metrics collection error: {exc}")
            self._stop_event.wait(self.interval)

    def stop(self) -> None:
        self._stop_event.set()
        self.join(timeout=self.interval + 2)

    # ------------------------------------------------------------------
    # Collectors
    # ------------------------------------------------------------------

    def _collect(self) -> MetricSample:
        ts = datetime.now(timezone.utc).isoformat()
        return MetricSample(
            ts=ts,
            system=self._collect_system(),
            ffmpeg=self._collect_ffmpeg(),
            database=self._collect_database(),
            api=self._collect_api(),
            network=self._collect_network(),
            disk_io=self._collect_disk_io(),
        )

    def _collect_system(self) -> dict:
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return {
            "cpu_percent": round(cpu, 1),
            "memory_percent": round(mem.percent, 1),
            "memory_used_mb": round(mem.used / (1024 * 1024), 1),
            "memory_total_mb": round(mem.total / (1024 * 1024), 1),
            "disk_percent": round(disk.percent, 1),
            "disk_used_gb": round(disk.used / (1024 ** 3), 2),
            "disk_total_gb": round(disk.total / (1024 ** 3), 2),
        }

    def _collect_ffmpeg(self) -> dict:
        procs = []
        total_cpu = 0.0
        total_rss_mb = 0.0
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info", "cmdline"]):
            try:
                if proc.info["name"] and "ffmpeg" in proc.info["name"].lower():
                    cpu = proc.info["cpu_percent"] or 0.0
                    rss = (proc.info["memory_info"].rss / (1024 * 1024)) if proc.info["memory_info"] else 0.0
                    total_cpu += cpu
                    total_rss_mb += rss
                    cmdline = proc.info["cmdline"] or []
                    # Try to extract camera_id from cmdline if pushed by our test harness
                    camera_id = None
                    for i, arg in enumerate(cmdline):
                        if "cap_test_cam_" in arg:
                            camera_id = arg.split("/")[-1]
                            break
                    procs.append({
                        "pid": proc.info["pid"],
                        "cpu_percent": round(cpu, 1),
                        "rss_mb": round(rss, 1),
                        "camera_id": camera_id,
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return {
            "process_count": len(procs),
            "total_cpu_percent": round(total_cpu, 1),
            "total_rss_mb": round(total_rss_mb, 1),
            "processes": procs,
        }

    def _collect_database(self) -> dict:
        if not self.db_url or not _HAS_PSYCOPG2:
            return {"available": False}

        result: dict = {"available": True, "connections": 0, "active_queries": 0}
        try:
            conn = psycopg2.connect(self.db_url.replace("+asyncpg", ""))
            conn.autocommit = True
            cur = conn.cursor()

            # Total connections to this DB
            db_name = conn.get_dsn_parameters().get("dbname", "")
            cur.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = %s",
                (db_name,),
            )
            result["connections"] = cur.fetchone()[0]

            # Active (non-idle) queries
            cur.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = %s AND state = 'active'",
                (db_name,),
            )
            result["active_queries"] = cur.fetchone()[0]

            # Connection pool utilisation (if we can infer from settings)
            # pool_size=20, max_overflow=30 in the app — hard-coded knowledge
            result["pool_size"] = 20
            result["max_overflow"] = 30

            # DB-level transaction stats (tuples returned / fetched)
            cur.execute(
                "SELECT xact_commit, xact_rollback, blks_read, blks_hit "
                "FROM pg_stat_database WHERE datname = %s",
                (db_name,),
            )
            row = cur.fetchone()
            if row:
                result["xact_commit"] = row[0]
                result["xact_rollback"] = row[1]
                result["blks_read"] = row[2]
                result["blks_hit"] = row[3]

            cur.close()
            conn.close()
        except Exception as exc:
            result["available"] = False
            result["error"] = str(exc)
        return result

    def _collect_api(self) -> dict:
        data: dict = {"available": False}
        try:
            health = self.api.health()
            data["available"] = True
            data["active_recordings"] = health.get("active_recordings", 0)
            data["go2rtc_status"] = health.get("go2rtc", "unknown")
        except Exception as exc:
            data["error"] = str(exc)

        # Also pull the rich monitoring endpoint if we can
        try:
            mon = self.api.monitoring_health()
            data["cameras"] = mon.get("cameras", {})
            data["go2rtc_healthy"] = mon.get("go2rtc", {}).get("healthy", False)
        except Exception:
            pass
        return data

    def _collect_network(self) -> dict:
        net = psutil.net_io_counters()
        now = time.time()
        result = {
            "recv_mbps": 0.0,
            "sent_mbps": 0.0,
            "recv_bytes": net.bytes_recv,
            "sent_bytes": net.bytes_sent,
        }
        if self._net_io_prev and self._net_io_time_prev:
            elapsed = now - self._net_io_time_prev
            if elapsed > 0:
                result["recv_mbps"] = round(
                    (net.bytes_recv - self._net_io_prev.bytes_recv) / elapsed / 125_000, 2
                )
                result["sent_mbps"] = round(
                    (net.bytes_sent - self._net_io_prev.bytes_sent) / elapsed / 125_000, 2
                )
        self._net_io_prev = net
        self._net_io_time_prev = now
        return result

    def _collect_disk_io(self) -> dict:
        dio = psutil.disk_io_counters()
        now = time.time()
        result = {
            "read_mbps": 0.0,
            "write_mbps": 0.0,
            "read_bytes": dio.read_bytes if dio else 0,
            "write_bytes": dio.write_bytes if dio else 0,
        }
        if self._disk_io_prev and self._disk_io_time_prev and dio:
            elapsed = now - self._disk_io_time_prev
            if elapsed > 0:
                result["read_mbps"] = round(
                    (dio.read_bytes - self._disk_io_prev.read_bytes) / elapsed / (1024 * 1024), 2
                )
                result["write_mbps"] = round(
                    (dio.write_bytes - self._disk_io_prev.write_bytes) / elapsed / (1024 * 1024), 2
                )
        if dio:
            self._disk_io_prev = dio
            self._disk_io_time_prev = now
        return result

    def _write_jsonl(self, sample: MetricSample) -> None:
        with open(self.out_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "timestamp": sample.ts,
                "system": sample.system,
                "ffmpeg": sample.ffmpeg,
                "database": sample.database,
                "api": sample.api,
                "network": sample.network,
                "disk_io": sample.disk_io,
            }, default=str) + "\n")


# ═══════════════════════════════════════════════════════════════════════════
# Capacity Test Orchestrator
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class TestConfig:
    api_url: str
    username: str
    password: str
    camera_count: int
    duration: int
    rtsp_base: str
    db_url: Optional[str]
    output_dir: Path
    cleanup: bool
    camera_prefix: str


class CapacityTest:
    def __init__(self, cfg: TestConfig):
        self.cfg = cfg
        self.api = NvrApiClient(cfg.api_url)
        self.camera_ids: List[str] = []
        self.collector: Optional[MetricsCollector] = None
        self._interrupted = False

    # ------------------------------------------------------------------
    # Main flow
    # ------------------------------------------------------------------

    def run(self) -> dict:
        start_time = time.monotonic()
        self.cfg.output_dir.mkdir(parents=True, exist_ok=True)

        # Auth
        self.api.login(self.cfg.username, self.cfg.password)

        # Pre-flight health check
        health = self.api.health()
        logger.info(f"NVR health: {health}")

        # Create cameras
        self._create_cameras()

        # Start recording
        self._start_all_recordings()

        # Start metrics collector
        jsonl_path = self.cfg.output_dir / f"metrics_{self._ts()}.jsonl"
        self.collector = MetricsCollector(
            api=self.api,
            db_url=self.cfg.db_url,
            interval=METRIC_INTERVAL,
            out_path=jsonl_path,
        )
        self.collector.start()
        logger.info(f"Metrics logging to {jsonl_path}")

        # Run for duration (or until interrupted)
        try:
            self._sleep_with_progress(self.cfg.duration)
        except KeyboardInterrupt:
            logger.info("Interrupted by user.")
            self._interrupted = True

        # Stop metrics
        self.collector.stop()

        # Stop recordings
        self._stop_all_recordings()

        # Cleanup cameras if requested
        if self.cfg.cleanup:
            self._delete_cameras()

        # Generate report
        report = self._generate_report(start_time)
        report_path = self.cfg.output_dir / f"report_{self._ts()}.json"
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, default=str)
        logger.info(f"Report written to {report_path}")
        return report

    # ------------------------------------------------------------------
    # Camera lifecycle
    # ------------------------------------------------------------------

    def _create_cameras(self) -> None:
        logger.info(f"Creating {self.cfg.camera_count} fake cameras...")
        for i in range(self.cfg.camera_count):
            name = f"{self.cfg.camera_prefix}{i:04d}"
            rtsp_url = f"{self.cfg.rtsp_base}/{self.cfg.camera_prefix}{i:04d}"
            cid = self.api.create_camera(name, rtsp_url)
            self.camera_ids.append(cid)
            if (i + 1) % 10 == 0 or (i + 1) == self.cfg.camera_count:
                logger.info(f"  Created {i + 1}/{self.cfg.camera_count} cameras")
        logger.info(f"All {len(self.camera_ids)} cameras created.")

    def _delete_cameras(self) -> None:
        logger.info("Deleting fake cameras...")
        for cid in self.camera_ids:
            self.api.delete_camera(cid)
        logger.info("Cleanup complete.")

    def _start_all_recordings(self) -> None:
        logger.info("Starting recording on all cameras...")
        ok = 0
        fail = 0
        for cid in self.camera_ids:
            try:
                self.api.start_recording(cid)
                ok += 1
            except Exception as exc:
                fail += 1
                logger.warning(f"Failed to start recording for {cid}: {exc}")
        logger.info(f"Recording started: {ok} OK, {fail} failed")
        if ok == 0:
            raise RuntimeError("No recordings could be started — aborting test.")
        # Give FFmpeg processes time to spin up
        time.sleep(5)

    def _stop_all_recordings(self) -> None:
        logger.info("Stopping all recordings...")
        for cid in self.camera_ids:
            try:
                self.api.stop_recording(cid)
            except Exception as exc:
                logger.warning(f"Failed to stop recording for {cid}: {exc}")
        logger.info("All recordings stopped.")

    # ------------------------------------------------------------------
    # Progress
    # ------------------------------------------------------------------

    def _sleep_with_progress(self, total_seconds: int) -> None:
        end = time.monotonic() + total_seconds
        while time.monotonic() < end:
            remaining = int(end - time.monotonic())
            if remaining % 30 == 0:
                logger.info(f"Test running... {remaining}s remaining")
            time.sleep(1)

    def _ts(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def _generate_report(self, start_time: float) -> dict:
        samples = self.collector.samples if self.collector else []
        elapsed = int(time.monotonic() - start_time)

        # Aggregates
        cpu_values = [s.system["cpu_percent"] for s in samples]
        mem_values = [s.system["memory_percent"] for s in samples]
        disk_pct_values = [s.system["disk_percent"] for s in samples]
        ffmpeg_counts = [s.ffmpeg["process_count"] for s in samples]
        ffmpeg_cpu = [s.ffmpeg["total_cpu_percent"] for s in samples]
        ffmpeg_rss = [s.ffmpeg["total_rss_mb"] for s in samples]
        net_recv = [s.network["recv_mbps"] for s in samples]
        net_sent = [s.network["sent_mbps"] for s in samples]
        disk_w = [s.disk_io["write_mbps"] for s in samples]

        api_recording_counts = [s.api.get("active_recordings", 0) for s in samples]

        # Peak / avg helpers
        def _peak(vals: List[float]) -> float:
            return round(max(vals), 2) if vals else 0.0

        def _avg(vals: List[float]) -> float:
            return round(sum(vals) / len(vals), 2) if vals else 0.0

        # Estimate dropped frames from bandwidth deviation
        # Expected bandwidth per camera ≈ bitrate (we assume 4 Mbps default)
        expected_kbps = self.cfg.camera_count * 4000  # rough assumption
        # Try to get actual average bandwidth from API samples
        actual_kbps_samples = []
        for s in samples:
            bw = s.api.get("cameras", {})
            # monitoring/health doesn't expose aggregate bandwidth, so we fall
            # back to the per-camera bandwidth endpoint data if present.
            # The API samples above don't include it; extend if needed.
        # Simpler: use network sent as proxy for total outbound ingestion
        avg_sent = _avg(net_sent)
        # 1 Mbps = 1000 kbps
        bandwidth_ratio = (avg_sent * 1000) / expected_kbps if expected_kbps > 0 else 1.0
        dropped_estimate_pct = max(0.0, round((1.0 - bandwidth_ratio) * 100, 1))

        # Bottleneck analysis
        bottlenecks = []
        if cpu_values and _peak(cpu_values) > 90:
            bottlenecks.append("CPU saturated (>90%)")
        if mem_values and _peak(mem_values) > 90:
            bottlenecks.append("RAM saturated (>90%)")
        if disk_w and _peak(disk_w) > 400:  # ~400 MB/s is fast NVMe territory
            bottlenecks.append("Disk write throughput very high")
        if ffmpeg_counts:
            max_ff = max(ffmpeg_counts)
            if max_ff < self.cfg.camera_count:
                bottlenecks.append(f"FFmpeg process count peaked at {max_ff}/{self.cfg.camera_count}")

        # Sustained camera count: how many had active recordings at peak
        sustained = max(api_recording_counts) if api_recording_counts else 0

        return {
            "test_config": {
                "camera_count_requested": self.cfg.camera_count,
                "duration_seconds": self.cfg.duration,
                "elapsed_seconds": elapsed,
                "interrupted": self._interrupted,
                "api_url": self.cfg.api_url,
                "rtsp_base": self.cfg.rtsp_base,
            },
            "summary": {
                "max_cameras_sustained": sustained,
                "dropped_frames_estimate_percent": dropped_estimate_pct,
                "bottlenecks": bottlenecks,
            },
            "resource_peaks": {
                "cpu_percent": _peak(cpu_values),
                "memory_percent": _peak(mem_values),
                "disk_usage_percent": _peak(disk_pct_values),
                "ffmpeg_process_count": _peak(ffmpeg_counts),
                "ffmpeg_cpu_percent": _peak(ffmpeg_cpu),
                "ffmpeg_memory_mb": _peak(ffmpeg_rss),
                "network_recv_mbps": _peak(net_recv),
                "network_sent_mbps": _peak(net_sent),
                "disk_write_mbps": _peak(disk_w),
            },
            "resource_averages": {
                "cpu_percent": _avg(cpu_values),
                "memory_percent": _avg(mem_values),
                "disk_usage_percent": _avg(disk_pct_values),
                "ffmpeg_process_count": _avg(ffmpeg_counts),
                "ffmpeg_cpu_percent": _avg(ffmpeg_cpu),
                "ffmpeg_memory_mb": _avg(ffmpeg_rss),
                "network_recv_mbps": _avg(net_recv),
                "network_sent_mbps": _avg(net_sent),
                "disk_write_mbps": _avg(disk_w),
            },
            "sample_count": len(samples),
            "camera_ids": self.camera_ids,
        }

    def close(self) -> None:
        if self.collector:
            self.collector.stop()
        self.api.close()


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="GVD NVR capacity testing framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic 16-camera test for 10 minutes
  python capacity_test.py -u admin -p secret --cameras 16

  # 64-camera mixed load for 30 minutes, keep cameras after test
  python capacity_test.py -u admin -p secret --cameras 64 --duration 1800 --no-cleanup

  # Inside Docker (backend container talking to host go2rtc)
  python capacity_test.py -u admin -p secret \
      --api-url http://localhost:8000 \
      --rtsp-base rtsp://host.docker.internal:8554 \
      --db-url postgresql+asyncpg://nvr:pass@db:5432/gvd_nvr \
      --cameras 32 --duration 600
""",
    )
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="NVR API base URL")
    parser.add_argument("-u", "--username", required=True, help="Admin username")
    parser.add_argument("-p", "--password", required=True, help="Admin password")
    parser.add_argument("--cameras", type=int, default=16, help="Number of cameras to simulate (default: 16)")
    parser.add_argument("--duration", type=int, default=600, help="Test duration in seconds (default: 600 = 10 min)")
    parser.add_argument("--rtsp-base", default=DEFAULT_RTSP_BASE, help="Base RTSP URL for simulated streams")
    parser.add_argument("--db-url", default=DEFAULT_DB_URL, help="PostgreSQL URL for direct DB metrics (optional)")
    parser.add_argument("--output-dir", default="./capacity-test-results", help="Directory for JSONL + report output")
    parser.add_argument("--no-cleanup", action="store_true", help="Keep fake cameras after test")
    parser.add_argument("--camera-prefix", default="cap_test_cam_", help="Camera / stream name prefix")
    parser.add_argument("--quiet", action="store_true", help="Suppress non-error output")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)

    cfg = TestConfig(
        api_url=args.api_url,
        username=args.username,
        password=args.password,
        camera_count=args.cameras,
        duration=args.duration,
        rtsp_base=args.rtsp_base,
        db_url=args.db_url or None,
        output_dir=Path(args.output_dir),
        cleanup=not args.no_cleanup,
        camera_prefix=args.camera_prefix,
    )

    test = CapacityTest(cfg)

    def _on_signal(signum, frame):
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        test._interrupted = True
        test.close()
        sys.exit(130)

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    try:
        report = test.run()
    except Exception as exc:
        logger.exception("Capacity test failed")
        test.close()
        return 1
    finally:
        test.close()

    # Print concise summary to stdout
    print("\n" + "=" * 60)
    print("CAPACITY TEST SUMMARY")
    print("=" * 60)
    print(f"Cameras requested : {report['test_config']['camera_count_requested']}")
    print(f"Cameras sustained : {report['summary']['max_cameras_sustained']}")
    print(f"Duration          : {report['test_config']['elapsed_seconds']}s")
    print(f"Dropped frames est: {report['summary']['dropped_frames_estimate_percent']}%")
    print(f"Peak CPU          : {report['resource_peaks']['cpu_percent']}%")
    print(f"Peak RAM          : {report['resource_peaks']['memory_percent']}%")
    print(f"Peak FFmpeg count : {report['resource_peaks']['ffmpeg_process_count']}")
    print(f"Peak FFmpeg CPU   : {report['resource_peaks']['ffmpeg_cpu_percent']}%")
    print(f"Peak disk write   : {report['resource_peaks']['disk_write_mbps']} MB/s")
    print(f"Bottlenecks       : {', '.join(report['summary']['bottlenecks']) or 'None detected'}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
