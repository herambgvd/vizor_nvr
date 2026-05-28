# =============================================================================
# ONVIF Media Service (Profile S) handler
# Covers: GetProfiles, GetStreamUri, GetSnapshotUri, GetVideoSources,
#         GetVideoSourceConfigurations, GetVideoEncoderConfigurations,
#         GetAudioSources, GetAudioEncoderConfiguration(s),
#         GetCompatibleAudioEncoderConfigurations, GetMetadataConfigurations,
#         GetProfile, GetCompatibleVideoEncoderConfigurations,
#         GetVideoEncoderConfigurationOptions
# =============================================================================

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict

from lxml import etree
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.cameras.models import Camera
from ._common import (
    NS_TRT, NS_TR2, NS_TT,
    _qn, _add_text, _base_xaddr, _get_external_host,
    _extract_profile_token, _profile_token_to_camera_id, _extract_text_field,
)

logger = logging.getLogger(__name__)

# ── Audio encoder configuration cache ────────────────────────────────────────
_audio_encoder_cache: Dict[str, Tuple[list, datetime]] = {}
_AUDIO_CACHE_TTL = 300  # 5 minutes


async def dispatch(action: str, body: etree.Element, request: Request, db: AsyncSession,
                   get_cameras, get_camera_by_id, **ctx):
    if "GetProfiles" in action:
        resp = etree.SubElement(body, _qn(NS_TRT, "GetProfilesResponse"))
        cameras = await get_cameras(db)
        for cam in cameras:
            _build_media_profile(resp, cam)

    elif "GetStreamUri" in action:
        resp = etree.SubElement(body, _qn(NS_TRT, "GetStreamUriResponse"))
        profile_token = _extract_profile_token(await request.body())
        cam_id = _profile_token_to_camera_id(profile_token)
        cam = await get_camera_by_id(db, cam_id) if cam_id else None
        media_uri = etree.SubElement(resp, _qn(NS_TRT, "MediaUri"))
        uri = _camera_rtsp_url(request, cam) if cam else ""
        _add_text(media_uri, NS_TT, "Uri", uri)
        _add_text(media_uri, NS_TT, "InvalidAfterConnect", "false")
        _add_text(media_uri, NS_TT, "InvalidAfterReboot", "false")
        _add_text(media_uri, NS_TT, "Timeout", "PT0S")

    elif "GetSnapshotUri" in action:
        resp = etree.SubElement(body, _qn(NS_TRT, "GetSnapshotUriResponse"))
        profile_token = _extract_profile_token(await request.body())
        cam_id = _profile_token_to_camera_id(profile_token)
        base = _base_xaddr(request)
        uri = f"{base}/api/cameras/{cam_id}/snapshot" if cam_id else ""
        media_uri = etree.SubElement(resp, _qn(NS_TRT, "MediaUri"))
        _add_text(media_uri, NS_TT, "Uri", uri)
        _add_text(media_uri, NS_TT, "InvalidAfterConnect", "false")
        _add_text(media_uri, NS_TT, "InvalidAfterReboot", "false")
        _add_text(media_uri, NS_TT, "Timeout", "PT0S")

    elif "GetVideoSources" in action:
        resp = etree.SubElement(body, _qn(NS_TRT, "GetVideoSourcesResponse"))
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
        resp = etree.SubElement(body, _qn(NS_TRT, "GetVideoSourceConfigurationsResponse"))
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
        resp = etree.SubElement(body, _qn(NS_TRT, "GetVideoEncoderConfigurationsResponse"))
        cameras = await get_cameras(db)
        for cam in cameras:
            _build_vec_element(resp, cam, NS_TT)

    elif "GetAudioSources" in action:
        etree.SubElement(body, _qn(NS_TRT, "GetAudioSourcesResponse"))

    elif "GetAudioEncoderConfiguration" in action and "GetAudioEncoderConfigurations" not in action:
        resp = etree.SubElement(body, _qn(NS_TRT, "GetAudioEncoderConfigurationResponse"))
        req_bytes = await request.body()
        aec_token = _extract_text_field(req_bytes, "ConfigurationToken") or ""
        cam_id = aec_token.replace("aec_", "") if aec_token.startswith("aec_") else None
        cam = await get_camera_by_id(db, cam_id) if cam_id else None
        if cam:
            cfgs = await _get_audio_encoder_configs(cam)
            for cfg in cfgs:
                _build_aec_element(resp, cam.id, cfg, NS_TRT)

    elif "GetAudioEncoderConfigurations" in action:
        resp = etree.SubElement(body, _qn(NS_TRT, "GetAudioEncoderConfigurationsResponse"))
        cameras = await get_cameras(db)
        for cam in cameras:
            cfgs = await _get_audio_encoder_configs(cam)
            for cfg in cfgs:
                _build_aec_element(resp, cam.id, cfg, NS_TRT)

    elif "GetCompatibleAudioEncoderConfigurations" in action:
        resp = etree.SubElement(body, _qn(NS_TRT, "GetCompatibleAudioEncoderConfigurationsResponse"))
        req_bytes = await request.body()
        profile_token = _extract_profile_token(req_bytes)
        cam_id = _profile_token_to_camera_id(profile_token)
        cam = await get_camera_by_id(db, cam_id) if cam_id else None
        if cam:
            cfgs = await _get_audio_encoder_configs(cam)
            for cfg in cfgs:
                _build_aec_element(resp, cam.id, cfg, NS_TRT)

    elif "GetMetadataConfigurations" in action:
        etree.SubElement(body, _qn(NS_TRT, "GetMetadataConfigurationsResponse"))

    elif "GetProfile" in action and "GetProfiles" not in action:
        resp = etree.SubElement(body, _qn(NS_TRT, "GetProfileResponse"))
        req_bytes = await request.body()
        profile_token = _extract_profile_token(req_bytes)
        cam_id = _profile_token_to_camera_id(profile_token)
        cam = await get_camera_by_id(db, cam_id) if cam_id else None
        if cam:
            _build_media_profile(resp, cam)

    elif "GetCompatibleVideoEncoderConfigurations" in action:
        resp = etree.SubElement(body, _qn(NS_TRT, "GetCompatibleVideoEncoderConfigurationsResponse"))
        cameras = await get_cameras(db)
        for cam in cameras:
            _build_vec_element(resp, cam, NS_TT)

    elif "GetVideoEncoderConfigurationOptions" in action:
        resp = etree.SubElement(body, _qn(NS_TRT, "GetVideoEncoderConfigurationOptionsResponse"))
        opts = etree.SubElement(resp, _qn(NS_TRT, "Options"))
        for encoding in ("H264", "H265", "JPEG"):
            enc_opt = etree.SubElement(opts, _qn(NS_TT, "H264" if encoding == "H264" else ("H264" if encoding == "H265" else "JPEG")))
            res_range = etree.SubElement(enc_opt, _qn(NS_TT, "ResolutionsAvailable"))
            r = etree.SubElement(res_range, _qn(NS_TT, "Width"))
            r.text = "1920"
            r2 = etree.SubElement(res_range, _qn(NS_TT, "Height"))
            r2.text = "1080"

    else:
        tag = action.split("}")[-1] if "}" in action else action
        if tag:
            etree.SubElement(body, _qn(NS_TRT, tag + "Response"))


