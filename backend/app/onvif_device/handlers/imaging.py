# =============================================================================
# ONVIF Imaging Service handler
# Covers: GetServiceCapabilities, GetImagingSettings, SetImagingSettings,
#         GetOptions, GetMoveOptions, Move, Stop, GetStatus
# =============================================================================

import logging
from typing import Optional

from lxml import etree
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.cameras.models import Camera
from ._common import (
    NS_TIMG, NS_TT,
    _qn, _add_text, _extract_text_field,
)

logger = logging.getLogger(__name__)

# Re-export SOAPFault reference from service module
_SOAPFault = None  # resolved at runtime via ctx


async def dispatch(action: str, body: etree.Element, request: Request, db: AsyncSession,
                   get_cameras, get_camera_by_id, soap_fault_cls=None, **ctx):
    _Fault = soap_fault_cls

    if "GetServiceCapabilities" in action:
        resp = etree.SubElement(body, _qn(NS_TIMG, "GetServiceCapabilitiesResponse"))
        caps = etree.SubElement(resp, _qn(NS_TIMG, "Capabilities"))
        caps.set("ImageStabilization", "false")
        caps.set("Presets", "false")

    elif "GetImagingSettings" in action:
        resp = etree.SubElement(body, _qn(NS_TIMG, "GetImagingSettingsResponse"))
        req_bytes = await request.body()
        vs_token = _extract_video_source_token(req_bytes)
        cam = await _camera_from_vs_token(db, vs_token, get_camera_by_id)
        if cam and cam.onvif_host:
            from app.cameras.onvif_service import onvif_service
            from app.core.crypto import decrypt_value
            try:
                img_settings = await onvif_service.get_imaging_settings(
                    cam.onvif_host, cam.onvif_port or 80,
                    decrypt_value(cam.onvif_username) or "admin",
                    decrypt_value(cam.onvif_password) or "admin",
                )
                _build_imaging_settings(resp, img_settings)
            except Exception as e:
                logger.debug(f"GetImagingSettings proxy failed for {cam.id}: {e}")
                _build_imaging_settings(resp, {})
        else:
            _build_imaging_settings(resp, {})

    elif "SetImagingSettings" in action:
        etree.SubElement(body, _qn(NS_TIMG, "SetImagingSettingsResponse"))
        req_bytes = await request.body()
        vs_token = _extract_video_source_token(req_bytes)
        cam = await _camera_from_vs_token(db, vs_token, get_camera_by_id)
        settings_patch = _extract_imaging_settings_patch(req_bytes)
        if cam and cam.onvif_host and settings_patch:
            from app.cameras.onvif_service import onvif_service
            from app.core.crypto import decrypt_value
            try:
                ok = await onvif_service.set_imaging_settings(
                    cam.onvif_host, cam.onvif_port or 80,
                    decrypt_value(cam.onvif_username) or "admin",
                    decrypt_value(cam.onvif_password) or "admin",
                    settings_patch,
                )
                if not ok and _Fault:
                    raise _Fault("ter:Action", "Camera rejected imaging settings")
            except Exception as e:
                logger.debug(f"SetImagingSettings proxy failed for {cam.id}: {e}")
                if _Fault:
                    raise _Fault("ter:Action", "Failed to apply imaging settings")

    elif "GetOptions" in action:
        resp = etree.SubElement(body, _qn(NS_TIMG, "GetOptionsResponse"))
        req_bytes = await request.body()
        vs_token = _extract_video_source_token(req_bytes)
        cam = await _camera_from_vs_token(db, vs_token, get_camera_by_id)
        if cam and cam.onvif_host:
            from app.cameras.onvif_service import onvif_service
            from app.core.crypto import decrypt_value
            try:
                opts = await onvif_service.get_imaging_options(
                    cam.onvif_host, cam.onvif_port or 80,
                    decrypt_value(cam.onvif_username) or "admin",
                    decrypt_value(cam.onvif_password) or "admin",
                )
                _build_imaging_options(resp, opts)
            except Exception as e:
                logger.debug(f"GetOptions proxy failed for {cam.id}: {e}")
                _build_imaging_options(resp, {})
        else:
            _build_imaging_options(resp, {})

    elif "GetMoveOptions" in action:
        resp = etree.SubElement(body, _qn(NS_TIMG, "GetMoveOptionsResponse"))
        move = etree.SubElement(resp, _qn(NS_TIMG, "MoveOptions"))
        abs_el = etree.SubElement(move, _qn(NS_TIMG, "Absolute"))
        _add_text(abs_el, NS_TT, "Position", "0 1")
        rel_el = etree.SubElement(move, _qn(NS_TIMG, "Relative"))
        _add_text(rel_el, NS_TT, "Distance", "-1 1")
        cont_el = etree.SubElement(move, _qn(NS_TIMG, "Continuous"))
        _add_text(cont_el, NS_TT, "Speed", "-1 1")

    elif "Move" in action:
        etree.SubElement(body, _qn(NS_TIMG, "MoveResponse"))
        req_bytes = await request.body()
        vs_token = _extract_video_source_token(req_bytes)
        cam = await _camera_from_vs_token(db, vs_token, get_camera_by_id)
        if cam and cam.onvif_host:
            from app.cameras.onvif_service import onvif_service
            from app.core.crypto import decrypt_value
            try:
                await onvif_service.move_focus(
                    cam.onvif_host, cam.onvif_port or 80,
                    decrypt_value(cam.onvif_username) or "admin",
                    decrypt_value(cam.onvif_password) or "admin",
                    mode="Auto",
                )
            except Exception as e:
                logger.debug(f"Move focus failed for {cam.id}: {e}")

    elif "Stop" in action:
        etree.SubElement(body, _qn(NS_TIMG, "StopResponse"))

    elif "GetStatus" in action:
        resp = etree.SubElement(body, _qn(NS_TIMG, "GetStatusResponse"))
        req_bytes = await request.body()
        vs_token = _extract_video_source_token(req_bytes)
        cam = await _camera_from_vs_token(db, vs_token, get_camera_by_id)
        if cam and cam.onvif_host:
            from app.cameras.onvif_service import onvif_service
            from app.core.crypto import decrypt_value
            try:
                img_settings = await onvif_service.get_imaging_settings(
                    cam.onvif_host, cam.onvif_port or 80,
                    decrypt_value(cam.onvif_username) or "admin",
                    decrypt_value(cam.onvif_password) or "admin",
                )
                status = etree.SubElement(resp, _qn(NS_TIMG, "Status"))
                _add_text(status, NS_TT, "Brightness", img_settings.get("brightness", 50))
                _add_text(status, NS_TT, "Contrast", img_settings.get("contrast", 50))
                _add_text(status, NS_TT, "ColorSaturation", img_settings.get("color_saturation", 50))
                _add_text(status, NS_TT, "Sharpness", img_settings.get("sharpness", 50))
            except Exception as e:
                logger.debug(f"GetStatus proxy failed for {cam.id}: {e}")
                status = etree.SubElement(resp, _qn(NS_TIMG, "Status"))
                _add_text(status, NS_TT, "Brightness", 50)
                _add_text(status, NS_TT, "Contrast", 50)
        else:
            status = etree.SubElement(resp, _qn(NS_TIMG, "Status"))
            _add_text(status, NS_TT, "Brightness", 50)
            _add_text(status, NS_TT, "Contrast", 50)

    else:
        tag = action.split("}")[-1] if "}" in action else action
        if tag:
            etree.SubElement(body, _qn(NS_TIMG, tag + "Response"))


