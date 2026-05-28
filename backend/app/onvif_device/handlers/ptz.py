# =============================================================================
# ONVIF PTZ Service handler (virtual — forwards to camera ONVIF endpoint)
# Covers: GetServiceCapabilities, GetConfigurations, GetConfiguration,
#         GetPresets, GotoPreset, ContinuousMove, RelativeMove, AbsoluteMove,
#         Stop, GetStatus, GetNodes
# =============================================================================

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from lxml import etree
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.cameras.models import Camera
from ._common import (
    NS_TPTZ, NS_TT,
    _qn, _add_text,
    _extract_profile_token, _profile_token_to_camera_id, _extract_text_field,
)

logger = logging.getLogger(__name__)


async def dispatch(action: str, body: etree.Element, request: Request, db: AsyncSession,
                   get_cameras, get_camera_by_id, **ctx):
    if "GetServiceCapabilities" in action:
        resp = etree.SubElement(body, _qn(NS_TPTZ, "GetServiceCapabilitiesResponse"))
        caps = etree.SubElement(resp, _qn(NS_TPTZ, "Capabilities"))
        caps.set("EFlip", "false")
        caps.set("Reverse", "false")
        caps.set("GetCompatibleConfigurations", "false")
        caps.set("MoveStatus", "false")
        caps.set("StatusPosition", "false")

    elif "GetConfigurations" in action:
        resp = etree.SubElement(body, _qn(NS_TPTZ, "GetConfigurationsResponse"))
        cameras = await get_cameras(db)
        for cam in cameras:
            cfg = etree.SubElement(resp, _qn(NS_TPTZ, "PTZConfiguration"))
            cfg.set("token", f"ptz_{cam.id}")
            _add_text(cfg, NS_TT, "Name", f"PTZ {cam.name}")
            _add_text(cfg, NS_TT, "NodeToken", f"ptznode_{cam.id}")
            _add_text(cfg, NS_TT, "DefaultAbsolutePantTiltPositionSpace",
                      "http://www.onvif.org/ver10/tptz/PanTiltSpaces/PositionGenericSpace")
            _add_text(cfg, NS_TT, "DefaultAbsoluteZoomPositionSpace",
                      "http://www.onvif.org/ver10/tptz/ZoomSpaces/PositionGenericSpace")
            _add_text(cfg, NS_TT, "DefaultContinuousPanTiltVelocitySpace",
                      "http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace")
            _add_text(cfg, NS_TT, "DefaultContinuousZoomVelocitySpace",
                      "http://www.onvif.org/ver10/tptz/ZoomSpaces/VelocityGenericSpace")

    elif "GetConfiguration" in action and "GetConfigurations" not in action:
        resp = etree.SubElement(body, _qn(NS_TPTZ, "GetConfigurationResponse"))
        req_bytes = await request.body()
        cam_id = _extract_ptz_token(req_bytes)
        cam = await get_camera_by_id(db, cam_id) if cam_id else None
        if cam:
            cfg = etree.SubElement(resp, _qn(NS_TPTZ, "PTZConfiguration"))
            cfg.set("token", f"ptz_{cam.id}")
            _add_text(cfg, NS_TT, "Name", f"PTZ {cam.name}")
            _add_text(cfg, NS_TT, "NodeToken", f"ptznode_{cam.id}")

    elif "GetPresets" in action:
        resp = etree.SubElement(body, _qn(NS_TPTZ, "GetPresetsResponse"))
        req_bytes = await request.body()
        profile_token = _extract_profile_token(req_bytes)
        cam_id = _profile_token_to_camera_id(profile_token)
        cam = await get_camera_by_id(db, cam_id) if cam_id else None
        if cam:
            try:
                presets = await _forward_get_presets(cam)
                for preset in presets:
                    p = etree.SubElement(resp, _qn(NS_TPTZ, "Preset"))
                    p.set("token", str(preset.get("token", "")))
                    _add_text(p, NS_TT, "Name", preset.get("name", ""))
            except Exception as e:
                logger.debug(f"PTZ GetPresets forward failed for cam {cam_id}: {e}")

    elif "GotoPreset" in action:
        etree.SubElement(body, _qn(NS_TPTZ, "GotoPresetResponse"))
        req_bytes = await request.body()
        profile_token = _extract_profile_token(req_bytes)
        cam_id = _profile_token_to_camera_id(profile_token)
        cam = await get_camera_by_id(db, cam_id) if cam_id else None
        if cam:
            try:
                preset_token = _extract_text_field(req_bytes, "PresetToken")
                await _forward_goto_preset(cam, profile_token or f"profile_{cam.id}", preset_token or "")
            except Exception as e:
                logger.debug(f"PTZ GotoPreset forward failed: {e}")

    elif "ContinuousMove" in action:
        etree.SubElement(body, _qn(NS_TPTZ, "ContinuousMoveResponse"))
        req_bytes = await request.body()
        profile_token = _extract_profile_token(req_bytes)
        cam_id = _profile_token_to_camera_id(profile_token)
        cam = await get_camera_by_id(db, cam_id) if cam_id else None
        if cam:
            try:
                velocity = _extract_velocity(req_bytes)
                await _forward_move(cam, "continuous", velocity, profile_token)
            except Exception as e:
                logger.debug(f"PTZ ContinuousMove forward failed: {e}")

    elif "RelativeMove" in action:
        etree.SubElement(body, _qn(NS_TPTZ, "RelativeMoveResponse"))
        req_bytes = await request.body()
        profile_token = _extract_profile_token(req_bytes)
        cam_id = _profile_token_to_camera_id(profile_token)
        cam = await get_camera_by_id(db, cam_id) if cam_id else None
        if cam:
            try:
                translation = _extract_velocity(req_bytes)
                await _forward_move(cam, "relative", translation, profile_token)
            except Exception as e:
                logger.debug(f"PTZ RelativeMove forward failed: {e}")

    elif "AbsoluteMove" in action:
        etree.SubElement(body, _qn(NS_TPTZ, "AbsoluteMoveResponse"))
        req_bytes = await request.body()
        profile_token = _extract_profile_token(req_bytes)
        cam_id = _profile_token_to_camera_id(profile_token)
        cam = await get_camera_by_id(db, cam_id) if cam_id else None
        if cam:
            try:
                position = _extract_velocity(req_bytes)
                await _forward_move(cam, "absolute", position, profile_token)
            except Exception as e:
                logger.debug(f"PTZ AbsoluteMove forward failed: {e}")

    elif "Stop" in action:
        etree.SubElement(body, _qn(NS_TPTZ, "StopResponse"))
        req_bytes = await request.body()
        profile_token = _extract_profile_token(req_bytes)
        cam_id = _profile_token_to_camera_id(profile_token)
        cam = await get_camera_by_id(db, cam_id) if cam_id else None
        if cam:
            try:
                await _forward_stop(cam, profile_token)
            except Exception as e:
                logger.debug(f"PTZ Stop forward failed: {e}")

    elif "GetStatus" in action:
        resp = etree.SubElement(body, _qn(NS_TPTZ, "GetStatusResponse"))
        status = etree.SubElement(resp, _qn(NS_TPTZ, "PTZStatus"))
        pos = etree.SubElement(status, _qn(NS_TT, "Position"))
        pt = etree.SubElement(pos, _qn(NS_TT, "PanTilt"))
        pt.set("x", "0.0")
        pt.set("y", "0.0")
        z = etree.SubElement(pos, _qn(NS_TT, "Zoom"))
        z.set("x", "0.0")
        ms = etree.SubElement(status, _qn(NS_TT, "MoveStatus"))
        _add_text(ms, NS_TT, "PanTilt", "IDLE")
        _add_text(ms, NS_TT, "Zoom", "IDLE")
        _add_text(status, NS_TT, "UtcTime", datetime.now(timezone.utc).isoformat())

    elif "GetNodes" in action:
        resp = etree.SubElement(body, _qn(NS_TPTZ, "GetNodesResponse"))
        cameras = await get_cameras(db)
        for cam in cameras:
            node = etree.SubElement(resp, _qn(NS_TPTZ, "PTZNode"))
            node.set("token", f"ptznode_{cam.id}")
            node.set("FixedHomePosition", "false")
            node.set("GeoMove", "false")
            _add_text(node, NS_TT, "Name", f"PTZNode {cam.name}")
            _add_text(node, NS_TT, "MaximumNumberOfPresets", "16")

    else:
        tag = action.split("}")[-1] if "}" in action else action
        if tag:
            etree.SubElement(body, _qn(NS_TPTZ, tag + "Response"))


