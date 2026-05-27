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
import ipaddress
import logging
import socket
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


# ── Subnet scan fallback (multicast-free ONVIF discovery) ────────────────
# Common ONVIF service ports across vendors. Order matters — try 80
# first since 99% of cameras serve there.
ONVIF_PROBE_PORTS = (80, 8080, 8000, 8899, 2020, 8081, 8443, 443)


def _autodetect_subnet() -> Optional[str]:
    """Return the CIDR string to probe for ONVIF cameras.

    Priority:
      1. `LAN_SUBNET` env var (operator sets in .env, e.g. "192.168.1.0/24")
      2. Default-route interface IP /24, IF the detected subnet looks like
         a typical home/office LAN (192.168.0.0/16 or 10.0.0.0/8) and NOT
         a Docker bridge range (172.16-172.31).
      3. None — caller falls back to multicast WS-Discovery only.
    """
    import os

    env_subnet = os.environ.get("LAN_SUBNET", "").strip()
    if env_subnet:
        try:
            ipaddress.ip_network(env_subnet, strict=False)
            return env_subnet
        except ValueError:
            logger.warning("LAN_SUBNET env var invalid: %s", env_subnet)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            host_ip = s.getsockname()[0]
        net = ipaddress.ip_network(f"{host_ip}/24", strict=False)
        ip_addr = ipaddress.ip_address(host_ip)

        # Refuse Docker bridge networks — won't find LAN cameras
        docker_ranges = [
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("10.0.0.0/8"),  # often Docker overlay
        ]
        # 192.168 / 10.x outside Docker = real LAN. 172.16-31 = Docker bridge.
        is_docker_bridge = ipaddress.ip_network("172.16.0.0/12").supernet_of(net)
        if is_docker_bridge:
            logger.info(
                "Auto-detected subnet %s is Docker bridge; refusing. "
                "Set LAN_SUBNET env var (e.g. 192.168.1.0/24) or pass "
                "?subnet= explicitly.",
                net,
            )
            return None

        return str(net)
    except Exception as e:  # noqa: BLE001
        logger.warning("Subnet autodetect failed: %s", e)
        return None


async def _probe_host(ip: str, timeout: float) -> Optional[Dict[str, Any]]:
    """TCP-probe ONVIF_PROBE_PORTS; on first hit return a candidate."""
    for port in ONVIF_PROBE_PORTS:
        try:
            fut = asyncio.open_connection(ip, port)
            reader, writer = await asyncio.wait_for(fut, timeout=timeout)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return {
                "ip": ip,
                "port": port,
                "xaddr": f"http://{ip}:{port}/onvif/device_service",
                "name": None,
                "manufacturer": None,
                "model": None,
            }
        except (asyncio.TimeoutError, OSError):
            continue
    return None


async def _rtsp_grab_jpeg(rtsp_url: str, timeout: float = 5.0) -> Optional[bytes]:
    """Pull a single JPEG frame from an RTSP stream via ffmpeg.

    Fallback for cameras that don't expose ONVIF GetSnapshotUri (or that
    return broken / vendor-specific URIs). Adds ~1-3s overhead per host.
    """
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-rtsp_transport", "tcp",
        "-stimeout", str(int(timeout * 1_000_000)),
        "-y",
        "-i", rtsp_url,
        "-frames:v", "1",
        "-f", "image2pipe",
        "-vcodec", "mjpeg",
        "-q:v", "5",
        "pipe:1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 2)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return None
    if proc.returncode != 0 or not stdout:
        return None
    if not stdout.startswith(b"\xff\xd8"):
        return None
    return stdout


async def _is_onvif_endpoint(ip: str, port: int, timeout: float = 2.0) -> bool:
    """Verify a host actually speaks ONVIF SOAP.

    Sends an unauthenticated GetSystemDateAndTime request. ONVIF cameras
    answer with a SOAP envelope (200 or 400 with SOAP fault); routers /
    switches / printers return HTML, JSON, or refuse. Used to drop
    non-camera hits from the discovery list.
    """
    import httpx

    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
        '<s:Body><GetSystemDateAndTime '
        'xmlns="http://www.onvif.org/ver10/device/wsdl"/>'
        '</s:Body></s:Envelope>'
    )
    headers = {
        "Content-Type": "application/soap+xml; charset=utf-8",
        "SOAPAction": '"http://www.onvif.org/ver10/device/wsdl/GetSystemDateAndTime"',
    }
    urls = [
        f"http://{ip}:{port}/onvif/device_service",
        f"http://{ip}:{port}/onvif/services",
    ]
    for url in urls:
        try:
            async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
                r = await client.post(url, content=body, headers=headers)
            text = r.text.lower()
            if "envelope" in text and "onvif" in text:
                return True
            if "envelope" in text and "getsystemdateandtimeresponse" in text:
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


