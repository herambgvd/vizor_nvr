"""FrameSource for the worker framework — reuses nvr's existing GStreamer source.

vizor-gpu shipped its own GStreamer/ffmpeg/cpp/pyav decoders. nvr ALREADY has a
battle-tuned async GStreamer source at `vizor_sdk.aio.frame_source` (audio-drop via
`application/x-rtp,media=video`, videorate pre-convert to analyze fps, rtspsrc
latency + tcp-timeout, cudadownload, and a JOIN-on-close that fixed a GLib thread
leak). Rather than port a second decoder, the worker framework reuses that one and
just re-exports it under the `FrameSource` ABC the BaseWorker expects.

`build_frame_source(rtsp_url, fps=...)` matches vizor-gpu's factory signature so the
BaseWorker calls it identically.
"""
from __future__ import annotations

import logging
import os
from typing import Any

# Reuse nvr's tuned async sources + ABC verbatim.
from ..aio.frame_source import (  # noqa: F401
    FrameSource,
    GStreamerFrameSource,
    PyAvFrameSource,
)

logger = logging.getLogger("vizor.worker.frame_source")


def build_frame_source(
    rtsp_url: str,
    *,
    fps: int = 5,
    backend: str | None = None,
    **kwargs: Any,
) -> FrameSource:
    """Pick a FrameSource. Default + canonical is GStreamer (nvr's tuned impl);
    `VIZOR_DECODER=pyav` forces the pure-software fallback. Any GStreamer build
    failure falls back to PyAV with a WARNING so a silent CPU-decode drop is visible.
    """
    requested = (backend or os.environ.get("VIZOR_DECODER", "gstreamer")).strip().lower()
    if requested != "pyav":
        try:
            src = GStreamerFrameSource(rtsp_url, fps=fps, **kwargs)
            logger.info("decoder: gstreamer engaged for %s", rtsp_url)
            return src
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "decoder fallback: gstreamer unavailable (%s: %s) — using PyAV "
                "software decode for %s; CPU-bound, expect drops under load.",
                type(e).__name__, e, rtsp_url,
            )
    return PyAvFrameSource(rtsp_url, fps=fps, **kwargs)