# ── Profile / encoder builders ───────────────────────────────────────────────

def _build_media_profile(parent: etree.Element, cam: Camera):
    prof = etree.SubElement(parent, _qn(NS_TT, "Profiles"))
    prof.set("token", f"profile_{cam.id}")
    prof.set("fixed", "false")
    _add_text(prof, NS_TT, "Name", cam.name)

    vsc = etree.SubElement(prof, _qn(NS_TT, "VideoSourceConfiguration"))
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

    _build_vec_element(prof, cam, NS_TT)


def _build_vec_element(parent: etree.Element, cam: Camera, ns: str):
    """Build VideoEncoderConfiguration element."""
    cfg = etree.SubElement(parent, _qn(ns, "VideoEncoderConfiguration"))
    cfg.set("token", f"vec_{cam.id}")
    _add_text(cfg, ns, "Name", f"Encoder {cam.name}")
    _add_text(cfg, ns, "UseCount", "1")
    codec = (cam.codec or "H264").upper()
    if codec == "H265":
        codec = "H265"
    elif codec not in ("H264", "JPEG", "MPEG4"):
        codec = "H264"
    _add_text(cfg, ns, "Encoding", codec)
    res = etree.SubElement(cfg, _qn(ns, "Resolution"))
    w, h = _parse_resolution(cam.resolution)
    _add_text(res, ns, "Width", w)
    _add_text(res, ns, "Height", h)
    rate = etree.SubElement(cfg, _qn(ns, "RateControl"))
    _add_text(rate, ns, "FrameRateLimit", cam.fps or 25)
    _add_text(rate, ns, "EncodingInterval", "1")
    _add_text(rate, ns, "BitrateLimit", _parse_bitrate(cam.bitrate))
    if codec == "H264":
        h264 = etree.SubElement(cfg, _qn(ns, "H264"))
        _add_text(h264, ns, "GovLength", 30)
        _add_text(h264, ns, "H264Profile", "Main")


