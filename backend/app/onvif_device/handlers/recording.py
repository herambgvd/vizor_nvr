# =============================================================================
# ONVIF Recording Service (Profile G) handler
# Covers: GetRecordings, GetRecordingSummary, GetRecordingConfiguration,
#         GetRecordingJobs
# =============================================================================

import logging
from datetime import datetime, timezone

from lxml import etree
from fastapi import Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ._common import (
    NS_TRC, NS_TT,
    _qn, _add_text, _extract_recording_token,
)

logger = logging.getLogger(__name__)


def _onvif_ts(dt) -> str:
    """Format a datetime as an ONVIF/UTC timestamp. Recording timestamps are
    stored naive-UTC, so treat a missing tzinfo as UTC."""
    if dt is None:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _recording_bounds(db: AsyncSession, camera_id=None):
    """Return (data_from, data_until, count) from the recordings table.

    Scoped to one camera when camera_id is given, else across all recordings.
    data_from = earliest start_time, data_until = latest end_time (falling back
    to latest start_time when end_time is NULL), count = number of segments.
    When there are no segments, data_from/data_until are None (callers emit a
    sensible 'now' instead of a fabricated 1970 epoch)."""
    from app.recordings.models import Recording

    stmt = select(
        func.min(Recording.start_time),
        func.max(func.coalesce(Recording.end_time, Recording.start_time)),
        func.count(Recording.id),
    )
    if camera_id is not None:
        stmt = stmt.where(Recording.camera_id == camera_id)
    row = (await db.execute(stmt)).one()
    return row[0], row[1], row[2] or 0


async def dispatch(action: str, body: etree.Element, request: Request, db: AsyncSession,
                   get_cameras, get_camera_by_id, **ctx):
    if "GetRecordings" in action:
        resp = etree.SubElement(body, _qn(NS_TRC, "GetRecordingsResponse"))
        cameras = await get_cameras(db)
        for cam in cameras:
            # Real recorded extent for this camera from the recordings table.
            data_from, data_until, _count = await _recording_bounds(db, cam.id)
            rec = etree.SubElement(resp, _qn(NS_TRC, "RecordingItem"))
            _add_text(rec, NS_TT, "RecordingToken", f"rec_{cam.id}")
            src = etree.SubElement(rec, _qn(NS_TT, "Source"))
            _add_text(src, NS_TT, "SourceId", cam.id)
            _add_text(src, NS_TT, "Name", cam.name)
            _add_text(src, NS_TT, "Location", cam.location or "")
            _add_text(src, NS_TT, "Description", cam.description or "")
            _add_text(src, NS_TT, "Address", cam.main_stream_url or "")
            tracks = etree.SubElement(rec, _qn(NS_TT, "Tracks"))
            track = etree.SubElement(tracks, _qn(NS_TT, "Track"))
            _add_text(track, NS_TT, "TrackToken", f"track_{cam.id}")
            _add_text(track, NS_TT, "TrackType", "Video")
            _add_text(track, NS_TT, "Description", cam.name)
            _add_text(track, NS_TT, "DataFrom", _onvif_ts(data_from))
            _add_text(track, NS_TT, "DataTo", _onvif_ts(data_until))

    elif "GetRecordingSummary" in action:
        resp = etree.SubElement(body, _qn(NS_TRC, "GetRecordingSummaryResponse"))
        # Real aggregate extent + actual segment count across all recordings.
        data_from, data_until, count = await _recording_bounds(db)
        summary = etree.SubElement(resp, _qn(NS_TRC, "Summary"))
        _add_text(summary, NS_TT, "DataFrom", _onvif_ts(data_from))
        _add_text(summary, NS_TT, "DataUntil", _onvif_ts(data_until))
        _add_text(summary, NS_TT, "NumberRecordings", count)

    elif "GetRecordingConfiguration" in action:
        resp = etree.SubElement(body, _qn(NS_TRC, "GetRecordingConfigurationResponse"))
        req_bytes = await request.body()
        rec_token = _extract_recording_token(req_bytes)
        cam_id = rec_token.replace("rec_", "") if rec_token and rec_token.startswith("rec_") else None
        cam = await get_camera_by_id(db, cam_id) if cam_id else None
        config = etree.SubElement(resp, _qn(NS_TRC, "RecordingConfiguration"))
        src = etree.SubElement(config, _qn(NS_TT, "Source"))
        _add_text(src, NS_TT, "SourceId", cam.id if cam else "")
        _add_text(src, NS_TT, "Name", cam.name if cam else "")
        _add_text(src, NS_TT, "Location", cam.location if cam else "")
        _add_text(src, NS_TT, "Description", cam.description if cam else "")
        _add_text(src, NS_TT, "Address", cam.main_stream_url if cam else "")
        _add_text(config, NS_TT, "Mode", "Always")
        _add_text(config, NS_TT, "MaximumRetentionTime", "P30D")

    elif "GetRecordingJobs" in action:
        resp = etree.SubElement(body, _qn(NS_TRC, "GetRecordingJobsResponse"))
        cameras = await get_cameras(db)
        for cam in cameras:
            if cam.is_recording:
                job = etree.SubElement(resp, _qn(NS_TRC, "JobItem"))
                _add_text(job, NS_TT, "JobToken", f"job_{cam.id}")
                _add_text(job, NS_TT, "RecordingToken", f"rec_{cam.id}")
                _add_text(job, NS_TT, "Mode", "Active")
                src = etree.SubElement(job, _qn(NS_TT, "Source"))
                _add_text(src, NS_TT, "SourceToken", f"src_{cam.id}")

    else:
        tag = action.split("}")[-1] if "}" in action else action
        if tag:
            etree.SubElement(body, _qn(NS_TRC, tag + "Response"))