# ── Forward helpers ──────────────────────────────────────────────────────────

async def _forward_get_presets(cam: Camera) -> List[Dict[str, Any]]:
    try:
        from app.cameras.onvif_service import onvif_service
        from app.core.crypto import decrypt_value
        host = cam.onvif_host
        port = cam.onvif_port or 80
        username = decrypt_value(cam.onvif_username) if cam.onvif_username else "admin"
        password = decrypt_value(cam.onvif_password) if cam.onvif_password else "admin"
        profile_token = cam.onvif_profile_token
        if not host:
            return []
        return await onvif_service.get_presets(host, port, username, password, profile_token)
    except Exception as e:
        logger.debug(f"_forward_get_presets error for cam {cam.id}: {e}")
        return []


async def _forward_goto_preset(cam: Camera, profile_token: str, preset_token: str):
    try:
        from app.cameras.onvif_service import onvif_service
        from app.core.crypto import decrypt_value
        host = cam.onvif_host
        port = cam.onvif_port or 80
        username = decrypt_value(cam.onvif_username) if cam.onvif_username else "admin"
        password = decrypt_value(cam.onvif_password) if cam.onvif_password else "admin"
        cam_profile_token = cam.onvif_profile_token or profile_token
        if not host:
            return
        await onvif_service.goto_preset(host, port, username, password, preset_token, cam_profile_token)
    except Exception as e:
        logger.debug(f"_forward_goto_preset error for cam {cam.id}: {e}")


