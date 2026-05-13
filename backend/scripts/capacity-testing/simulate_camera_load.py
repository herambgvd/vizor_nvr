#!/usr/bin/env python3
# =============================================================================
# simulate_camera_load.py — Generate realistic RTSP camera streams for testing
# =============================================================================
# Usage:
#   python simulate_camera_load.py --count 32 --resolution 1920x1080 --bitrate 4M
#
# This script launches N FFmpeg processes that generate synthetic test-pattern
# video streams and push them to the local go2rtc RTSP server.  The resulting
# streams can then be consumed by the NVR backend as if they were real cameras.
# =============================================================================

import argparse
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import List

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
GO2RTC_RTSP_URL = os.getenv("GO2RTC_RTSP_URL", "rtsp://localhost:8554")
FFMPEG_PATH = os.getenv("FFMPEG_PATH", "ffmpeg")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("simulate_camera_load")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_ffmpeg_cmd(
    stream_name: str,
    resolution: str,
    fps: int,
    bitrate: str,
    codec: str,
    duration: int,
    rtsp_url: str,
    hwaccel: str,
) -> List[str]:
    """Build an FFmpeg command that generates a test stream."""
    width, height = resolution.split("x")

    # Video source: test pattern with some motion (scroll + timestamp)
    # testsrc2 is more realistic than testsrc (includes color bars + scrolling text)
    vf = (
        f"testsrc2=size={resolution}:rate={fps},"
        f"drawtext=text='%{{pts\\:hms}}':fontsize=24:fontcolor=white:box=1:boxcolor=black@0.5:x=10:y=10"
    )

    cmd = [
        FFMPEG_PATH,
        "-hide_banner",
        "-loglevel", "error",
        "-re",                          # read at native frame rate
        "-f", "lavfi",
        "-i", vf,
    ]

    # Optional hardware acceleration for encoding (reduces host CPU load)
    if hwaccel == "nvenc" and codec == "h264":
        vcodec = "h264_nvenc"
        cmd.extend(["-preset", "p4", "-tune", "ll"])
    elif hwaccel == "vaapi" and codec == "h264":
        vcodec = "h264_vaapi"
        cmd.extend(["-vaapi_device", "/dev/dri/renderD128", "-vf", "format=nv12,hwupload"])
    elif hwaccel == "videotoolbox" and codec == "h264":
        vcodec = "h264_videotoolbox"
    else:
        vcodec = "libx264"
        cmd.extend(["-preset", "ultrafast"])  # minimise encoding CPU

    cmd.extend([
        "-pix_fmt", "yuv420p",
        "-c:v", vcodec,
        "-b:v", bitrate,
        "-g", str(fps * 2),            # GOP = 2 seconds
        "-f", "rtsp",
        "-rtsp_transport", "tcp",
    ])

    if duration > 0:
        cmd.extend(["-t", str(duration)])

    cmd.append(f"{rtsp_url}/{stream_name}")
    return cmd


