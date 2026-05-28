# =============================================================================
# ONVIF Search Service (Profile G) handler
# Covers: FindRecordings, GetRecordingSearchResults, FindEvents,
#         GetEventSearchResults, EndSearch, GetServiceCapabilities
# =============================================================================

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Any

from lxml import etree
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from ._common import (
    NS_TSE, NS_TT,
    _qn, _add_text, _extract_recording_token,
)

logger = logging.getLogger(__name__)

# Search token registry (instance-level; passed in via ctx or kept module-level)
# We keep this module-level to match original behavior (service singleton owned it)
_search_tokens: Dict[str, Dict[str, Any]] = {}


async def dispatch(action: str, body: etree.Element, request: Request, db: AsyncSession,
                   get_cameras, get_recordings_for_camera, search_tokens: dict = None, **ctx):
    # Allow caller to provide an external token dict for testing; fall back to module-level
    tokens = search_tokens if search_tokens is not None else _search_tokens

    if "FindRecordings" in action:
        resp = etree.SubElement(body, _qn(NS_TSE, "FindRecordingsResponse"))
        token = f"search_{uuid.uuid4().hex[:8]}"
        tokens[token] = {"type": "recordings", "created": datetime.now(timezone.utc)}
        _add_text(resp, NS_TSE, "SearchToken", token)

    elif "GetRecordingSearchResults" in action:
        resp = etree.SubElement(body, _qn(NS_TSE, "GetRecordingSearchResultsResponse"))
        req_bytes = await request.body()
        rec_token = _extract_recording_token(req_bytes)
        start, end = _extract_time_range(req_bytes)

        cameras = await get_cameras(db)
        result_list = etree.SubElement(resp, _qn(NS_TSE, "ResultList"))
        _add_text(result_list, NS_TSE, "SearchState", "Completed")
        for cam in cameras:
            if rec_token and f"rec_{cam.id}" != rec_token:
                continue
            recordings = await get_recordings_for_camera(db, cam.id, start, end)
            for rec in recordings:
                item = etree.SubElement(result_list, _qn(NS_TSE, "RecordingInformation"))
                _add_text(item, NS_TT, "RecordingToken", f"rec_{cam.id}")
                src = etree.SubElement(item, _qn(NS_TT, "Source"))
                _add_text(src, NS_TT, "SourceId", cam.id)
                _add_text(src, NS_TT, "Name", cam.name)
                _add_text(src, NS_TT, "Location", cam.location or "")
                _add_text(src, NS_TT, "Description", cam.description or "")
                _add_text(src, NS_TT, "Address", cam.main_stream_url or "")
                _add_text(item, NS_TT, "EarliestRecording",
                          rec.start_time.strftime("%Y-%m-%dT%H:%M:%SZ") if rec.start_time else "")
                _add_text(item, NS_TT, "LatestRecording",
                          rec.end_time.strftime("%Y-%m-%dT%H:%M:%SZ") if rec.end_time else "")
                _add_text(item, NS_TT, "Content", "")

    elif "FindEvents" in action:
        resp = etree.SubElement(body, _qn(NS_TSE, "FindEventsResponse"))
        token = f"evtsearch_{uuid.uuid4().hex[:8]}"
        tokens[token] = {"type": "events", "created": datetime.now(timezone.utc)}
        _add_text(resp, NS_TSE, "SearchToken", token)

    elif "GetEventSearchResults" in action:
        resp = etree.SubElement(body, _qn(NS_TSE, "GetEventSearchResultsResponse"))
        result_list = etree.SubElement(resp, _qn(NS_TSE, "ResultList"))
        _add_text(result_list, NS_TSE, "SearchState", "Completed")

    elif "EndSearch" in action:
        etree.SubElement(body, _qn(NS_TSE, "EndSearchResponse"))
        req_bytes = await request.body()
        token = _extract_search_token(req_bytes)
        if token and token in tokens:
            tokens.pop(token, None)

    elif "GetServiceCapabilities" in action:
        resp = etree.SubElement(body, _qn(NS_TSE, "GetServiceCapabilitiesResponse"))
        caps = etree.SubElement(resp, _qn(NS_TSE, "Capabilities"))
        caps.set("MetadataSearch", "false")

    else:
        tag = action.split("}")[-1] if "}" in action else action
        if tag:
            etree.SubElement(body, _qn(NS_TSE, tag + "Response"))


def _extract_search_token(xml_bytes: bytes):
    try:
        root = etree.fromstring(xml_bytes)
        for tag in ("SearchToken", "{%s}SearchToken" % NS_TSE):
            el = root.find(".//" + tag)
            if el is not None:
                return el.text
    except Exception:
        pass
    return None


def _extract_time_range(xml_bytes: bytes):
    start, end = None, None
    try:
        root = etree.fromstring(xml_bytes)
        for tag in ("StartPoint", "{%s}StartPoint" % NS_TSE):
            el = root.find(".//" + tag)
            if el is not None and el.text:
                start = datetime.fromisoformat(el.text.replace("Z", "+00:00"))
        for tag in ("EndPoint", "{%s}EndPoint" % NS_TSE):
            el = root.find(".//" + tag)
            if el is not None and el.text:
                end = datetime.fromisoformat(el.text.replace("Z", "+00:00"))
    except Exception:
        pass
    return start, end
