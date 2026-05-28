# =============================================================================
# ONVIF Replay Service helpers — time-shifted replay via ffmpeg session manager
# =============================================================================
# Called from ONVIFDeviceService._handle_replay() in service.py.
#
# GetReplayUri workflow:
#   1. Parse RecordingToken → camera_id (or direct recording ID)
#   2. Parse StartTime from the SOAP request body
#   3. Look up the Recording segment that contains StartTime
#   4. Compute byte offset, generate a unique stream_id
#   5. Spawn (or reuse) an ffmpeg process via ReplayManager
#   6. Return the RTSP URI for that stream
#
# If StartTime falls outside all stored segments → SOAP fault ter:NotPresent
# If RecordingToken maps to a camera but no segments → same fault
# =============================================================================

import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional, Tuple, Union

from lxml import etree
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.recordings.models import Recording
from app.recordings.service import RecordingService
from app.onvif_device.replay_manager import replay_manager

logger = logging.getLogger(__name__)

# ONVIF namespaces used in replay SOAP requests
NS_TRP = "http://www.onvif.org/ver10/replay/wsdl"
NS_TT  = "http://www.onvif.org/ver10/schema"


def _parse_start_time(xml_bytes: bytes) -> Optional[datetime]:
    """
    Extract StartTime from a GetReplayUri SOAP body.
    Accepts ISO-8601 with Z or +00:00 suffix, or without tz info.
    Returns a timezone-aware UTC datetime or None if absent/unparseable.
    """
    try:
        root = etree.fromstring(xml_bytes)
        for tag in ("StartTime",
                    f"{{{NS_TRP}}}StartTime",
                    f"{{{NS_TT}}}StartTime"):
            el = root.find(f".//{tag}")
            if el is not None and el.text:
                text = el.text.strip()
                # Normalise: replace trailing Z, handle missing tz
                text = text.replace("Z", "+00:00")
                try:
                    dt = datetime.fromisoformat(text)
                except ValueError:
                    # Fallback: strip fractional seconds
                    text = re.sub(r"\.\d+", "", text)
                    dt = datetime.fromisoformat(text)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
    except Exception as e:
        logger.debug(f"replay._parse_start_time: {e}")
    return None


def _parse_rate_control(xml_bytes: bytes) -> dict:
    """
    Extract RateControl fields from a GetReplayUri SOAP body.
    Returns a dict with keys: speed_factor (float), reverse (bool).
    Defaults: speed_factor=1.0, reverse=False.
    """
    result = {"speed_factor": 1.0, "reverse": False}
    try:
        root = etree.fromstring(xml_bytes)
        for tag_prefix in ("", f"{{{NS_TRP}}}", f"{{{NS_TT}}}"):
            rc = root.find(f".//{tag_prefix}RateControl")
            if rc is None:
                continue
            for sf_tag in ("SpeedFactor", f"{{{NS_TT}}}SpeedFactor", f"{{{NS_TRP}}}SpeedFactor"):
                sf_el = rc.find(f".//{sf_tag}") or rc.find(sf_tag)
                if sf_el is not None and sf_el.text:
                    try:
                        result["speed_factor"] = float(sf_el.text.strip())
                    except ValueError:
                        pass
            for rev_tag in ("Reverse", f"{{{NS_TT}}}Reverse", f"{{{NS_TRP}}}Reverse"):
                rev_el = rc.find(f".//{rev_tag}") or rc.find(rev_tag)
                if rev_el is not None and rev_el.text:
                    result["reverse"] = rev_el.text.strip().lower() == "true"
            break
    except Exception as e:
        logger.debug(f"replay._parse_rate_control: {e}")
    return result


def _recording_token_to_camera_id(token: Optional[str]) -> Optional[str]:
    """
    ONVIF recording tokens used by this NVR follow the pattern `rec_<camera_id>`.
    If the token doesn't match that pattern, treat it as a direct recording id
    (caller will try get_by_id first, then fall through to camera-based lookup).
    """
    if not token:
        return None
    if token.startswith("rec_"):
        return token[4:]
    return None


def _make_stream_id(recording_id: str, offset: float) -> str:
    """Generate a deterministic, URL-safe stream identifier."""
    # Truncate recording UUID to 12 chars to keep the name short
    short_id = recording_id.replace("-", "")[:12]
    return f"replay_{short_id}_{int(offset)}"