class SimulatedCameraPool:
    """Manages a pool of FFmpeg processes acting as simulated cameras."""

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.processes: List[subprocess.Popen] = []
        self._stopped = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        logger.info(f"Starting {self.args.count} simulated camera stream(s)...")
        logger.info(f"Target RTSP server: {self.args.rtsp_url}")

        for i in range(self.args.count):
            stream_name = f"{self.args.prefix}{i:04d}"
            cmd = _build_ffmpeg_cmd(
                stream_name=stream_name,
                resolution=self.args.resolution,
                fps=self.args.fps,
                bitrate=self.args.bitrate,
                codec=self.args.codec,
                duration=self.args.duration,
                rtsp_url=self.args.rtsp_url,
                hwaccel=self.args.hwaccel,
            )

            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                self.processes.append(proc)
                logger.info(f"  [{i+1}/{self.args.count}] {stream_name}  PID={proc.pid}")
            except FileNotFoundError:
                logger.error(f"FFmpeg not found at '{FFMPEG_PATH}'. Install FFmpeg or set FFMPEG_PATH.")
                self.stop()
                sys.exit(1)
            except Exception as exc:
                logger.error(f"Failed to start stream {stream_name}: {exc}")

        # Give go2rtc a moment to register the incoming streams
        time.sleep(2)
        alive = sum(1 for p in self.processes if p.poll() is None)
        logger.info(f"{alive}/{self.args.count} streams are alive.")

        if alive == 0:
            logger.error("No streams started — check go2rtc is running and accessible.")
            sys.exit(1)

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        logger.info("Stopping simulated camera streams...")
        for proc in self.processes:
            if proc.poll() is None:
                proc.terminate()
        # Graceful shutdown window
        gone, alive = [], list(self.processes)
        for _ in range(10):
            alive = [p for p in alive if p.poll() is None]
            if not alive:
                break
            time.sleep(0.5)
        for p in alive:
            p.kill()
        logger.info("All simulated streams stopped.")

    def health(self) -> dict:
        """Return health snapshot of the simulated streams."""
        alive = 0
        dead = 0
        for p in self.processes:
            if p.poll() is None:
                alive += 1
            else:
                dead += 1
        return {
            "total": len(self.processes),
            "alive": alive,
            "dead": dead,
        }

    def tail_errors(self, n: int = 5) -> List[str]:
        """Return last N lines of stderr from dead processes."""
        lines = []
        for p in self.processes:
            if p.poll() is not None and p.stderr:
                try:
                    err = p.stderr.read()
                    if err:
                        lines.extend(err.strip().splitlines()[-n:])
                except Exception:
                    pass
        return lines


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate synthetic RTSP camera streams for NVR capacity testing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 16x 1080p25 H.264 @ 4 Mbps  (default)
  python simulate_camera_load.py --count 16

  # 32x 4K15 H.265 @ 8 Mbps for 10 minutes
  python simulate_camera_load.py --count 32 --resolution 3840x2160 --fps 15 --bitrate 8M --codec hevc --duration 600

  # Use NVIDIA hardware encoder to reduce CPU load
  python simulate_camera_load.py --count 64 --hwaccel nvenc

  # Push to a remote go2rtc instance
  python simulate_camera_load.py --count 8 --rtsp-url rtsp://192.168.1.50:8554
""",
    )
    parser.add_argument("--count", type=int, default=16, help="Number of simulated cameras (default: 16)")
    parser.add_argument("--resolution", default="1920x1080", help="Video resolution, e.g. 1920x1080 or 3840x2160")
    parser.add_argument("--fps", type=int, default=25, help="Frames per second (default: 25)")
    parser.add_argument("--bitrate", default="4M", help="Video bitrate, e.g. 4M or 8M (default: 4M)")
    parser.add_argument("--codec", choices=["h264", "hevc"], default="h264", help="Video codec (default: h264)")
    parser.add_argument("--duration", type=int, default=0, help="Stream duration in seconds, 0 = infinite (default: 0)")
    parser.add_argument("--rtsp-url", default=GO2RTC_RTSP_URL, help="Base RTSP URL to push streams to")
    parser.add_argument("--prefix", default="cap_test_cam_", help="Stream name prefix (default: cap_test_cam_)")
    parser.add_argument("--hwaccel", choices=["none", "nvenc", "vaapi", "videotoolbox"], default="none",
                        help="Hardware video encoder (default: none / software)")
    parser.add_argument("--quiet", action="store_true", help="Suppress non-error output")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)

    pool = SimulatedCameraPool(args)

    def _on_signal(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        pool.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    pool.start()

    # If finite duration, just wait
    if args.duration > 0:
        logger.info(f"Streaming for {args.duration}s...")
        time.sleep(args.duration)
        pool.stop()
        return

    # Infinite mode — keep main thread alive and print periodic health
    logger.info("Streaming indefinitely. Press Ctrl+C to stop.")
    while True:
        time.sleep(10)
        health = pool.health()
        if health["dead"] > 0:
            logger.warning(f"Health check: {health['alive']}/{health['total']} alive ({health['dead']} dead)")
            for line in pool.tail_errors(n=3):
                logger.warning(f"  FFmpeg error: {line}")
        else:
            logger.info(f"Health check: {health['alive']}/{health['total']} alive")


if __name__ == "__main__":
    main()
