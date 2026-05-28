# =============================================================================
# ONVIF Media2 Service (Profile T) handler
# Uses tr2: namespace. Covers: GetProfiles, GetStreamUri, GetSnapshotUri,
# GetVideoSources, GetVideoSourceConfigurations, GetVideoEncoderConfigurations,
# GetMetadataConfigurations, GetAnalyticsConfigurations, GetMasks, GetOSDs,
# GetServiceCapabilities, GetProfile
# =============================================================================

import logging
from typing import Optional

from lxml import etree
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.cameras.models import Camera
from ._common import (
    NS_TR2, NS_TT,
    _qn, _add_text, _base_xaddr, _get_external_host,
    _extract_profile_token, _profile_token_to_camera_id,
)
from .media1 import _parse_resolution, _parse_bitrate, _camera_rtsp_url

logger = logging.getLogger(__name__)


async def dispatch(action: str, body: etree.Element, request: Request, db: AsyncSession,
                   get_cameras, get_camera_by_id, **ctx):
    if "GetProfiles" in action:
        resp = etree.SubElement(body, _qn(NS_TR2, "GetProfilesResponse"))
        cameras = await get_cameras(db)
        for cam in cameras:
            _build_media2_profile(resp, cam)

    elif "GetStreamUri" in action:
        resp = etree.SubElement(body, _qn(NS_TR2, "GetStreamUriResponse"))
        profile_token = _extract_profile_token(await request.body())
        cam_id = _profile_token_to_camera_id(profile_token)
        cam = await get_camera_by_id(db, cam_id) if cam_id else None
        uri = _camera_rtsp_url(request, cam) if cam else ""
        _add_text(resp, NS_TR2, "Uri", uri)
        _add_text(resp, NS_TR2, "InvalidAfterConnect", "false")
        _add_text(resp, NS_TR2, "InvalidAfterReboot", "false")
        _add_text(resp, NS_TR2, "Timeout", "PT0S")

    elif "GetSnapshotUri" in action:
        resp = etree.SubElement(body, _qn(NS_TR2, "GetSnapshotUriResponse"))
        profile_token = _extract_profile_token(await request.body())
        cam_id = _profile_token_to_camera_id(profile_token)
        base = _base_xaddr(request)
        uri = f"{base}/api/cameras/{cam_id}/snapshot" if cam_id else ""
        _add_text(resp, NS_TR2, "Uri", uri)

    elif "GetVideoSources" in action:
        resp = etree.SubElement(body, _qn(NS_TR2, "GetVideoSourcesResponse"))
        cameras = await get_cameras(db)
        for cam in cameras:
            vs = etree.SubElement(resp, _qn(NS_TT, "VideoSources"))
            vs.set("token", f"vs_{cam.id}")
            res = etree.SubElement(vs, _qn(NS_TT, "Resolution"))
            w, h = _parse_resolution(cam.resolution)
            _add_text(res, NS_TT, "Width", w)
            _add_text(res, NS_TT, "Height", h)
            _add_text(vs, NS_TT, "Framerate", cam.fps or 25)

    elif "GetVideoSourceConfigurations" in action:
        resp = etree.SubElement(body, _qn(NS_TR2, "GetVideoSourceConfigurationsResponse"))
        cameras = await get_cameras(db)
        for cam in cameras:
            vsc = etree.SubElement(resp, _qn(NS_TT, "Configurations"))
            vsc.set("token", f"vsc_{cam.id}")
            _add_text(vsc, NS_TT, "Name", f"VideoSource {cam.name}")
            _add_text(vsc, NS_TT, "UseCount", "1")
            _add_text(vsc, NS_TT, "SourceToken", f"vs_{cam.id}")
            bounds = etree.SubElement(vsc, _qn(NS_TT, "Bounds"))
            w, h = _parse_resolution(cam.resolution)
            bounds.set("x", "0")
            bounds.set("y", "0")
            bounds.set("width", str(w))
            bounds.set("height", str(h))

    elif "GetVideoEncoderConfigurations" in action:
        resp = etree.SubElement(body, _qn(NS_TR2, "GetVideoEncoderConfigurationsResponse"))
        cameras = await get_cameras(db)
        for cam in cameras:
            from .media1 import _build_vec_element
            _build_vec_element(resp, cam, NS_TT)

    elif "GetMetadataConfigurations" in action:
        etree.SubElement(body, _qn(NS_TR2, "GetMetadataConfigurationsResponse"))

    elif "GetAnalyticsConfigurations" in action:
        etree.SubElement(body, _qn(NS_TR2, "GetAnalyticsConfigurationsResponse"))

    elif "GetMasks" in action:
        etree.SubElement(body, _qn(NS_TR2, "GetMasksResponse"))

    elif "GetOSDs" in action:
        etree.SubElement(body, _qn(NS_TR2, "GetOSDsResponse"))

    elif "GetServiceCapabilities" in action:
        resp = etree.SubElement(body, _qn(NS_TR2, "GetServiceCapabilitiesResponse"))
        caps = etree.SubElement(resp, _qn(NS_TR2, "Capabilities"))
        caps.set("ProfileCapabilities", "Streaming")
        sc = etree.SubElement(caps, _qn(NS_TR2, "StreamingCapabilities"))
        sc.set("RTPMulticast", "false")
        sc.set("RTP_TCP", "true")
        sc.set("RTP_RTSP_TCP", "true")

    elif "GetProfile" in action and "GetProfiles" not in action:
        resp = etree.SubElement(body, _qn(NS_TR2, "GetProfileResponse"))
        req_bytes = await request.body()
        profile_token = _extract_profile_token(req_bytes)
        cam_id = _profile_token_to_camera_id(profile_token)
        cam = await get_camera_by_id(db, cam_id) if cam_id else None
        if cam:
            _build_media2_profile(resp, cam)

    else:
        tag = action.split("}")[-1] if "}" in action else action
        if tag:
            etree.SubElement(body, _qn(NS_TR2, tag + "Response"))