def _build_aec_element(parent: etree.Element, cam_id: str, cfg: dict, ns: str):
    """Build AudioEncoderConfiguration element."""
    aec = etree.SubElement(parent, _qn(ns, "Configurations"))
    aec.set("token", cfg.get("token", f"aec_{cam_id}"))
    _add_text(aec, NS_TT, "Name", cfg.get("name", f"Audio {cam_id}"))
    _add_text(aec, NS_TT, "UseCount", cfg.get("use_count", "1"))
    _add_text(aec, NS_TT, "Encoding", cfg.get("encoding", "AAC"))
    _add_text(aec, NS_TT, "Bitrate", cfg.get("bitrate", "64"))
    _add_text(aec, NS_TT, "SampleRate", cfg.get("sample_rate", "8000"))
    multicast = etree.SubElement(aec, _qn(NS_TT, "Multicast"))
    addr = etree.SubElement(multicast, _qn(NS_TT, "Address"))
    _add_text(addr, NS_TT, "Type", "IPv4")
    _add_text(addr, NS_TT, "IPv4Address", "0.0.0.0")
    _add_text(multicast, NS_TT, "Port", "0")
    _add_text(multicast, NS_TT, "TTL", "1")
    _add_text(multicast, NS_TT, "AutoStart", "false")
    _add_text(aec, NS_TT, "SessionTimeout", "PT0S")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _camera_rtsp_url(request: Request, cam: Optional[Camera]) -> str:
    if not cam:
        return ""
    host = _get_external_host(request).split(":")[0]
    return f"rtsp://{host}:{settings.GO2RTC_RTSP_PORT}/{cam.id}"


def _parse_resolution(res: Optional[str]):
    if not res:
        return 1920, 1080
    try:
        parts = str(res).lower().split("x")
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
    except Exception:
        pass
    return 1920, 1080


def _parse_bitrate(bitrate: Optional[str]) -> int:
    if not bitrate:
        return 4096
    try:
        return int(str(bitrate).replace("kbps", "").replace(" ", ""))
    except Exception:
        return 4096


async def _get_audio_encoder_configs(cam: Camera) -> list:
    cache_entry = _audio_encoder_cache.get(cam.id)
    if cache_entry:
        cached_list, cached_at = cache_entry
        if (datetime.now(timezone.utc) - cached_at).total_seconds() < _AUDIO_CACHE_TTL:
            return cached_list
    configs = await _fetch_audio_encoder_configs(cam)
    _audio_encoder_cache[cam.id] = (configs, datetime.now(timezone.utc))
    return configs


async def _fetch_audio_encoder_configs(cam: Camera) -> list:
    try:
        from app.cameras.onvif_service import _HAS_ONVIF
        if not _HAS_ONVIF:
            return []
        from onvif import ONVIFCamera
        from app.core.crypto import decrypt_value
        host = cam.onvif_host
        if not host:
            return []
        port = cam.onvif_port or 80
        username = decrypt_value(cam.onvif_username) if cam.onvif_username else "admin"
        password = decrypt_value(cam.onvif_password) if cam.onvif_password else "admin"

        def _query():
            try:
                onvif_cam = ONVIFCamera(host, port, username, password)
                media = onvif_cam.create_media_service()
                result = media.GetAudioEncoderConfigurations()
                configs = []
                for cfg in (result or []):
                    configs.append({
                        "token": str(getattr(cfg, "token", f"aec_{cam.id}")),
                        "name": str(getattr(cfg, "Name", f"Audio {cam.name}")),
                        "use_count": str(getattr(cfg, "UseCount", "1")),
                        "encoding": str(getattr(cfg, "Encoding", "AAC")),
                        "bitrate": str(getattr(cfg, "Bitrate", "64")),
                        "sample_rate": str(getattr(cfg, "SampleRate", "8000")),
                    })
                return configs
            except Exception as e:
                logger.debug(f"Audio encoder query failed for cam {cam.id}: {e}")
                return []

        return await asyncio.to_thread(_query)
    except Exception as e:
        logger.debug(f"_fetch_audio_encoder_configs error: {e}")
        return []
