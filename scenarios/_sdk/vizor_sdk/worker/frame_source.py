"""FrameSource factory for the worker framework.

Decoder order (GStreamer is DROPPED for the worker — it threw a std::runtime
"Unable to read configuration" crash in the worker process, distinct from the app):

  1. cpp   — native vizor_decode NVDEC (h264_cuvid). Lowest CPU; the canonical
             worker decoder. Needs the compiled .so on PYTHONPATH.
  2. ffmpeg— PyAV software decode. CPU fallback when the cpp .so is missing.
  3. pyav  — nvr's existing PyAV source (last resort).

Pick via VIZOR_DECODER=cpp|ffmpeg|pyav (default cpp). Every fallback logs a WARNING
so a silent drop to software decode is visible.
"""
from __future__ import annotations

import logging
import os
from typing import Any

# Reuse nvr's ABC + the pure-software PyAV source as the final fallback.
from ..aio.frame_source import FrameSource, PyAvFrameSource  # noqa: F401

logger = logging.getLogger("vizor.worker.frame_source")


def build_frame_source(
    rtsp_url: str,
    *,
    fps: int = 5,
    backend: str | None = None,
    **kwargs: Any,
) -> FrameSource:
    requested = (backend or os.environ.get("VIZOR_DECODER", "cpp")).strip().lower()
    chosen = requested

    def _fallback(frm: str, to: str, exc: Exception) -> None:
        logger.warning(
            "decoder fallback: '%s' unavailable (%s: %s) — falling back to '%s'. "
            "On a GPU box this likely means software CPU decode.",
            frm, type(exc).__name__, exc, to)

    if chosen == "cpp":
        try:
            from .cpp_frame_source import CppFrameSource
            src = CppFrameSource(rtsp_url, fps=fps, **kwargs)
            logger.info("decoder: cpp (NVDEC) engaged for %s", rtsp_url)
            return src
        except Exception as e:  # noqa: BLE001
            _fallback("cpp", "ffmpeg", e)
            chosen = "ffmpeg"
    if chosen == "ffmpeg":
        try:
            from .ffmpeg_frame_source import FFmpegFrameSource
            src = FFmpegFrameSource(rtsp_url, fps=fps, **kwargs)
            logger.info("decoder: ffmpeg (PyAV) engaged for %s", rtsp_url)
            return src
        except Exception as e:  # noqa: BLE001
            _fallback("ffmpeg", "pyav", e)
            chosen = "pyav"
    logger.warning("decoder: using PyAV software decode for %s (requested '%s')",
                   rtsp_url, requested)
    return PyAvFrameSource(rtsp_url, fps=fps, **kwargs)
