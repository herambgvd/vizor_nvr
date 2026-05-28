# =============================================================================
# ONVIF Recording Service (Profile G) handler
# Covers: GetRecordings, GetRecordingSummary, GetRecordingConfiguration,
#         GetRecordingJobs
# =============================================================================

import logging
from datetime import datetime, timezone

from lxml import etree
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from ._common import (
    NS_TRC, NS_TT,
    _qn, _add_text, _extract_recording_token,
)

logger = logging.getLogger(__name__)


async def dispatch(action: str, body: etree.Element, request: Request, db: AsyncSession,
                   get_cameras, get_camera_by_id, **ctx):
    if "GetRecordings" in action:
        resp = etree.SubElement(body, _qn(NS_TRC, "GetRecordingsResponse"))
        cameras = await get_cameras(db)
        for cam in cameras:
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
            _add_text(track, NS_TT, "DataFrom", "1970-01-01T00:00:00Z")
            _add_text(track, NS_TT, "DataTo", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    elif "GetRecordingSummary" in action:
        resp = etree.SubElement(body, _qn(NS_TRC, "GetRecordingSummaryResponse"))
        cameras = await get_cameras(db)
        summary = etree.SubElement(resp, _qn(NS_TRC, "Summary"))
        _add_text(summary, NS_TT, "DataFrom", "1970-01-01T00:00:00Z")
        _add_text(summary, NS_TT, "DataUntil", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        _add_text(summary, NS_TT, "NumberRecordings", len(cameras))

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
