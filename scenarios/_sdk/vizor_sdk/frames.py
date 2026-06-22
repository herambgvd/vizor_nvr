"""FramePuller — pull analysis frames from a go2rtc RTSP restream.

Decodes one camera's RTSP stream to BGR frames at a target FPS and calls a
per-frame callback. Production features extracted verbatim from the proven FRS
live worker:

  * NVDEC hardware decode (hwaccel=cuda) for many-camera scale, with automatic
    fall-back to software decode if the GPU pipe yields nothing (no GPU / ffmpeg
    without cuvid) — a camera never silently goes dark.
  * Latest-frame backpressure: if several frames arrive in one read (we fell
    behind), keep only the newest and drop the stale ones so latency never
    snowballs.
  * Stall watchdog: kill + reconnect ffmpeg if no data arrives within a window
    (wedged camera / black-hole network that never EOFs the pipe).
  * Reconnect backoff on stream drop.

The puller is scenario-agnostic — it hands BGR frames to your callback; what you
do with them (detect faces / plates / PPE / pose) is the plugin's job.
"""
from __future__ import annotations

import logging
import subprocess
import threading
import time
from typing import Callable, Optional

import numpy as np

logger = logging.getLogger(__name__)

_SOI = b"\xff\xd8"  # JPEG start-of-image
_EOI = b"\xff\xd9"  # JPEG end-of-image


class FramePuller:
    """Pull BGR frames from one camera's go2rtc restream.

        puller = FramePuller(rtsp_url, fps=5, hwaccel="cuda")
        puller.run(on_frame=lambda bgr: detect(bgr))   # blocks until stop()
        # in another thread / signal: puller.stop()
    """

    def __init__(
        self,
        rtsp_url: str,
        fps: float = 5.0,
        hwaccel: str = "none",          # "cuda" -> NVDEC, else software
        max_width: int = 1920,
        stall_timeout: int = 20,
        label: str = "",                # for log lines (e.g. camera id)
    ):
        self.rtsp_url = rtsp_url
        self.fps = fps
        self.hwaccel = hwaccel
        self.max_width = max_width
        self.stall_timeout = stall_timeout
        self.label = label or rtsp_url
        self._stop = threading.Event()
        self._hw_failed = False
        self._used_hw = False

    def stop(self) -> None:
        self._stop.set()

    # ── ffmpeg command ────────────────────────────────────────────────────
    def _ffmpeg(self) -> subprocess.Popen:
        # Decode RTSP -> MJPEG at the analysis FPS, native resolution (capped to
        # bound memory). Detectors letterbox internally, so an upstream downscale
        # would starve small/far objects — keep it native up to max_width.
        use_hw = self.hwaccel == "cuda" and not self._hw_failed
        # RTSP socket I/O timeout (µs). ffmpeg 7.x dropped the old `-rw_timeout`
        # and `-stimeout` CLI flags for the rtsp demuxer; the working one is
        # `-timeout`. Without a valid flag ffmpeg errors out and yields no frames.
        timeout_flag = ["-timeout", "10000000"]
        if use_hw:
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                *timeout_flag,
                "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
                "-rtsp_transport", "tcp", "-i", self.rtsp_url,
                "-vf", (f"fps={self.fps},scale_cuda='min({self.max_width},iw)':-2,"
                        "hwdownload,format=nv12"),
                "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "2", "pipe:1",
            ]
        else:
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                *timeout_flag,
                "-rtsp_transport", "tcp", "-i", self.rtsp_url,
                "-vf", f"fps={self.fps},scale='min({self.max_width},iw)':-2",
                "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "2", "pipe:1",
            ]
        self._used_hw = use_hw
        return subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10 ** 7
        )

    # ── run loop ──────────────────────────────────────────────────────────
    def run(
        self,
        on_frame: Callable[[np.ndarray], None],
        on_state: Optional[Callable[[str, Optional[str]], None]] = None,
    ) -> None:
        """Block, pulling frames and calling on_frame(bgr) for each. Reconnects on
        drop. on_state(state, detail) is called on running/error/stopped if given."""
        backoff = 2
        while not self._stop.is_set():
            proc = None
            frames = 0
            try:
                proc = self._ffmpeg()
                if on_state:
                    on_state("running", None)
                backoff = 2
                frames = self._consume(proc, on_frame)
            except Exception as exc:  # noqa: BLE001
                if on_state:
                    on_state("error", str(exc)[:200])
            finally:
                if proc and proc.poll() is None:
                    proc.kill()
            if self._stop.is_set():
                break
            # NVDEC produced nothing -> GPU/cuvid unavailable. Latch to software
            # and retry immediately so the camera isn't dark.
            if self._used_hw and frames == 0 and not self._hw_failed:
                self._hw_failed = True
                logger.warning("[%s] NVDEC unavailable, falling back to software decode", self.label)
                continue
            time.sleep(min(backoff, 30))
            backoff *= 2
        if on_state:
            on_state("stopped", None)

    def _consume(self, proc, on_frame: Callable[[np.ndarray], None]) -> int:
        try:
            import cv2
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] opencv (cv2) required for frame decode: %s", self.label, exc)
            return 0

        buf = b""
        frames = 0
        last_read = [time.time()]

        def _watchdog():
            while not self._stop.is_set() and proc.poll() is None:
                if time.time() - last_read[0] > self.stall_timeout:
                    logger.warning("[%s] decode stalled (%ss no data) — killing ffmpeg",
                                   self.label, self.stall_timeout)
                    try:
                        proc.kill()
                    except Exception:  # noqa: BLE001
                        pass
                    return
                time.sleep(1.0)

        threading.Thread(target=_watchdog, daemon=True).start()

        while not self._stop.is_set():
            chunk = proc.stdout.read(65536)
            last_read[0] = time.time()
            if not chunk:
                break  # ffmpeg exited / watchdog killed -> outer loop reconnects
            buf += chunk
            # Backpressure: keep only the LATEST complete JPEG in this read, drop
            # stale ones so latency never snowballs under GPU saturation.
            latest = None
            while True:
                start = buf.find(_SOI)
                end = buf.find(_EOI, start + 2)
                if start == -1 or end == -1:
                    break
                latest = buf[start:end + 2]
                buf = buf[end + 2:]
            if latest is not None:
                arr = cv2.imdecode(np.frombuffer(latest, np.uint8), cv2.IMREAD_COLOR)
                if arr is not None:
                    frames += 1
                    try:
                        on_frame(arr)
                    except Exception as exc:  # noqa: BLE001 — a bad frame cb must not kill the stream
                        logger.warning("[%s] frame callback error: %s", self.label, exc)
        return frames