async def _forward_move(cam: Camera, move_type: str, params: dict, profile_token: str):
    try:
        from app.cameras.onvif_service import onvif_service
        from app.core.crypto import decrypt_value
        host = cam.onvif_host
        port = cam.onvif_port or 80
        username = decrypt_value(cam.onvif_username) if cam.onvif_username else "admin"
        password = decrypt_value(cam.onvif_password) if cam.onvif_password else "admin"
        cam_profile_token = cam.onvif_profile_token or profile_token or f"profile_{cam.id}"
        if not host:
            return
        if move_type == "continuous":
            await onvif_service.continuous_move(host, port, username, password, params, cam_profile_token)
        elif move_type == "relative":
            await onvif_service.relative_move(host, port, username, password, params, cam_profile_token)
        elif move_type == "absolute":
            await onvif_service.absolute_move(host, port, username, password, params, cam_profile_token)
    except Exception as e:
        logger.debug(f"_forward_move error for cam {cam.id}: {e}")


async def _forward_stop(cam: Camera, profile_token: str):
    try:
        from app.cameras.onvif_service import onvif_service
        from app.core.crypto import decrypt_value
        host = cam.onvif_host
        port = cam.onvif_port or 80
        username = decrypt_value(cam.onvif_username) if cam.onvif_username else "admin"
        password = decrypt_value(cam.onvif_password) if cam.onvif_password else "admin"
        cam_profile_token = cam.onvif_profile_token or profile_token or f"profile_{cam.id}"
        if not host:
            return
        await onvif_service.stop(host, port, username, password, cam_profile_token)
    except Exception as e:
        logger.debug(f"_forward_stop error for cam {cam.id}: {e}")


def _extract_ptz_token(xml_bytes: bytes) -> Optional[str]:
    try:
        root = etree.fromstring(xml_bytes)
        from ._common import NS_TPTZ as _TPTZ
        for tag in ("PTZConfigurationToken", "{%s}PTZConfigurationToken" % _TPTZ):
            el = root.find(".//" + tag)
            if el is not None:
                t = el.text or ""
                return t.replace("ptz_", "") if t.startswith("ptz_") else t
    except Exception:
        pass
    return None


def _extract_velocity(xml_bytes: bytes) -> dict:
    try:
        from ._common import NS_TPTZ as _TPTZ, NS_TT as _TT
        root = etree.fromstring(xml_bytes)
        vel = root.find(".//{%s}Velocity" % _TPTZ)
        if vel is not None:
            pt = vel.find("{%s}PanTilt" % _TT)
            zoom = vel.find("{%s}Zoom" % _TT)
            return {
                "x": float(pt.get("x", 0)) if pt is not None else 0.0,
                "y": float(pt.get("y", 0)) if pt is not None else 0.0,
                "z": float(zoom.get("x", 0)) if zoom is not None else 0.0,
            }
        pos = root.find(".//{%s}Position" % _TPTZ)
        if pos is not None:
            pt = pos.find("{%s}PanTilt" % _TT)
            zoom = pos.find("{%s}Zoom" % _TT)
            return {
                "x": float(pt.get("x", 0)) if pt is not None else 0.0,
                "y": float(pt.get("y", 0)) if pt is not None else 0.0,
                "z": float(zoom.get("x", 0)) if zoom is not None else 0.0,
            }
    except Exception:
        pass
    return {"x": 0.0, "y": 0.0, "z": 0.0}