async def _tcp_subnet_scan(subnet: str, timeout: float = 0.8) -> List[Dict[str, Any]]:
    """Parallel TCP probe across every host in `subnet`.

    Concurrency 256 so /24 finishes in 5-8s. Short timeout 0.8s — most
    devices respond in <100ms; anything slower is router/printer/IoT
    noise we'd discard anyway.
    """
    try:
        net = ipaddress.ip_network(subnet, strict=False)
    except ValueError as e:
        logger.warning("Invalid subnet %s: %s", subnet, e)
        return []

    if net.num_addresses > 1024:
        logger.warning(
            "Subnet %s too large (%d hosts); aborting scan",
            subnet, net.num_addresses,
        )
        return []

    sem = asyncio.Semaphore(256)

    async def _bounded(ip: str):
        async with sem:
            return await _probe_host(ip, timeout)

    tasks = [_bounded(str(ip)) for ip in net.hosts()]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if isinstance(r, dict)]

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

    async def discover(
        self,
        timeout: int = 5,
        subnet: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Discover ONVIF cameras on the LAN.

        Tries WS-Discovery (multicast 239.255.255.250:3702) first. When
        running inside a Docker bridge network, multicast typically can't
        reach the host LAN, so we fall back to a unicast subnet scan
        that probes common ONVIF ports (80, 8080, 2020, 8000, 8899) on
        every host in the subnet.

        `subnet` overrides auto-detection. Example: "192.168.1.0/24".
        """
        devices: List[Dict[str, Any]] = []

        # ── Try WS-Discovery first (works when host network is reachable)
        if _HAS_WSDISCOVERY:
            try:
                devices = await asyncio.to_thread(self._wsd_scan, timeout)
            except Exception as e:  # noqa: BLE001
                logger.warning("WS-Discovery scan failed: %s", e)
                devices = []

        # ── Fallback: TCP probe across subnet ───────────────────────────
        if not devices:
            target_subnet = subnet or _autodetect_subnet()
            if target_subnet:
                logger.info("WS-Discovery returned 0 results; trying TCP subnet scan on %s", target_subnet)
                devices = await _tcp_subnet_scan(target_subnet, timeout=2.0)
            else:
                logger.warning("Could not auto-detect subnet for fallback scan")

        # ── Enrich with device info (manufacturer / model / firmware) ──
        # Pass operator creds if supplied; many cameras 401 on default
        # admin/admin and the row stays unlabeled otherwise.
        u = username or "admin"
        p = password or "admin"
        enriched = []
        for dev in devices:
            info = await self.get_device_info(dev["ip"], dev["port"], u, p)
            if info:
                dev.update(info)
                enriched.append(dev)
                continue

            # No info from default creds. Probe ONVIF endpoint anonymously
            # to confirm it speaks ONVIF at all — eliminates routers /
            # switches / NAS boxes that just happen to have port 80 open.
            if await _is_onvif_endpoint(dev["ip"], dev["port"]):
                # Mark auth-required so the UI shows it as "unverified"
                # and the operator can supply real credentials.
                dev["auth_required"] = True
                enriched.append(dev)
            # else: silently drop — not an ONVIF device.

        return enriched

    def _wsd_scan(self, timeout: int) -> List[Dict[str, Any]]:
        """Synchronous WS-Discovery scan — runs in thread."""
        results: List[Dict[str, Any]] = []
        wsd = WSDiscovery()
        wsd.start()
        try:
            services = wsd.searchServices(timeout=timeout)
            for svc in services:
                types = svc.getTypes()
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
        finally:
            wsd.stop()
        return results

    # ------------------------------------------------------------------
    # Device info & stream URIs
    # ------------------------------------------------------------------

    async def get_device_info(
        self, host: str, port: int = 80,
        username: str = "admin", password: str = "admin",
    ) -> Optional[Dict[str, Any]]:
        """Query device info (manufacturer, model, firmware, serial,
        hardware id, capabilities, network interfaces)."""
        if not _HAS_ONVIF:
            return None

        def _query():
            try:
                cam = ONVIFCamera(host, port, username, password)
                info = cam.devicemgmt.GetDeviceInformation()
                out = {
                    "manufacturer": getattr(info, "Manufacturer", None),
                    "model": getattr(info, "Model", None),
                    "name": getattr(info, "Model", None),
                    "firmware": getattr(info, "FirmwareVersion", None),
                    "serial_number": getattr(info, "SerialNumber", None),
                    "hardware_id": getattr(info, "HardwareId", None),
                }
                # Best-effort: capabilities + network interfaces.
                try:
                    caps = cam.devicemgmt.GetCapabilities({"Category": "All"})
                    out["has_ptz"] = bool(getattr(caps, "PTZ", None))
                    out["has_imaging"] = bool(getattr(caps, "Imaging", None))
                    out["has_analytics"] = bool(getattr(caps, "Analytics", None))
                    out["has_events"] = bool(getattr(caps, "Events", None))
                except Exception:  # noqa: BLE001
                    pass
                try:
                    ifaces = cam.devicemgmt.GetNetworkInterfaces()
                    mac = None
                    for iface in ifaces or []:
                        info_obj = getattr(iface, "Info", None)
                        if info_obj and getattr(info_obj, "HwAddress", None):
                            mac = info_obj.HwAddress
                            break
                    if mac:
                        out["mac"] = mac
                except Exception:  # noqa: BLE001
                    pass
                return out
            except Exception as e:
                logger.warning(f"ONVIF info query failed for {host}: {e}")
                return None

        return await asyncio.to_thread(_query)

    async def get_snapshot_uri(
        self, host: str, port: int = 80,
        username: str = "admin", password: str = "admin",
        profile_token: Optional[str] = None,
    ) -> Optional[str]:
        """Return the camera's ONVIF GetSnapshotUri for its first profile."""
        if not _HAS_ONVIF:
            return None

        def _query():
            try:
                cam = ONVIFCamera(host, port, username, password)
                media = cam.create_media_service()
                _profile_token = profile_token
                if not _profile_token:
                    profiles = media.GetProfiles()
                    if not profiles:
                        return None
                    _profile_token = profiles[0].token
                resp = media.GetSnapshotUri({"ProfileToken": _profile_token})
                return getattr(resp, "Uri", None)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"ONVIF snapshot URI query failed for {host}: {e}")
                return None

        return await asyncio.to_thread(_query)

    async def fetch_snapshot(
        self, host: str, port: int = 80,
        username: str = "admin", password: str = "admin",
        timeout: float = 4.0,
    ) -> Optional[bytes]:
        """Fetch a JPEG of the latest frame from the camera.

        Order:
          1. ONVIF GetSnapshotUri + (anon | basic | digest) HTTP fetch
          2. ONVIF GetStreamUri RTSP + ffmpeg single-frame grab

        Returns None only if both paths fail.
        """
        import httpx

        # ── Path 1: ONVIF snapshot URI ─────────────────────────────────
        uri = await self.get_snapshot_uri(host, port, username, password)
        if uri:
            try:
                async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
                    for auth in (
                        None,
                        (username, password),
                        httpx.DigestAuth(username, password),
                    ):
                        try:
                            r = await client.get(uri, auth=auth)
                        except Exception:  # noqa: BLE001
                            continue
                        if (
                            r.status_code == 200
                            and r.content
                            and r.content.startswith(b"\xff\xd8")
                        ):
                            return r.content
            except Exception as e:  # noqa: BLE001
                logger.debug("HTTP snapshot fetch failed for %s: %s", host, e)

        # ── Path 2: RTSP single-frame via ffmpeg ───────────────────────
        try:
            uris = await self.get_stream_uris(host, port, username, password)
            rtsp = uris.get("main_stream_url")
            if rtsp:
                jpeg = await _rtsp_grab_jpeg(rtsp, timeout=timeout)
                if jpeg:
                    return jpeg
        except Exception as e:  # noqa: BLE001
            logger.debug("RTSP snapshot fallback failed for %s: %s", host, e)

        return None

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
        profile_token: Optional[str] = None,
    ) -> bool:
        """Start continuous PTZ movement. Call stop() to halt."""
        if not _HAS_ONVIF:
            raise RuntimeError("python-onvif-zeep not installed")

        def _move():
            try:
                cam = ONVIFCamera(host, port, username, password)
                media = cam.create_media_service()
                ptz = cam.create_ptz_service()
                _profile_token = profile_token or media.GetProfiles()[0].token

                request = ptz.create_type("ContinuousMove")
                request.ProfileToken = _profile_token
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
        profile_token: Optional[str] = None,
    ) -> bool:
        """Stop all PTZ movement."""
        if not _HAS_ONVIF:
            return False

        def _stop():
            try:
                cam = ONVIFCamera(host, port, username, password)
                media = cam.create_media_service()
                ptz = cam.create_ptz_service()
                _profile_token = profile_token or media.GetProfiles()[0].token
                ptz.Stop({"ProfileToken": _profile_token, "PanTilt": True, "Zoom": True})
                return True
            except Exception as e:
                logger.error(f"PTZ stop failed: {e}")
                return False

        return await asyncio.to_thread(_stop)

    async def get_presets(
        self, host: str, port: int, username: str, password: str,
        profile_token: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        if not _HAS_ONVIF:
            return []

        def _presets():
            try:
                cam = ONVIFCamera(host, port, username, password)
                media = cam.create_media_service()
                ptz = cam.create_ptz_service()
                _profile_token = profile_token or media.GetProfiles()[0].token
                presets = ptz.GetPresets({"ProfileToken": _profile_token})
                return [{"token": str(p.token), "name": str(p.Name)} for p in presets]
            except Exception as e:
                logger.error(f"Get presets failed: {e}")
                return []

        return await asyncio.to_thread(_presets)

    async def goto_preset(
        self, host: str, port: int, username: str, password: str,
        preset_token: str,
        profile_token: Optional[str] = None,
    ) -> bool:
        if not _HAS_ONVIF:
            return False

        def _goto():
            try:
                cam = ONVIFCamera(host, port, username, password)
                media = cam.create_media_service()
                ptz = cam.create_ptz_service()
                _profile_token = profile_token or media.GetProfiles()[0].token
                ptz.GotoPreset({
                    "ProfileToken": _profile_token,
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
        profile_token: Optional[str] = None,
    ) -> Optional[str]:
        """Save current position as a named preset. Returns preset token."""
        if not _HAS_ONVIF:
            return None

        def _set():
            try:
                cam = ONVIFCamera(host, port, username, password)
                media = cam.create_media_service()
                ptz = cam.create_ptz_service()
                _profile_token = profile_token or media.GetProfiles()[0].token
                result = ptz.SetPreset({
                    "ProfileToken": _profile_token,
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
        profile_token: Optional[str] = None,
    ) -> bool:
        """Delete a PTZ preset by its token."""
        if not _HAS_ONVIF:
            return False

        def _delete():
            try:
                cam = ONVIFCamera(host, port, username, password)
                media = cam.create_media_service()
                ptz = cam.create_ptz_service()
                _profile_token = profile_token or media.GetProfiles()[0].token
                ptz.RemovePreset({
                    "ProfileToken": _profile_token,
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

    # ------------------------------------------------------------------
    # NVR Channel Enumeration
    # ------------------------------------------------------------------

    async def enumerate_channels(
        self,
        host: str,
        port: int = 80,
        username: str = "admin",
        password: str = "admin",
    ) -> List[Dict[str, Any]]:
        """Enumerate all ONVIF media profiles on a device grouped by physical
        channel (VideoSource).

        Returns one entry per channel with main + sub stream information.
        On total failure returns [] and logs a warning — never raises.
        """
        if not _HAS_ONVIF:
            logger.warning("enumerate_channels: python-onvif-zeep not installed")
            return []

        def _enumerate() -> List[Dict[str, Any]]:
            import re

            try:
                cam = ONVIFCamera(host, port, username, password)
                media = cam.create_media_service()
                profiles = media.GetProfiles()
            except Exception as exc:
                logger.warning("enumerate_channels: GetProfiles failed for %s: %s", host, exc)
                return []

            if not profiles:
                return []

            # ── Group profiles by VideoSource token ────────────────────
            # Key = source token (string) when present; fall back to the
            # leading integer in the profile Name ("Channel1_Main" → "1");
            # last resort: use the profile's own token as the group key.
            def _source_key(profile) -> str:
                try:
                    vsc = getattr(profile, "VideoSourceConfiguration", None)
                    if vsc:
                        src = getattr(vsc, "SourceToken", None)
                        if src:
                            return str(src)
                except Exception:
                    pass
                # Heuristic: extract leading number from profile name
                name = str(getattr(profile, "Name", "") or "")
                m = re.search(r"\d+", name)
                if m:
                    return m.group(0)
                return str(getattr(profile, "token", profile))

            # Ordered dict so insertion order = channel order
            groups: Dict[str, list] = {}
            for p in profiles:
                key = _source_key(p)
                groups.setdefault(key, []).append(p)

            # ── Helper: build stream URL for a profile ─────────────────
            def _stream_url(profile) -> Optional[str]:
                try:
                    resp = media.GetStreamUri({
                        "StreamSetup": {
                            "Stream": "RTP-Unicast",
                            "Transport": {"Protocol": "RTSP"},
                        },
                        "ProfileToken": profile.token,
                    })
                    url = str(getattr(resp, "Uri", "") or "")
                    if url and "://" in url and "@" not in url.split("://", 1)[1].split("/")[0]:
                        proto, rest = url.split("://", 1)
                        url = f"{proto}://{username}:{password}@{rest}"
                    return url or None
                except Exception as exc:
                    logger.debug(
                        "enumerate_channels: GetStreamUri failed for profile %s: %s",
                        getattr(profile, "token", "?"), exc,
                    )
                    return None

            def _snapshot_url(profile) -> Optional[str]:
                try:
                    resp = media.GetSnapshotUri({"ProfileToken": profile.token})
                    return str(getattr(resp, "Uri", "") or "") or None
                except Exception:
                    return None

            def _resolution(profile) -> str:
                try:
                    enc = profile.VideoEncoderConfiguration
                    res = enc.Resolution
                    return f"{res.Width}x{res.Height}"
                except Exception:
                    return "unknown"

            def _width(profile) -> int:
                try:
                    return int(profile.VideoEncoderConfiguration.Resolution.Width)
                except Exception:
                    return 0

            def _fps(profile) -> Optional[int]:
                try:
                    return int(profile.VideoEncoderConfiguration.RateControl.FrameRateLimit)
                except Exception:
                    return None

            def _codec(profile) -> Optional[str]:
                try:
                    enc_str = str(profile.VideoEncoderConfiguration.Encoding).upper()
                    return enc_str or None
                except Exception:
                    return None

            results = []
            for ch_idx, (source_key, ch_profiles) in enumerate(groups.items(), start=1):
                # Sort descending by width → first = main, second = sub
                sorted_profiles = sorted(ch_profiles, key=_width, reverse=True)
                main_profile = sorted_profiles[0]
                sub_profile = sorted_profiles[1] if len(sorted_profiles) > 1 else None

                # Prefer a name that includes channel info from the main profile
                name_raw = str(getattr(main_profile, "Name", "") or "")
                channel_name = name_raw if name_raw else f"Channel {ch_idx}"

                main_url = _stream_url(main_profile)
                main_entry = {
                    "profile_token": str(main_profile.token),
                    "resolution": _resolution(main_profile),
                    "fps": _fps(main_profile),
                    "codec": _codec(main_profile),
                    "stream_url": main_url,
                }

                sub_entry = None
                if sub_profile:
                    sub_url = _stream_url(sub_profile)
                    sub_entry = {
                        "profile_token": str(sub_profile.token),
                        "resolution": _resolution(sub_profile),
                        "fps": _fps(sub_profile),
                        "codec": _codec(sub_profile),
                        "stream_url": sub_url,
                    }

                snapshot = _snapshot_url(main_profile)

                results.append({
                    "channel": ch_idx,
                    "source_token": source_key,
                    "name": channel_name,
                    "main": main_entry,
                    "sub": sub_entry,
                    "snapshot_url": snapshot,
                })

            return results

        try:
            return await asyncio.to_thread(_enumerate)
        except Exception as exc:
            logger.warning("enumerate_channels: unexpected error for %s: %s", host, exc)
            return []

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
