# =============================================================================
# ONVIF Service — discovery + PTZ via python-onvif or go2rtc
# =============================================================================
# Discovery: WS-Discovery to scan LAN for ONVIF cameras.
# PTZ: Direct ONVIF SOAP calls for pan/tilt/zoom/presets.
# Stream URIs: Query ONVIF camera to auto-fill main + sub stream URLs.
#
# All blocking ONVIF calls are offloaded to threads via asyncio.to_thread().
# =============================================================================

import asyncio
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# Optional imports — gracefully degrade if not installed
try:
    from onvif import ONVIFCamera
    _HAS_ONVIF = True
except ImportError:
    _HAS_ONVIF = False
    logger.info("python-onvif-zeep not installed — ONVIF PTZ disabled. pip install onvif-zeep")

try:
    from wsdiscovery import WSDiscovery
    _HAS_WSDISCOVERY = True
except ImportError:
    _HAS_WSDISCOVERY = False
    logger.info("wsdiscovery not installed — ONVIF discovery disabled. pip install WSDiscovery")


class ONVIFService:
    """High-level async wrapper around ONVIF discovery and PTZ operations."""

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    async def discover(self, timeout: int = 5) -> List[Dict[str, Any]]:
        """
        Scan the local network for ONVIF-compliant cameras.
        Returns list of dicts with ip, port, name, manufacturer, model.
        """
        if not _HAS_WSDISCOVERY:
            raise RuntimeError("WSDiscovery not installed. pip install WSDiscovery")

        def _scan():
            results = []
            wsd = WSDiscovery()
            wsd.start()
            services = wsd.searchServices(timeout=timeout)
            for svc in services:
                types = svc.getTypes()
                # Filter for NetworkVideoTransmitter (ONVIF cameras)
                is_nvt = any("NetworkVideoTransmitter" in str(t) for t in types)
                if not is_nvt:
                    continue
                for xaddr in svc.getXAddrs():
                    try:
                        from urllib.parse import urlparse
                        parsed = urlparse(xaddr)
                        results.append({
                            "ip": parsed.hostname,
                            "port": parsed.port or 80,
                            "xaddr": xaddr,
                            "name": None,
                            "manufacturer": None,
                            "model": None,
                        })
                    except Exception:
                        pass
            wsd.stop()
            return results

        devices = await asyncio.to_thread(_scan)

        # Optionally enrich with device info
        enriched = []
        for dev in devices:
            info = await self.get_device_info(dev["ip"], dev["port"])
            dev.update(info or {})
            enriched.append(dev)

        return enriched

    # ------------------------------------------------------------------
    # Device info & stream URIs
    # ------------------------------------------------------------------

    async def get_device_info(
        self, host: str, port: int = 80,
        username: str = "admin", password: str = "admin",
    ) -> Optional[Dict[str, Any]]:
        """Query device info (manufacturer, model, firmware)."""
        if not _HAS_ONVIF:
            return None

        def _query():
            try:
                cam = ONVIFCamera(host, port, username, password)
                info = cam.devicemgmt.GetDeviceInformation()
                return {
                    "manufacturer": info.Manufacturer,
                    "model": info.Model,
                    "name": info.Model,
                    "firmware": info.FirmwareVersion,
                }
            except Exception as e:
                logger.warning(f"ONVIF info query failed for {host}: {e}")
                return None

        return await asyncio.to_thread(_query)

    async def get_stream_uris(
        self, host: str, port: int = 80,
        username: str = "admin", password: str = "admin",
    ) -> Dict[str, Optional[str]]:
        """
        Query ONVIF camera for main and sub stream RTSP URLs.
        Returns {"main_stream_url": "rtsp://...", "sub_stream_url": "rtsp://..."}.
        """
        if not _HAS_ONVIF:
            return {"main_stream_url": None, "sub_stream_url": None}

        def _get_uris():
            try:
                cam = ONVIFCamera(host, port, username, password)
                media = cam.create_media_service()
                profiles = media.GetProfiles()

                uris = {"main_stream_url": None, "sub_stream_url": None}

                for i, profile in enumerate(profiles[:2]):  # main + sub
                    try:
                        stream_setup = {
                            "Stream": "RTP-Unicast",
                            "Transport": {"Protocol": "RTSP"},
                        }
                        uri_resp = media.GetStreamUri({
                            "StreamSetup": stream_setup,
                            "ProfileToken": profile.token,
                        })
                        url = str(uri_resp.Uri)
                        # Inject credentials into RTSP URL
                        if username and "://" in url:
                            proto, rest = url.split("://", 1)
                            url = f"{proto}://{username}:{password}@{rest}"

                        if i == 0:
                            uris["main_stream_url"] = url
                        else:
                            uris["sub_stream_url"] = url
                    except Exception as e:
                        logger.warning(f"Failed to get stream URI for profile {i}: {e}")

                return uris
            except Exception as e:
                logger.error(f"ONVIF stream URI query failed for {host}: {e}")
                return {"main_stream_url": None, "sub_stream_url": None}

        return await asyncio.to_thread(_get_uris)

    # ------------------------------------------------------------------
    # PTZ Control
    # ------------------------------------------------------------------

    async def continuous_move(
        self, host: str, port: int, username: str, password: str,
        pan: float = 0.0, tilt: float = 0.0, zoom: float = 0.0, speed: float = 0.5,
    ) -> bool:
        """Start continuous PTZ movement. Call stop() to halt."""
        if not _HAS_ONVIF:
            raise RuntimeError("python-onvif-zeep not installed")

        def _move():
            try:
                cam = ONVIFCamera(host, port, username, password)
                media = cam.create_media_service()
                ptz = cam.create_ptz_service()
                profiles = media.GetProfiles()
                profile_token = profiles[0].token

                request = ptz.create_type("ContinuousMove")
                request.ProfileToken = profile_token
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

    async def stop(
        self, host: str, port: int, username: str, password: str,
    ) -> bool:
        """Stop all PTZ movement."""
        if not _HAS_ONVIF:
            return False

        def _stop():
            try:
                cam = ONVIFCamera(host, port, username, password)
                media = cam.create_media_service()
                ptz = cam.create_ptz_service()
                profile_token = media.GetProfiles()[0].token
                ptz.Stop({"ProfileToken": profile_token, "PanTilt": True, "Zoom": True})
                return True
            except Exception as e:
                logger.error(f"PTZ stop failed: {e}")
                return False

        return await asyncio.to_thread(_stop)

    async def get_presets(
        self, host: str, port: int, username: str, password: str,
    ) -> List[Dict[str, str]]:
        if not _HAS_ONVIF:
            return []

        def _presets():
            try:
                cam = ONVIFCamera(host, port, username, password)
                media = cam.create_media_service()
                ptz = cam.create_ptz_service()
                profile_token = media.GetProfiles()[0].token
                presets = ptz.GetPresets({"ProfileToken": profile_token})
                return [{"token": str(p.token), "name": str(p.Name)} for p in presets]
            except Exception as e:
                logger.error(f"Get presets failed: {e}")
                return []

        return await asyncio.to_thread(_presets)

    async def goto_preset(
        self, host: str, port: int, username: str, password: str,
        preset_token: str,
    ) -> bool:
        if not _HAS_ONVIF:
            return False

        def _goto():
            try:
                cam = ONVIFCamera(host, port, username, password)
                media = cam.create_media_service()
                ptz = cam.create_ptz_service()
                profile_token = media.GetProfiles()[0].token
                ptz.GotoPreset({
                    "ProfileToken": profile_token,
                    "PresetToken": preset_token,
                })
                return True
            except Exception as e:
                logger.error(f"Goto preset failed: {e}")
                return False

        return await asyncio.to_thread(_goto)

    async def set_preset(
        self, host: str, port: int, username: str, password: str,
        preset_name: str,
    ) -> Optional[str]:
        """Save current position as a named preset. Returns preset token."""
        if not _HAS_ONVIF:
            return None

        def _set():
            try:
                cam = ONVIFCamera(host, port, username, password)
                media = cam.create_media_service()
                ptz = cam.create_ptz_service()
                profile_token = media.GetProfiles()[0].token
                result = ptz.SetPreset({
                    "ProfileToken": profile_token,
                    "PresetName": preset_name,
                })
                return str(result)
            except Exception as e:
                logger.error(f"Set preset failed: {e}")
                return None

        return await asyncio.to_thread(_set)

    async def delete_preset(
        self, host: str, port: int, username: str, password: str,
        preset_token: str,
    ) -> bool:
        """Delete a PTZ preset by its token."""
        if not _HAS_ONVIF:
            return False

        def _delete():
            try:
                cam = ONVIFCamera(host, port, username, password)
                media = cam.create_media_service()
                ptz = cam.create_ptz_service()
                profile_token = media.GetProfiles()[0].token
                ptz.RemovePreset({
                    "ProfileToken": profile_token,
                    "PresetToken": preset_token,
                })
                return True
            except Exception as e:
                logger.error(f"Delete preset failed: {e}")
                return False

        return await asyncio.to_thread(_delete)

    async def check_ptz_capable(
        self, host: str, port: int, username: str, password: str,
    ) -> bool:
        """Check if camera supports PTZ."""
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

    # ------------------------------------------------------------------
    # Media2 / Profile T (H.265, newer cameras)
    # ------------------------------------------------------------------

    async def get_stream_uris_media2(
        self, host: str, port: int = 80,
        username: str = "admin", password: str = "admin",
    ) -> Optional[Dict[str, Optional[str]]]:
        """
        Try ONVIF Media2 (Profile T) for stream URIs.
        Returns None if Media2 is not supported.
        """
        if not _HAS_ONVIF:
            return None

        def _get():
            try:
                cam = ONVIFCamera(host, port, username, password)
                # Check if Media2 service is available
                caps = cam.devicemgmt.GetCapabilities()
                media2_addr = None
                try:
                    svcs = cam.devicemgmt.GetServices({"IncludeCapability": False})
                    for svc in svcs:
                        ns = str(getattr(svc, "Namespace", ""))
                        if "media/2" in ns or "media/wsdl/media2" in ns:
                            media2_addr = str(svc.XAddr)
                            break
                except Exception:
                    return None

                if not media2_addr:
                    return None

                media2 = cam.create_media2_service()
                profiles = media2.GetProfiles({"Type": ["All"]})
                if not profiles:
                    return None

                uris: Dict[str, Optional[str]] = {"main_stream_url": None, "sub_stream_url": None}
                for i, profile in enumerate(profiles[:2]):
                    try:
                        uri_resp = media2.GetStreamUri({
                            "StreamSetup": {"Stream": "RTP-Unicast", "Transport": {"Protocol": "RTSP"}},
                            "ProfileToken": profile.token,
                        })
                        url = str(uri_resp.Uri) if hasattr(uri_resp, "Uri") else str(uri_resp[0].Uri)
                        if username and "://" in url:
                            proto, rest = url.split("://", 1)
                            url = f"{proto}://{username}:{password}@{rest}"
                        if i == 0:
                            uris["main_stream_url"] = url
                        else:
                            uris["sub_stream_url"] = url
                    except Exception:
                        pass

                # Detect codec from first profile (H.265 indicator)
                try:
                    enc = profiles[0].VideoEncoderConfiguration
                    codec = str(enc.Encoding).upper() if enc else None
                    uris["codec"] = codec
                except Exception:
                    pass

                return uris
            except Exception as e:
                logger.debug(f"Media2 query failed for {host}: {e}")
                return None

        return await asyncio.to_thread(_get)

    async def get_stream_uris_with_media2_fallback(
        self, host: str, port: int = 80,
        username: str = "admin", password: str = "admin",
    ) -> Dict[str, Optional[str]]:
        """Try Media2 first, fall back to Media (Profile S)."""
        result = await self.get_stream_uris_media2(host, port, username, password)
        if result and result.get("main_stream_url"):
            result["media_version"] = 2
            return result
        result = await self.get_stream_uris(host, port, username, password)
        result["media_version"] = 1
        return result

    async def get_capabilities(
        self, host: str, port: int = 80,
        username: str = "admin", password: str = "admin",
    ) -> Dict[str, Any]:
        """Query full ONVIF capabilities (which services are supported)."""
        if not _HAS_ONVIF:
            return {}

        def _caps():
            try:
                cam = ONVIFCamera(host, port, username, password)
                caps = cam.devicemgmt.GetCapabilities()
                result: Dict[str, Any] = {}
                for svc_name in ("Analytics", "Device", "Events", "Imaging", "Media", "PTZ"):
                    svc_caps = getattr(caps, svc_name, None)
                    if svc_caps:
                        result[svc_name.lower()] = {
                            "xaddr": str(getattr(svc_caps, "XAddr", "")),
                        }
                # Check for Media2 via GetServices
                try:
                    svcs = cam.devicemgmt.GetServices({"IncludeCapability": False})
                    result["supported_services"] = [str(getattr(s, "Namespace", "")) for s in svcs]
                    result["media2_supported"] = any(
                        "media/2" in str(getattr(s, "Namespace", "")) for s in svcs
                    )
                except Exception:
                    pass
                return result
            except Exception as e:
                logger.error(f"GetCapabilities failed for {host}: {e}")
                return {}

        return await asyncio.to_thread(_caps)

    # ------------------------------------------------------------------
    # ONVIF System Service — reboot, time sync, factory reset
    # ------------------------------------------------------------------

    async def get_device_system_info(
        self, host: str, port: int = 80,
        username: str = "admin", password: str = "admin",
    ) -> Dict[str, Any]:
        """Extended device info including serial number and hardware ID."""
        if not _HAS_ONVIF:
            return {}

        def _info():
            try:
                cam = ONVIFCamera(host, port, username, password)
                info = cam.devicemgmt.GetDeviceInformation()
                return {
                    "manufacturer": str(info.Manufacturer),
                    "model": str(info.Model),
                    "firmware_version": str(info.FirmwareVersion),
                    "serial_number": str(info.SerialNumber),
                    "hardware_id": str(info.HardwareId),
                }
            except Exception as e:
                logger.error(f"GetDeviceInformation failed for {host}: {e}")
                return {}

        return await asyncio.to_thread(_info)

    async def get_camera_time(
        self, host: str, port: int = 80,
        username: str = "admin", password: str = "admin",
    ) -> Dict[str, Any]:
        """Get current date/time on the camera."""
        if not _HAS_ONVIF:
            return {}

        def _time():
            try:
                cam = ONVIFCamera(host, port, username, password)
                dt = cam.devicemgmt.GetSystemDateAndTime()
                utc = dt.UTCDateTime
                return {
                    "timezone": str(dt.TimeZone.TZ) if dt.TimeZone else None,
                    "ntp_enabled": dt.NTP,
                    "datetime_type": str(dt.DateTimeType),
                    "utc": {
                        "year": utc.Date.Year, "month": utc.Date.Month, "day": utc.Date.Day,
                        "hour": utc.Time.Hour, "minute": utc.Time.Minute, "second": utc.Time.Second,
                    } if utc else None,
                }
            except Exception as e:
                logger.error(f"GetSystemDateAndTime failed for {host}: {e}")
                return {}

        return await asyncio.to_thread(_time)

    async def sync_camera_time(
        self, host: str, port: int = 80,
        username: str = "admin", password: str = "admin",
    ) -> bool:
        """Sync camera time to NVR system time (UTC)."""
        if not _HAS_ONVIF:
            return False

        def _sync():
            try:
                cam = ONVIFCamera(host, port, username, password)
                now = datetime.utcnow()
                req = cam.devicemgmt.create_type("SetSystemDateAndTime")
                req.DateTimeType = "Manual"
                req.DaylightSavings = False
                req.UTCDateTime = {
                    "Date": {"Year": now.year, "Month": now.month, "Day": now.day},
                    "Time": {"Hour": now.hour, "Minute": now.minute, "Second": now.second},
                }
                cam.devicemgmt.SetSystemDateAndTime(req)
                return True
            except Exception as e:
                logger.error(f"SetSystemDateAndTime failed for {host}: {e}")
                return False

        return await asyncio.to_thread(_sync)

    async def reboot_camera(
        self, host: str, port: int = 80,
        username: str = "admin", password: str = "admin",
    ) -> str:
        """Reboot the camera via ONVIF SystemReboot."""
        if not _HAS_ONVIF:
            raise RuntimeError("python-onvif-zeep not installed")

        def _reboot():
            try:
                cam = ONVIFCamera(host, port, username, password)
                result = cam.devicemgmt.SystemReboot()
                return str(result) if result else "Reboot initiated"
            except Exception as e:
                raise RuntimeError(f"SystemReboot failed: {e}")

        return await asyncio.to_thread(_reboot)

    async def factory_default(
        self, host: str, port: int = 80,
        username: str = "admin", password: str = "admin",
        hard: bool = False,
    ) -> bool:
        """Reset camera to factory defaults (soft = keep IP/accounts, hard = full reset)."""
        if not _HAS_ONVIF:
            return False

        def _reset():
            try:
                cam = ONVIFCamera(host, port, username, password)
                factory_default_type = "Hard" if hard else "Soft"
                cam.devicemgmt.SetSystemFactoryDefault({"FactoryDefault": factory_default_type})
                return True
            except Exception as e:
                logger.error(f"SetSystemFactoryDefault failed for {host}: {e}")
                return False

        return await asyncio.to_thread(_reset)

    # ------------------------------------------------------------------
    # ONVIF Imaging Service — exposure, WDR, day/night, focus
    # ------------------------------------------------------------------

    async def get_imaging_settings(
        self, host: str, port: int = 80,
        username: str = "admin", password: str = "admin",
    ) -> Dict[str, Any]:
        """Get all imaging settings for the first video source."""
        if not _HAS_ONVIF:
            return {}

        def _get():
            try:
                cam = ONVIFCamera(host, port, username, password)
                media = cam.create_media_service()
                video_sources = media.GetVideoSources()
                if not video_sources:
                    return {}
                vs_token = video_sources[0].token

                imaging = cam.create_imaging_service()
                settings = imaging.GetImagingSettings({"VideoSourceToken": vs_token})

                result: Dict[str, Any] = {"video_source_token": vs_token}
                if hasattr(settings, "Brightness"):
                    result["brightness"] = settings.Brightness
                if hasattr(settings, "ColorSaturation"):
                    result["color_saturation"] = settings.ColorSaturation
                if hasattr(settings, "Contrast"):
                    result["contrast"] = settings.Contrast
                if hasattr(settings, "Sharpness"):
                    result["sharpness"] = settings.Sharpness
                if hasattr(settings, "IrCutFilter"):
                    result["ir_cut_filter"] = str(settings.IrCutFilter)  # ON/OFF/AUTO
                if hasattr(settings, "WideDynamicRange") and settings.WideDynamicRange:
                    result["wide_dynamic_range"] = {
                        "mode": str(settings.WideDynamicRange.Mode),
                        "level": getattr(settings.WideDynamicRange, "Level", None),
                    }
                if hasattr(settings, "BacklightCompensation") and settings.BacklightCompensation:
                    result["backlight_compensation"] = {
                        "mode": str(settings.BacklightCompensation.Mode),
                        "level": getattr(settings.BacklightCompensation, "Level", None),
                    }
                if hasattr(settings, "Exposure") and settings.Exposure:
                    exp = settings.Exposure
                    result["exposure"] = {
                        "mode": str(getattr(exp, "Mode", "")),
                        "min_exposure_time": getattr(exp, "MinExposureTime", None),
                        "max_exposure_time": getattr(exp, "MaxExposureTime", None),
                        "min_gain": getattr(exp, "MinGain", None),
                        "max_gain": getattr(exp, "MaxGain", None),
                        "iris": getattr(exp, "Iris", None),
                        "gain": getattr(exp, "Gain", None),
                    }
                if hasattr(settings, "Focus") and settings.Focus:
                    result["focus"] = {
                        "mode": str(getattr(settings.Focus, "AutoFocusMode", "")),
                        "default_speed": getattr(settings.Focus, "DefaultSpeed", None),
                    }
                return result
            except Exception as e:
                logger.error(f"GetImagingSettings failed for {host}: {e}")
                return {}

        return await asyncio.to_thread(_get)

    async def get_imaging_options(
        self, host: str, port: int = 80,
        username: str = "admin", password: str = "admin",
    ) -> Dict[str, Any]:
        """Get valid ranges for all imaging parameters."""
        if not _HAS_ONVIF:
            return {}

        def _opts():
            try:
                cam = ONVIFCamera(host, port, username, password)
                media = cam.create_media_service()
                vs_token = media.GetVideoSources()[0].token
                imaging = cam.create_imaging_service()
                opts = imaging.GetOptions({"VideoSourceToken": vs_token})
                result: Dict[str, Any] = {}
                for field in ("Brightness", "ColorSaturation", "Contrast", "Sharpness"):
                    fld_opts = getattr(opts, field, None)
                    if fld_opts:
                        result[field.lower()] = {
                            "min": getattr(fld_opts, "Min", None),
                            "max": getattr(fld_opts, "Max", None),
                        }
                if getattr(opts, "IrCutFilterModes", None):
                    result["ir_cut_filter_modes"] = [str(m) for m in opts.IrCutFilterModes]
                return result
            except Exception as e:
                logger.error(f"GetImagingOptions failed for {host}: {e}")
                return {}

        return await asyncio.to_thread(_opts)

    async def set_imaging_settings(
        self, host: str, port: int = 80,
        username: str = "admin", password: str = "admin",
        settings_patch: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Apply a partial imaging settings patch."""
        if not _HAS_ONVIF or not settings_patch:
            return False

        def _set():
            try:
                cam = ONVIFCamera(host, port, username, password)
                media = cam.create_media_service()
                vs_token = media.GetVideoSources()[0].token
                imaging = cam.create_imaging_service()

                current = imaging.GetImagingSettings({"VideoSourceToken": vs_token})
                # Apply patch
                if "brightness" in settings_patch and hasattr(current, "Brightness"):
                    current.Brightness = float(settings_patch["brightness"])
                if "contrast" in settings_patch and hasattr(current, "Contrast"):
                    current.Contrast = float(settings_patch["contrast"])
                if "color_saturation" in settings_patch and hasattr(current, "ColorSaturation"):
                    current.ColorSaturation = float(settings_patch["color_saturation"])
                if "sharpness" in settings_patch and hasattr(current, "Sharpness"):
                    current.Sharpness = float(settings_patch["sharpness"])
                if "ir_cut_filter" in settings_patch and hasattr(current, "IrCutFilter"):
                    current.IrCutFilter = settings_patch["ir_cut_filter"]
                if "wide_dynamic_range" in settings_patch and hasattr(current, "WideDynamicRange"):
                    wdr = settings_patch["wide_dynamic_range"]
                    if current.WideDynamicRange:
                        current.WideDynamicRange.Mode = wdr.get("mode", "OFF")
                        if "level" in wdr:
                            current.WideDynamicRange.Level = float(wdr["level"])

                imaging.SetImagingSettings({
                    "VideoSourceToken": vs_token,
                    "ImagingSettings": current,
                    "ForcePersistence": True,
                })
                return True
            except Exception as e:
                logger.error(f"SetImagingSettings failed for {host}: {e}")
                return False

        return await asyncio.to_thread(_set)

    async def move_focus(
        self, host: str, port: int = 80,
        username: str = "admin", password: str = "admin",
        mode: str = "Auto",
    ) -> bool:
        """Trigger autofocus or set focus mode (Auto/Manual)."""
        if not _HAS_ONVIF:
            return False

        def _focus():
            try:
                cam = ONVIFCamera(host, port, username, password)
                media = cam.create_media_service()
                vs_token = media.GetVideoSources()[0].token
                imaging = cam.create_imaging_service()
                imaging.Move({
                    "VideoSourceToken": vs_token,
                    "Focus": {"Continuous": {"Speed": 1.0}} if mode == "Auto" else {"Stop": {}},
                })
                return True
            except Exception as e:
                logger.warning(f"Move focus failed for {host}: {e}")
                return False

        return await asyncio.to_thread(_focus)

    # ------------------------------------------------------------------
    # ONVIF Digital I/O Service
    # ------------------------------------------------------------------

    async def get_relay_outputs(
        self, host: str, port: int = 80,
        username: str = "admin", password: str = "admin",
    ) -> List[Dict[str, Any]]:
        """Get all relay output definitions from camera."""
        if not _HAS_ONVIF:
            return []

        def _get():
            try:
                cam = ONVIFCamera(host, port, username, password)
                outputs = cam.devicemgmt.GetRelayOutputs()
                result = []
                for out in outputs or []:
                    result.append({
                        "token": str(out.token),
                        "mode": str(getattr(out.Properties, "Mode", "")),
                        "delay_time": str(getattr(out.Properties, "DelayTime", "")),
                        "idle_state": str(getattr(out.Properties, "IdleState", "")),
                    })
                return result
            except Exception as e:
                logger.warning(f"GetRelayOutputs failed for {host}: {e}")
                return []

        return await asyncio.to_thread(_get)

    async def set_relay_output_state(
        self, host: str, port: int = 80,
        username: str = "admin", password: str = "admin",
        relay_token: str = "RelayOut1",
        logical_state: str = "active",   # active | inactive
    ) -> bool:
        """Trigger (or release) a relay output."""
        if not _HAS_ONVIF:
            return False

        def _set():
            try:
                cam = ONVIFCamera(host, port, username, password)
                cam.devicemgmt.SetRelayOutputState({
                    "RelayOutputToken": relay_token,
                    "LogicalState": logical_state,
                })
                return True
            except Exception as e:
                logger.error(f"SetRelayOutputState failed for {host}: {e}")
                return False

        return await asyncio.to_thread(_set)

    async def get_digital_inputs(
        self, host: str, port: int = 80,
        username: str = "admin", password: str = "admin",
    ) -> List[Dict[str, Any]]:
        """Get digital input definitions from camera."""
        if not _HAS_ONVIF:
            return []

        def _get():
            try:
                cam = ONVIFCamera(host, port, username, password)
                inputs = cam.devicemgmt.GetDigitalInputs()
                result = []
                for inp in inputs or []:
                    result.append({
                        "token": str(inp.token),
                        "idle_state": str(getattr(inp, "IdleState", "")),
                    })
                return result
            except Exception as e:
                logger.warning(f"GetDigitalInputs failed for {host}: {e}")
                return []

        return await asyncio.to_thread(_get)

    async def get_audio_output_uri(
        self, host: str, port: int = 80,
        username: str = "admin", password: str = "admin",
    ) -> Optional[str]:
        """Get the RTSP backchannel URI for two-way audio from ONVIF Media service."""
        if not _HAS_ONVIF:
            return None

        def _get():
            try:
                cam = ONVIFCamera(host, port, username, password)
                media = cam.create_media_service()
                profiles = media.GetProfiles()
                if not profiles:
                    return None
                # Use the first profile that has an audio backchannel
                for profile in profiles:
                    try:
                        stream_uri = media.GetStreamUri({
                            "StreamSetup": {
                                "Stream": "RTP-Unicast",
                                "Transport": {"Protocol": "RTSP"},
                            },
                            "ProfileToken": profile.token,
                        })
                        uri = stream_uri.Uri
                        # Some cameras expose backchannel on a different path
                        # Heuristic: replace stream with backchannel if available
                        if uri:
                            return uri.replace("/stream", "/backchannel").replace("/live", "/backchannel")
                    except Exception:
                        continue
                return None
            except Exception as e:
                logger.warning(f"GetAudioOutputUri failed for {host}: {e}")
                return None

        return await asyncio.to_thread(_get)


# Module singleton
onvif_service = ONVIFService()