def _rtsp_uri(request: Request, stream_id: str) -> str:
    """Build the public RTSP URI for this replay stream."""
    from app.config import settings
    host = request.headers.get("x-forwarded-host", "")
    if not host:
        host = request.headers.get("host", "localhost")
    # Strip port from host (we'll add the RTSP port explicitly)
    host_only = host.split(":")[0]
    return f"rtsp://{host_only}:{settings.GO2RTC_RTSP_PORT}/{stream_id}"


async def handle_get_replay_uri(
    xml_bytes: bytes,
    recording_token: Optional[str],
    request: Request,
    db: AsyncSession,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Core logic for GetReplayUri.

    Returns:
        (uri, None)         — success; uri is the RTSP stream URL
        (None, fault_code)  — failure; fault_code is an ONVIF fault string
    """
    start_time = _parse_start_time(xml_bytes)
    camera_id  = _recording_token_to_camera_id(recording_token)

    # ── Parse RateControl ────────────────────────────────────────────────────
    rate_control = _parse_rate_control(xml_bytes)
    speed_factor = rate_control["speed_factor"]
    reverse      = rate_control["reverse"]

    # Cap speed to valid range
    speed_factor = max(0.25, min(4.0, speed_factor))

    # Reverse playback is not supported — return SOAP fault
    if reverse and speed_factor < 0:
        logger.info("GetReplayUri: Reverse=true requested — not supported (ter:NotSupported)")
        return None, "ter:NotSupported"
    if reverse:
        logger.info("GetReplayUri: Reverse=true with positive SpeedFactor — ignoring Reverse flag")
        reverse = False

    segment: Optional[Recording] = None

    # ── Attempt 1: camera-level lookup with StartTime ─────────────────
    if camera_id and start_time:
        segment = await RecordingService.find_segment_at(db, camera_id, start_time)
        if segment is None:
            logger.info(
                f"GetReplayUri: no segment at {start_time.isoformat()} for camera {camera_id}"
            )

    # ── Attempt 2: StartTime not provided — use most recent segment ───
    if segment is None and camera_id and start_time is None:
        segment = await RecordingService.get_latest_segment(db, camera_id)
        if segment:
            start_time = segment.start_time
            if segment.start_time.tzinfo is None:
                start_time = segment.start_time.replace(tzinfo=timezone.utc)
            logger.info(
                f"GetReplayUri: no StartTime provided, using latest segment {segment.id} "
                f"for camera {camera_id}"
            )

    # ── Attempt 3: direct recording id ────────────────────────────────
    if segment is None and recording_token and not recording_token.startswith("rec_"):
        segment = await RecordingService.get_by_id(db, recording_token)
        if segment:
            start_time = start_time or (
                segment.start_time.replace(tzinfo=timezone.utc)
                if segment.start_time.tzinfo is None
                else segment.start_time
            )

    # ── Not found ─────────────────────────────────────────────────────
    if segment is None:
        logger.warning(
            f"GetReplayUri: recording not found — token={recording_token}, "
            f"start_time={start_time}"
        )
        return None, "ter:NotPresent"

    # ── Verify file exists on disk ────────────────────────────────────
    if not segment.file_path or not os.path.exists(segment.file_path):
        logger.warning(
            f"GetReplayUri: file missing for recording {segment.id}: {segment.file_path!r}"
        )
        return None, "ter:NotPresent"

    # ── Compute seek offset ───────────────────────────────────────────
    seg_start = segment.start_time
    if seg_start.tzinfo is None:
        seg_start = seg_start.replace(tzinfo=timezone.utc)

    if start_time is None:
        offset = 0.0
    else:
        # Ensure start_time is tz-aware
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        offset = max(0.0, (start_time - seg_start).total_seconds())

    stream_id = _make_stream_id(segment.id, offset)

    # ── Spawn ffmpeg replay session ───────────────────────────────────
    ok = await replay_manager.start_session(
        stream_id=stream_id,
        file_path=segment.file_path,
        offset_seconds=offset,
        speed_factor=speed_factor,
    )
    if not ok:
        logger.error(f"GetReplayUri: failed to start replay session for {stream_id}")
        return None, "ter:Action"

    replay_manager.touch_session(stream_id)

    uri = _rtsp_uri(request, stream_id)
    logger.info(
        f"GetReplayUri: stream_id={stream_id} uri={uri} "
        f"segment={segment.id} offset={offset:.1f}s"
    )
    return uri, None