# ── Builders ─────────────────────────────────────────────────────────────────

def _build_imaging_settings(parent: etree.Element, settings: dict):
    img = etree.SubElement(parent, _qn(NS_TIMG, "ImagingSettings"))
    _add_text(img, NS_TT, "Brightness", settings.get("brightness", 50))
    _add_text(img, NS_TT, "ColorSaturation", settings.get("color_saturation", 50))
    _add_text(img, NS_TT, "Contrast", settings.get("contrast", 50))
    _add_text(img, NS_TT, "Sharpness", settings.get("sharpness", 50))
    if settings.get("ir_cut_filter"):
        _add_text(img, NS_TT, "IrCutFilter", settings["ir_cut_filter"])
    if settings.get("wide_dynamic_range"):
        wdr = etree.SubElement(img, _qn(NS_TT, "WideDynamicRange"))
        _add_text(wdr, NS_TT, "Mode", settings["wide_dynamic_range"].get("mode", "OFF"))
        _add_text(wdr, NS_TT, "Level", settings["wide_dynamic_range"].get("level", 0))
    if settings.get("exposure"):
        exp = etree.SubElement(img, _qn(NS_TT, "Exposure"))
        _add_text(exp, NS_TT, "Mode", settings["exposure"].get("mode", "AUTO"))


def _build_imaging_options(parent: etree.Element, opts: dict):
    img_opts = etree.SubElement(parent, _qn(NS_TIMG, "ImagingOptions"))
    for field in ("brightness", "color_saturation", "contrast", "sharpness"):
        if field in opts:
            fmin = opts[field].get("min", 0)
            fmax = opts[field].get("max", 100)
            el = etree.SubElement(img_opts, _qn(NS_TT, field.capitalize()))
            rng = etree.SubElement(el, _qn(NS_TT, "MinMax"))
            _add_text(rng, NS_TT, "Min", fmin)
            _add_text(rng, NS_TT, "Max", fmax)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _extract_video_source_token(xml_bytes: bytes) -> Optional[str]:
    try:
        root = etree.fromstring((xml_bytes or b'').lstrip() if isinstance(xml_bytes, (bytes, bytearray)) else xml_bytes)
        for tag in ("VideoSourceToken", "{%s}VideoSourceToken" % NS_TT):
            el = root.find(".//" + tag)
            if el is not None:
                return el.text
    except Exception:
        pass
    return None


async def _camera_from_vs_token(db, vs_token: Optional[str], get_camera_by_id) -> Optional[Camera]:
    if not vs_token:
        return None
    cam_id = vs_token.replace("vs_", "") if vs_token.startswith("vs_") else vs_token
    return await get_camera_by_id(db, cam_id)


def _extract_imaging_settings_patch(xml_bytes: bytes) -> Optional[dict]:
    try:
        root = etree.fromstring((xml_bytes or b'').lstrip() if isinstance(xml_bytes, (bytes, bytearray)) else xml_bytes)
        patch = {}
        for tag in ("Brightness", "{%s}Brightness" % NS_TT):
            el = root.find(".//" + tag)
            if el is not None and el.text:
                patch["brightness"] = float(el.text)
        for tag in ("Contrast", "{%s}Contrast" % NS_TT):
            el = root.find(".//" + tag)
            if el is not None and el.text:
                patch["contrast"] = float(el.text)
        for tag in ("ColorSaturation", "{%s}ColorSaturation" % NS_TT):
            el = root.find(".//" + tag)
            if el is not None and el.text:
                patch["color_saturation"] = float(el.text)
        for tag in ("Sharpness", "{%s}Sharpness" % NS_TT):
            el = root.find(".//" + tag)
            if el is not None and el.text:
                patch["sharpness"] = float(el.text)
        for tag in ("IrCutFilter", "{%s}IrCutFilter" % NS_TT):
            el = root.find(".//" + tag)
            if el is not None and el.text:
                patch["ir_cut_filter"] = el.text
        return patch if patch else None
    except Exception:
        return None