def _build_media2_profile(parent: etree.Element, cam: Camera):
    """Build Media2 profile element (Profile T)."""
    prof = etree.SubElement(parent, _qn(NS_TR2, "Profiles"))
    prof.set("token", f"profile_{cam.id}")
    prof.set("fixed", "false")
    _add_text(prof, NS_TR2, "Name", cam.name)
    configs = etree.SubElement(prof, _qn(NS_TR2, "Configurations"))

    vsc = etree.SubElement(configs, _qn(NS_TT, "VideoSource"))
    vsc.set("token", f"vsc_{cam.id}")
    _add_text(vsc, NS_TT, "Name", f"VideoSource {cam.name}")
    _add_text(vsc, NS_TT, "UseCount", "1")
    _add_text(vsc, NS_TT, "SourceToken", f"vs_{cam.id}")
    bounds = etree.SubElement(vsc, _qn(NS_TT, "Bounds"))
    w, h = _parse_resolution(cam.resolution)
    bounds.set("x", "0")
    bounds.set("y", "0")
    bounds.set("width", str(w))
    bounds.set("height", str(h))

    vec = etree.SubElement(configs, _qn(NS_TT, "VideoEncoder"))
    vec.set("token", f"vec_{cam.id}")
    _add_text(vec, NS_TT, "Name", f"Encoder {cam.name}")
    _add_text(vec, NS_TT, "UseCount", "1")
    codec = (cam.codec or "H264").upper()
    if codec not in ("H264", "H265", "JPEG"):
        codec = "H264"
    _add_text(vec, NS_TT, "Encoding", codec)
    res = etree.SubElement(vec, _qn(NS_TT, "Resolution"))
    _add_text(res, NS_TT, "Width", w)
    _add_text(res, NS_TT, "Height", h)
    rate = etree.SubElement(vec, _qn(NS_TT, "RateControl"))
    _add_text(rate, NS_TT, "FrameRateLimit", cam.fps or 25)
    _add_text(rate, NS_TT, "EncodingInterval", "1")
    _add_text(rate, NS_TT, "BitrateLimit", _parse_bitrate(cam.bitrate))
