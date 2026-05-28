# =============================================================================
# Hardware Acceleration Probe — detect available ffmpeg HW encoders/decoders
# =============================================================================
# Runs once at process startup (or on first call to probe()).
# Results are cached for the process lifetime.
# =============================================================================

import logging
import platform
import subprocess
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

_cache: Optional[Dict[str, Any]] = None


def probe() -> Dict[str, Any]:
    """
    Probe ffmpeg for available hardware acceleration.

    Returns a dict:
        {
            "available": ["nvenc", "vaapi", ...],
            "decoders": {"h264": "h264_cuvid", ...},
            "encoders": {"h264": "h264_nvenc", ...},
            "platform": "linux" | "darwin" | ...,
            "probed_at": "<iso8601>",
        }
    The result is cached after the first call.
    """
    global _cache
    if _cache is not None:
        return _cache

    result: Dict[str, Any] = {
        "available": [],
        "decoders": {},
        "encoders": {},
        "raw_hwaccels": [],
        "platform": platform.system().lower(),
        "probed_at": datetime.now(timezone.utc).isoformat(),
    }

    # ── Step 1: query supported hwaccel backends ──────────────────────────────
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-hwaccels"],
            capture_output=True, timeout=10, text=True,
        ).stdout
        hwaccels = [
            line.strip() for line in out.splitlines()
            if line.strip() and "Hardware" not in line
        ]
        result["raw_hwaccels"] = hwaccels
    except Exception as e:
        logger.warning(f"hwaccel_probe: -hwaccels failed: {e}")
        hwaccels = []

    # ── Step 2: query encoders ────────────────────────────────────────────────
    encoders_out = ""
    try:
        encoders_out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, timeout=10, text=True,
        ).stdout
    except Exception as e:
        logger.warning(f"hwaccel_probe: -encoders failed: {e}")

    # ── Step 3: query decoders ────────────────────────────────────────────────
    decoders_out = ""
    try:
        decoders_out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-decoders"],
            capture_output=True, timeout=10, text=True,
        ).stdout
    except Exception as e:
        logger.warning(f"hwaccel_probe: -decoders failed: {e}")

    def _has_codec(text: str, name: str) -> bool:
        return f" {name} " in text or f" {name}\n" in text or text.endswith(f" {name}")

    # Encoder candidates (priority order: nvenc > vaapi > videotoolbox > qsv)
    encoder_candidates = [
        ("nvenc",         "h264",  "h264_nvenc"),
        ("nvenc",         "hevc",  "hevc_nvenc"),
        ("vaapi",         "h264",  "h264_vaapi"),
        ("vaapi",         "hevc",  "hevc_vaapi"),
        ("videotoolbox",  "h264",  "h264_videotoolbox"),
        ("videotoolbox",  "hevc",  "hevc_videotoolbox"),
        ("qsv",           "h264",  "h264_qsv"),
        ("qsv",           "hevc",  "hevc_qsv"),
    ]

    found_families: set = set()
    for family, codec, enc_name in encoder_candidates:
        if _has_codec(encoders_out, enc_name):
            if family not in found_families:
                result["available"].append(family)
                found_families.add(family)
            if codec not in result["encoders"]:
                result["encoders"][codec] = enc_name

    # Decoder candidates
    decoder_candidates = [
        ("h264", "h264_cuvid"),
        ("h264", "h264_vaapi"),
        ("h264", "h264_videotoolbox"),
        ("h264", "h264_qsv"),
        ("hevc", "hevc_cuvid"),
        ("hevc", "hevc_vaapi"),
        ("hevc", "hevc_videotoolbox"),
        ("hevc", "hevc_qsv"),
    ]
    for codec, dec_name in decoder_candidates:
        if _has_codec(decoders_out, dec_name) and codec not in result["decoders"]:
            result["decoders"][codec] = dec_name

    logger.info(
        f"hwaccel_probe: available={result['available']} "
        f"encoders={result['encoders']} platform={result['platform']}"
    )
    _cache = result
    return result


def pick_encoder(codec: str = "h264") -> List[str]:
    """
    Return the best ffmpeg encoder flags for the given codec based on
    the cached hardware probe.

    Priority: nvenc > vaapi > videotoolbox > qsv > libx264 (software).

    Returns a list of flags ready to be inserted into an ffmpeg command,
    e.g. ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "23"]
    """
    info = probe()
    available = info.get("available", [])
    encoders = info.get("encoders", {})

    if "nvenc" in available and codec in encoders and "nvenc" in encoders.get(codec, ""):
        enc = encoders[codec]
        return ["-c:v", enc, "-preset", "p4", "-rc", "vbr", "-cq", "23"]
    if "vaapi" in available and codec in encoders and "vaapi" in encoders.get(codec, ""):
        enc = encoders[codec]
        return ["-c:v", enc, "-qp", "23"]
    if "videotoolbox" in available and codec in encoders and "videotoolbox" in encoders.get(codec, ""):
        enc = encoders[codec]
        return ["-c:v", enc, "-b:v", "4M"]
    if "qsv" in available and codec in encoders and "qsv" in encoders.get(codec, ""):
        enc = encoders[codec]
        return ["-c:v", enc, "-preset", "medium", "-global_quality", "23"]

    # Software fallback
    if codec == "h264":
        return ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23"]
    return ["-c:v", f"lib{codec}"]
