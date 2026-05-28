# =============================================================================
# ONVIF PTZ sub-module — continuous/relative/absolute move, stop, presets
# Extracted from cameras/onvif_service.py for maintainability.
# =============================================================================

import asyncio
import logging
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

try:
    from onvif import ONVIFCamera
    _HAS_ONVIF = True
except ImportError:
    _HAS_ONVIF = False


async def continuous_move(
    host: str, port: int, username: str, password: str,
    pan: float = 0.0, tilt: float = 0.0, zoom: float = 0.0, speed: float = 0.5,
    profile_token: Optional[str] = None,
) -> bool:
    if not _HAS_ONVIF:
        raise RuntimeError("python-onvif-zeep not installed")

    def _move():
        try:
            cam = ONVIFCamera(host, port, username, password)
            media = cam.create_media_service()
            ptz = cam.create_ptz_service()
            _pt = profile_token or media.GetProfiles()[0].token
            request = ptz.create_type("ContinuousMove")
            request.ProfileToken = _pt
            request.Velocity = {
                "PanTilt": {"x": pan * speed, "y": tilt * speed},
                "Zoom": {"x": zoom * speed},
            }
            ptz.ContinuousMove(request)
            return True
        except Exception as e:
            logger.error(f"PTZ move failed: {e}")
            return False

    return await asyncio.to_thread(_move)


async def relative_move(
    host: str, port: int, username: str, password: str,
    translation: dict, profile_token: Optional[str] = None,
) -> bool:
    if not _HAS_ONVIF:
        raise RuntimeError("python-onvif-zeep not installed")

    def _move():
        try:
            cam = ONVIFCamera(host, port, username, password)
            media = cam.create_media_service()
            ptz = cam.create_ptz_service()
            _pt = profile_token or media.GetProfiles()[0].token
            request = ptz.create_type("RelativeMove")
            request.ProfileToken = _pt
            request.Translation = {
                "PanTilt": {"x": translation.get("x", 0), "y": translation.get("y", 0)},
                "Zoom": {"x": translation.get("z", 0)},
            }
            ptz.RelativeMove(request)
            return True
        except Exception as e:
            logger.error(f"PTZ relative move failed: {e}")
            return False

    return await asyncio.to_thread(_move)


async def absolute_move(
    host: str, port: int, username: str, password: str,
    position: dict, profile_token: Optional[str] = None,
) -> bool:
    if not _HAS_ONVIF:
        raise RuntimeError("python-onvif-zeep not installed")

    def _move():
        try:
            cam = ONVIFCamera(host, port, username, password)
            media = cam.create_media_service()
            ptz = cam.create_ptz_service()
            _pt = profile_token or media.GetProfiles()[0].token
            request = ptz.create_type("AbsoluteMove")
            request.ProfileToken = _pt
            request.Position = {
                "PanTilt": {"x": position.get("x", 0), "y": position.get("y", 0)},
                "Zoom": {"x": position.get("z", 0)},
            }
            ptz.AbsoluteMove(request)
            return True
        except Exception as e:
            logger.error(f"PTZ absolute move failed: {e}")
            return False

    return await asyncio.to_thread(_move)


async def stop(
    host: str, port: int, username: str, password: str,
    profile_token: Optional[str] = None,
) -> bool:
    if not _HAS_ONVIF:
        return False

    def _stop():
        try:
            cam = ONVIFCamera(host, port, username, password)
            media = cam.create_media_service()
            ptz = cam.create_ptz_service()
            _pt = profile_token or media.GetProfiles()[0].token
            ptz.Stop({"ProfileToken": _pt, "PanTilt": True, "Zoom": True})
            return True
        except Exception as e:
            logger.error(f"PTZ stop failed: {e}")
            return False

    return await asyncio.to_thread(_stop)


async def get_presets(
    host: str, port: int, username: str, password: str,
    profile_token: Optional[str] = None,
) -> List[Dict[str, str]]:
    if not _HAS_ONVIF:
        return []

    def _presets():
        try:
            cam = ONVIFCamera(host, port, username, password)
            media = cam.create_media_service()
            ptz = cam.create_ptz_service()
            _pt = profile_token or media.GetProfiles()[0].token
            presets = ptz.GetPresets({"ProfileToken": _pt})
            return [{"token": str(p.token), "name": str(p.Name)} for p in presets]
        except Exception as e:
            logger.error(f"Get presets failed: {e}")
            return []

    return await asyncio.to_thread(_presets)


async def goto_preset(
    host: str, port: int, username: str, password: str,
    preset_token: str, profile_token: Optional[str] = None,
) -> bool:
    if not _HAS_ONVIF:
        return False

    def _goto():
        try:
            cam = ONVIFCamera(host, port, username, password)
            media = cam.create_media_service()
            ptz = cam.create_ptz_service()
            _pt = profile_token or media.GetProfiles()[0].token
            ptz.GotoPreset({"ProfileToken": _pt, "PresetToken": preset_token})
            return True
        except Exception as e:
            logger.error(f"Goto preset failed: {e}")
            return False

    return await asyncio.to_thread(_goto)


async def set_preset(
    host: str, port: int, username: str, password: str,
    preset_name: str, profile_token: Optional[str] = None,
) -> Optional[str]:
    if not _HAS_ONVIF:
        return None

    def _set():
        try:
            cam = ONVIFCamera(host, port, username, password)
            media = cam.create_media_service()
            ptz = cam.create_ptz_service()
            _pt = profile_token or media.GetProfiles()[0].token
            result = ptz.SetPreset({"ProfileToken": _pt, "PresetName": preset_name})
            token = getattr(result, "PresetToken", None) or getattr(result, "token", None)
            return str(token) if token else None
        except Exception as e:
            logger.error(f"Set preset failed: {e}")
            return None

    return await asyncio.to_thread(_set)


async def delete_preset(
    host: str, port: int, username: str, password: str,
    preset_token: str, profile_token: Optional[str] = None,
) -> bool:
    if not _HAS_ONVIF:
        return False

    def _delete():
        try:
            cam = ONVIFCamera(host, port, username, password)
            media = cam.create_media_service()
            ptz = cam.create_ptz_service()
            _pt = profile_token or media.GetProfiles()[0].token
            ptz.RemovePreset({"ProfileToken": _pt, "PresetToken": preset_token})
            return True
        except Exception as e:
            logger.error(f"Delete preset failed: {e}")
            return False

    return await asyncio.to_thread(_delete)


async def check_ptz_capable(host: str, port: int, username: str, password: str) -> bool:
    if not _HAS_ONVIF:
        return False

    def _check():
        try:
            cam = ONVIFCamera(host, port, username, password)
            media = cam.create_media_service()
            profiles = media.GetProfiles()
            return any(hasattr(p, "PTZConfiguration") and p.PTZConfiguration for p in profiles)
        except Exception:
            return False

    return await asyncio.to_thread(_check)
