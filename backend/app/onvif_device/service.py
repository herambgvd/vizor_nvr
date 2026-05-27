# =============================================================================
# ONVIF Device Server — exposes the NVR as an ONVIF-compliant device
# =============================================================================
# Implements:
#   Device, Media (Profile S), Media2 (Profile T), PTZ (virtual forward),
#   Recording, Search, Replay (Profile G), Events
# Profiles: S (streaming) + T (modern) + G (recording)
#
# Uses lxml for XML building and raw FastAPI routes for SOAP transport.
# No full WSDL validation — responses are built to match ONVIF schema
# expectations used by mainstream VMS clients.
# =============================================================================

import logging
import base64
import hashlib
import uuid
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

from lxml import etree
from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session_maker
from app.cameras.models import Camera
from app.recordings.models import Recording

logger = logging.getLogger(__name__)

# ── Namespace constants ─────────────────────────────────────────────────────
NS_SOAP  = "http://www.w3.org/2003/05/soap-envelope"
NS_WSSE  = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
NS_WSU   = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
NS_WSA   = "http://www.w3.org/2005/08/addressing"
NS_TDS   = "http://www.onvif.org/ver10/device/wsdl"
NS_TRT   = "http://www.onvif.org/ver10/media/wsdl"
NS_TR2   = "http://www.onvif.org/ver20/media/wsdl"
NS_TRC   = "http://www.onvif.org/ver10/recording/wsdl"
NS_TSE   = "http://www.onvif.org/ver10/search/wsdl"
NS_TRP   = "http://www.onvif.org/ver10/replay/wsdl"
NS_TEV   = "http://www.onvif.org/ver10/events/wsdl"
NS_TPTZ  = "http://www.onvif.org/ver20/ptz/wsdl"
NS_TT    = "http://www.onvif.org/ver10/schema"
NS_WSNT  = "http://docs.oasis-open.org/wsn/b-2"
NS_WSRF  = "http://docs.oasis-open.org/wsrf/bf-2"

SOAP_ENV = "{%s}" % NS_SOAP
WSA_ENV  = "{%s}" % NS_WSA
TDS_ENV  = "{%s}" % NS_TDS
TRT_ENV  = "{%s}" % NS_TRT
TR2_ENV  = "{%s}" % NS_TR2
TRC_ENV  = "{%s}" % NS_TRC
TSE_ENV  = "{%s}" % NS_TSE
TRP_ENV  = "{%s}" % NS_TRP
TEV_ENV  = "{%s}" % NS_TEV
TPTZ_ENV = "{%s}" % NS_TPTZ
TT_ENV   = "{%s}" % NS_TT
WSNT_ENV = "{%s}" % NS_WSNT
WSRF_ENV = "{%s}" % NS_WSRF

# ── ONVIF Device credentials ────────────────────────────────────────────────
ONVIF_DEVICE_USER = os.getenv("ONVIF_DEVICE_USERNAME", "admin")
ONVIF_DEVICE_PASS = os.getenv("ONVIF_DEVICE_PASSWORD", "admin")

# ── XML helpers ─────────────────────────────────────────────────────────────

def _qn(ns: str, tag: str) -> str:
    return "{%s}%s" % (ns, tag)


def _soap_envelope() -> etree.Element:
    env = etree.Element(_qn(NS_SOAP, "Envelope"), nsmap={
        "soap": NS_SOAP,
        "tt":   NS_TT,
        "tds":  NS_TDS,
        "trt":  NS_TRT,
        "tr2":  NS_TR2,
        "trc":  NS_TRC,
        "tse":  NS_TSE,
        "trp":  NS_TRP,
        "tev":  NS_TEV,
        "tptz": NS_TPTZ,
        "wsa":  NS_WSA,
        "wsnt": NS_WSNT,
        "wsrf": NS_WSRF,
    })
    etree.SubElement(env, _qn(NS_SOAP, "Body"))
    return env


def _body(envelope: etree.Element) -> etree.Element:
    return envelope.find(_qn(NS_SOAP, "Body"))


def _add_text(parent: etree.Element, ns: str, tag: str, text: Any) -> etree.Element:
    el = etree.SubElement(parent, _qn(ns, tag))
    el.text = str(text) if text is not None else ""
    return el


# ── Request helpers ─────────────────────────────────────────────────────────

def _get_external_host(request: Request) -> str:
    """Determine the external host:port for XAddr URLs."""
    forwarded_host = request.headers.get("x-forwarded-host")
    if forwarded_host:
        return forwarded_host
    host = request.headers.get("host", "localhost")
    return host


def _base_xaddr(request: Request) -> str:
    scheme = request.headers.get("x-forwarded-proto", "http")
    host = _get_external_host(request)
    return f"{scheme}://{host}"


# ── WS-UsernameToken auth (basic) ───────────────────────────────────────────

def _verify_username_token(xml_bytes: bytes) -> bool:
    """Verify WS-UsernameToken PasswordDigest if present. Skip if absent."""
    if not xml_bytes:
        return True
    try:
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError:
        return True
    # Find Security header
    sec = root.find(".//{%s}Security" % NS_WSSE)
    if sec is None:
        return True  # no auth required when absent
    ut = sec.find(".//{%s}UsernameToken" % NS_WSSE)
    if ut is None:
        return True
    username_el = ut.find("{%s}Username" % NS_WSSE)
    password_el = ut.find("{%s}Password" % NS_WSSE)
    nonce_el    = ut.find("{%s}Nonce" % NS_WSSE)
    created_el  = ut.find("{%s}Created" % NS_WSU)

    if username_el is None or password_el is None:
        return False

    username       = username_el.text or ""
    password_type  = password_el.get("Type", "")
    password_value = password_el.text or ""

    if username != ONVIF_DEVICE_USER:
        return False

    if "PasswordDigest" in password_type:
        if nonce_el is None or created_el is None:
            return False
        nonce   = base64.b64decode(nonce_el.text or "")
        created = (created_el.text or "").encode("utf-8")
        secret  = ONVIF_DEVICE_PASS.encode("utf-8")
        digest  = base64.b64encode(
            hashlib.sha1(nonce + created + secret).digest()
        ).decode("utf-8")
        return digest == password_value
    else:
        # Plain text password
        return password_value == ONVIF_DEVICE_PASS


# ── Database helpers ────────────────────────────────────────────────────────

async def _get_cameras(db: AsyncSession) -> List[Camera]:
    result = await db.execute(select(Camera).where(Camera.is_enabled.is_(True)))
    return list(result.scalars().all())


async def _get_camera_by_id(db: AsyncSession, camera_id: str) -> Optional[Camera]:
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    return result.scalar_one_or_none()


async def _get_recordings_for_camera(
    db: AsyncSession, camera_id: str,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
) -> List[Recording]:
    q = select(Recording).where(Recording.camera_id == camera_id)
    if start:
        q = q.where(Recording.start_time >= start)
    if end:
        q = q.where(Recording.start_time <= end)
    q = q.order_by(Recording.start_time.desc()).limit(500)
    result = await db.execute(q)
    return list(result.scalars().all())


# =============================================================================
# Service Handlers
# =============================================================================

class ONVIFDeviceService:
    """Dispatches ONVIF SOAP requests to the correct handler."""

    def __init__(self):
        self._search_tokens: Dict[str, Dict[str, Any]] = {}

    # ── Dispatch ──────────────────────────────────────────────────────────

    async def handle(self, service_path: str, request: Request) -> Response:
        body_bytes = await request.body()
        action = self._extract_action(body_bytes, request)
        logger.debug(f"ONVIF {service_path} action={action}")

        if not _verify_username_token(body_bytes):
            return self._fault("ter:NotAuthorized", "Authentication failed")

        envelope = _soap_envelope()
        resp_body = _body(envelope)

        try:
            async with async_session_maker() as db:
                if service_path == "/onvif/device_service":
                    await self._handle_device(action, resp_body, request, db)
                elif service_path == "/onvif/media_service":
                    await self._handle_media(action, resp_body, request, db)
                elif service_path == "/onvif/media2_service":
                    await self._handle_media2(action, resp_body, request, db)
                elif service_path == "/onvif/ptz_service":
                    await self._handle_ptz(action, resp_body, request, db)
                elif service_path == "/onvif/recording_service":
                    await self._handle_recording(action, resp_body, request, db)
                elif service_path == "/onvif/search_service":
                    await self._handle_search(action, resp_body, request, db)
                elif service_path == "/onvif/replay_service":
                    await self._handle_replay(action, resp_body, request, db)
                elif service_path == "/onvif/event_service":
                    await self._handle_event(action, resp_body, request, db)
                else:
                    return self._fault("ter:ActionNotSupported", f"Unknown service {service_path}")
        except Exception as e:
            logger.exception(f"ONVIF handler error for {action}: {e}")
            return self._fault("ter:Receiver", "Internal error")

        xml_str = etree.tostring(envelope, pretty_print=True, xml_declaration=True, encoding="UTF-8")
        return Response(content=xml_str, media_type="application/soap+xml; charset=utf-8")

    def _extract_action(self, body_bytes: bytes, request: Request) -> str:
        action = request.headers.get("soapaction", "").strip('"')
        if action:
            return action
        # Fallback: parse Body first child
        try:
            root = etree.fromstring(body_bytes)
            body = root.find(_qn(NS_SOAP, "Body"))
            if body is not None and len(body) > 0:
                tag = body[0].tag
                return tag
        except Exception:
            pass
        return ""

    def _fault(self, code: str, text: str) -> Response:
        env = _soap_envelope()
        body = _body(env)
        fault = etree.SubElement(body, _qn(NS_SOAP, "Fault"))
        code_el = etree.SubElement(fault, _qn(NS_SOAP, "Code"))
        _add_text(code_el, NS_SOAP, "Value", code)
        reason_el = etree.SubElement(fault, _qn(NS_SOAP, "Reason"))
        text_el = etree.SubElement(reason_el, _qn(NS_SOAP, "Text"))
        text_el.set("{http://www.w3.org/XML/1998/namespace}lang", "en")
        text_el.text = text
        xml_str = etree.tostring(env, pretty_print=True, xml_declaration=True, encoding="UTF-8")
        return Response(content=xml_str, media_type="application/soap+xml; charset=utf-8", status_code=500)

    # =====================================================================
    # Device Service
    # =====================================================================

    async def _handle_device(self, action: str, body: etree.Element, request: Request, db: AsyncSession):
        if "GetDeviceInformation" in action:
            resp = etree.SubElement(body, _qn(NS_TDS, "GetDeviceInformationResponse"))
            _add_text(resp, NS_TDS, "Manufacturer", "GVD")
            _add_text(resp, NS_TDS, "Model", "NVR")
            from app import __version__
            _add_text(resp, NS_TDS, "FirmwareVersion", __version__)
            _add_text(resp, NS_TDS, "SerialNumber", "GVDNVR" + settings.JWT_SECRET_KEY[:8])
            _add_text(resp, NS_TDS, "HardwareId", "GVD-NVR-001")

        elif "GetCapabilities" in action:
            resp = etree.SubElement(body, _qn(NS_TDS, "GetCapabilitiesResponse"))
            caps = etree.SubElement(resp, _qn(NS_TDS, "Capabilities"))
            await self._build_capabilities(caps, request)

        elif "GetServices" in action:
            resp = etree.SubElement(body, _qn(NS_TDS, "GetServicesResponse"))
            await self._build_services(resp, request)

        elif "GetServiceCapabilities" in action:
            resp = etree.SubElement(body, _qn(NS_TDS, "GetServiceCapabilitiesResponse"))
            caps = etree.SubElement(resp, _qn(NS_TDS, "Capabilities"))
            caps.set("NetworkCapabilities", "true")
            caps.set("SecurityCapabilities", "true")
            caps.set("SystemCapabilities", "true")
            net = etree.SubElement(caps, _qn(NS_TDS, "Network"))
            net.set("IPFilter", "false")
            net.set("ZeroConfiguration", "false")
            net.set("IPVersion6", "false")
            net.set("DynDNS", "false")
            sec = etree.SubElement(caps, _qn(NS_TDS, "Security"))
            sec.set("TLS1.2", "false")
            sec.set("UsernameToken", "true")
            sec.set("HttpDigest", "false")
            sec.set("RELToken", "false")
            sys = etree.SubElement(caps, _qn(NS_TDS, "System"))
            sys.set("DiscoveryResolve", "false")
            sys.set("DiscoveryBye", "true")
            sys.set("RemoteDiscovery", "false")
            sys.set("SystemBackup", "false")
            sys.set("SystemLogging", "false")
            sys.set("FirmwareUpgrade", "false")
            sys.set("SupportedVersions", "2.50")

        elif "GetSystemDateAndTime" in action:
            resp = etree.SubElement(body, _qn(NS_TDS, "GetSystemDateAndTimeResponse"))
            await self._build_datetime(resp)

        elif "GetNetworkInterfaces" in action:
            resp = etree.SubElement(body, _qn(NS_TDS, "GetNetworkInterfacesResponse"))
            iface = etree.SubElement(resp, _qn(NS_TDS, "NetworkInterfaces"))
            iface.set("token", "eth0")
            enabled_el = etree.SubElement(iface, _qn(NS_TT, "Enabled"))
            enabled_el.text = "true"
            info = etree.SubElement(iface, _qn(NS_TT, "Info"))
            _add_text(info, NS_TT, "Name", "eth0")

        elif "GetScopes" in action:
            resp = etree.SubElement(body, _qn(NS_TDS, "GetScopesResponse"))
            for scope_def in [
                ("Fixed",        "onvif://www.onvif.org/type/video_server"),
                ("Fixed",        "onvif://www.onvif.org/type/network_video_transmitter"),
                ("Fixed",        "onvif://www.onvif.org/Profile/Streaming"),
                ("Fixed",        "onvif://www.onvif.org/Profile/T"),
                ("Fixed",        "onvif://www.onvif.org/Profile/G"),
                ("Configurable", "onvif://www.onvif.org/name/GVD-NVR"),
                ("Fixed",        "onvif://www.onvif.org/location/"),
            ]:
                scope = etree.SubElement(resp, _qn(NS_TDS, "Scopes"))
                _add_text(scope, NS_TT, "ScopeDef", scope_def[0])
                _add_text(scope, NS_TT, "ScopeItem", scope_def[1])

        elif "GetHostname" in action:
            resp = etree.SubElement(body, _qn(NS_TDS, "GetHostnameResponse"))
            info = etree.SubElement(resp, _qn(NS_TDS, "HostnameInformation"))
            _add_text(info, NS_TT, "FromDHCP", "false")
            _add_text(info, NS_TT, "Name", _get_external_host(request).split(":")[0])

        elif "GetUsers" in action:
            resp = etree.SubElement(body, _qn(NS_TDS, "GetUsersResponse"))
            user = etree.SubElement(resp, _qn(NS_TDS, "User"))
            _add_text(user, NS_TT, "Username", ONVIF_DEVICE_USER)
            _add_text(user, NS_TT, "UserLevel", "Administrator")

        elif "CreateUsers" in action:
            etree.SubElement(body, _qn(NS_TDS, "CreateUsersResponse"))

        elif "SetUser" in action:
            etree.SubElement(body, _qn(NS_TDS, "SetUserResponse"))

        elif "GetSystemUris" in action:
            resp = etree.SubElement(body, _qn(NS_TDS, "GetSystemUrisResponse"))
            base = _base_xaddr(request)
            # No firmware update / backup URIs needed
            _add_text(resp, NS_TDS, "SystemLogUris", "")

        elif "SystemReboot" in action:
            resp = etree.SubElement(body, _qn(NS_TDS, "SystemRebootResponse"))
            _add_text(resp, NS_TDS, "Message", "Reboot not supported on this NVR")

        elif "SetSystemFactoryDefault" in action:
            etree.SubElement(body, _qn(NS_TDS, "SetSystemFactoryDefaultResponse"))

        else:
            # For unimplemented device methods, return empty success
            tag = action.split("}")[-1] if "}" in action else action
            if tag:
                etree.SubElement(body, _qn(NS_TDS, tag + "Response"))

    async def _build_capabilities(self, parent: etree.Element, request: Request):
        base = _base_xaddr(request)
        # Device caps
        dev = etree.SubElement(parent, _qn(NS_TT, "Device"))
        _add_text(dev, NS_TT, "XAddr", f"{base}/onvif/device_service")
        net = etree.SubElement(dev, _qn(NS_TT, "Network"))
        net.set("IPFilter", "false")
        net.set("ZeroConfiguration", "false")
        net.set("IPVersion6", "false")
        net.set("DynDNS", "false")
        sys = etree.SubElement(dev, _qn(NS_TT, "System"))
        sys.set("DiscoveryResolve", "false")
        sys.set("DiscoveryBye", "true")
        sys.set("RemoteDiscovery", "false")
        sys.set("SystemBackup", "false")
        sys.set("SystemLogging", "false")
        sys.set("FirmwareUpgrade", "false")
        sec = etree.SubElement(dev, _qn(NS_TT, "Security"))
        sec.set("TLS1.2", "false")
        sec.set("UsernameToken", "true")
        sec.set("HttpDigest", "false")
        sec.set("RELToken", "false")

        # Media caps (Profile S)
        media = etree.SubElement(parent, _qn(NS_TT, "Media"))
        _add_text(media, NS_TT, "XAddr", f"{base}/onvif/media_service")
        sc = etree.SubElement(media, _qn(NS_TT, "StreamingCapabilities"))
        sc.set("RTPMulticast", "false")
        sc.set("RTP_TCP", "true")
        sc.set("RTP_RTSP_TCP", "true")

        # Event caps
        evt = etree.SubElement(parent, _qn(NS_TT, "Events"))
        _add_text(evt, NS_TT, "XAddr", f"{base}/onvif/event_service")
        _add_text(evt, NS_TT, "WSSubscriptionPolicySupport", "false")
        _add_text(evt, NS_TT, "WSPullPointSupport", "true")
        _add_text(evt, NS_TT, "WSPausableSubscriptionManagerInterfaceSupport", "false")

        # PTZ caps
        ptz = etree.SubElement(parent, _qn(NS_TT, "PTZ"))
        _add_text(ptz, NS_TT, "XAddr", f"{base}/onvif/ptz_service")

        # Extension (Profile G + Media2)
        ext = etree.SubElement(parent, _qn(NS_TT, "Extension"))

        media2 = etree.SubElement(ext, _qn(NS_TT, "Media"))
        _add_text(media2, NS_TT, "XAddr", f"{base}/onvif/media2_service")

        rec = etree.SubElement(ext, _qn(NS_TT, "Recording"))
        _add_text(rec, NS_TT, "XAddr", f"{base}/onvif/recording_service")

        search = etree.SubElement(ext, _qn(NS_TT, "Search"))
        _add_text(search, NS_TT, "XAddr", f"{base}/onvif/search_service")

        replay = etree.SubElement(ext, _qn(NS_TT, "Replay"))
        _add_text(replay, NS_TT, "XAddr", f"{base}/onvif/replay_service")

    async def _build_services(self, parent: etree.Element, request: Request):
        base = _base_xaddr(request)
        services = [
            (NS_TDS,  f"{base}/onvif/device_service",    2, 21),
            (NS_TRT,  f"{base}/onvif/media_service",     2, 6),
            (NS_TR2,  f"{base}/onvif/media2_service",    2, 0),
            (NS_TPTZ, f"{base}/onvif/ptz_service",       2, 4),
            (NS_TRC,  f"{base}/onvif/recording_service", 2, 0),
            (NS_TSE,  f"{base}/onvif/search_service",    2, 0),
            (NS_TRP,  f"{base}/onvif/replay_service",    1, 0),
            (NS_TEV,  f"{base}/onvif/event_service",     2, 4),
        ]
        for ns, xaddr, major, minor in services:
            svc_el = etree.SubElement(parent, _qn(NS_TDS, "Service"))
            _add_text(svc_el, NS_TDS, "Namespace", ns)
            _add_text(svc_el, NS_TDS, "XAddr", xaddr)
            ver = etree.SubElement(svc_el, _qn(NS_TDS, "Version"))
            _add_text(ver, NS_TT, "Major", major)
            _add_text(ver, NS_TT, "Minor", minor)

    async def _build_datetime(self, parent: etree.Element):
        now = datetime.now(timezone.utc)
        sdt = etree.SubElement(parent, _qn(NS_TDS, "SystemDateAndTime"))
        _add_text(sdt, NS_TT, "DateTimeType", "NTP")
        _add_text(sdt, NS_TT, "DaylightSavings", "false")
        tz = etree.SubElement(sdt, _qn(NS_TT, "TimeZone"))
        _add_text(tz, NS_TT, "TZ", "UTC+0")
        utc = etree.SubElement(sdt, _qn(NS_TT, "UTCDateTime"))
        d = etree.SubElement(utc, _qn(NS_TT, "Date"))
        _add_text(d, NS_TT, "Year", now.year)
        _add_text(d, NS_TT, "Month", now.month)
        _add_text(d, NS_TT, "Day", now.day)
        t = etree.SubElement(utc, _qn(NS_TT, "Time"))
        _add_text(t, NS_TT, "Hour", now.hour)
        _add_text(t, NS_TT, "Minute", now.minute)
        _add_text(t, NS_TT, "Second", now.second)

    # =====================================================================
    # Media Service (Profile S)
    # =====================================================================

    async def _handle_media(self, action: str, body: etree.Element, request: Request, db: AsyncSession):
        if "GetProfiles" in action:
            resp = etree.SubElement(body, _qn(NS_TRT, "GetProfilesResponse"))
            cameras = await _get_cameras(db)
            for cam in cameras:
                self._build_media_profile(resp, cam)

        elif "GetStreamUri" in action:
            resp = etree.SubElement(body, _qn(NS_TRT, "GetStreamUriResponse"))
            profile_token = self._extract_profile_token(await request.body())
            cam_id = self._profile_token_to_camera_id(profile_token)
            cam = await _get_camera_by_id(db, cam_id) if cam_id else None
            media_uri = etree.SubElement(resp, _qn(NS_TRT, "MediaUri"))
            uri = self._camera_rtsp_url(request, cam) if cam else ""
            _add_text(media_uri, NS_TT, "Uri", uri)
            _add_text(media_uri, NS_TT, "InvalidAfterConnect", "false")
            _add_text(media_uri, NS_TT, "InvalidAfterReboot", "false")
            _add_text(media_uri, NS_TT, "Timeout", "PT0S")

        elif "GetSnapshotUri" in action:
            resp = etree.SubElement(body, _qn(NS_TRT, "GetSnapshotUriResponse"))
            profile_token = self._extract_profile_token(await request.body())
            cam_id = self._profile_token_to_camera_id(profile_token)
            base = _base_xaddr(request)
            uri = f"{base}/api/cameras/{cam_id}/snapshot" if cam_id else ""
            media_uri = etree.SubElement(resp, _qn(NS_TRT, "MediaUri"))
            _add_text(media_uri, NS_TT, "Uri", uri)
            _add_text(media_uri, NS_TT, "InvalidAfterConnect", "false")
            _add_text(media_uri, NS_TT, "InvalidAfterReboot", "false")
            _add_text(media_uri, NS_TT, "Timeout", "PT0S")

        elif "GetVideoSources" in action:
            resp = etree.SubElement(body, _qn(NS_TRT, "GetVideoSourcesResponse"))
            cameras = await _get_cameras(db)
            for cam in cameras:
                vs = etree.SubElement(resp, _qn(NS_TT, "VideoSources"))
                vs.set("token", f"vs_{cam.id}")
                res = etree.SubElement(vs, _qn(NS_TT, "Resolution"))
                w, h = self._parse_resolution(cam.resolution)
                _add_text(res, NS_TT, "Width", w)
                _add_text(res, NS_TT, "Height", h)
                _add_text(vs, NS_TT, "Framerate", cam.fps or 25)

        elif "GetVideoSourceConfigurations" in action:
            resp = etree.SubElement(body, _qn(NS_TRT, "GetVideoSourceConfigurationsResponse"))
            cameras = await _get_cameras(db)
            for cam in cameras:
                vsc = etree.SubElement(resp, _qn(NS_TT, "Configurations"))
                vsc.set("token", f"vsc_{cam.id}")
                _add_text(vsc, NS_TT, "Name", f"VideoSource {cam.name}")
                _add_text(vsc, NS_TT, "UseCount", "1")
                _add_text(vsc, NS_TT, "SourceToken", f"vs_{cam.id}")
                bounds = etree.SubElement(vsc, _qn(NS_TT, "Bounds"))
                w, h = self._parse_resolution(cam.resolution)
                bounds.set("x", "0")
                bounds.set("y", "0")
                bounds.set("width", str(w))
                bounds.set("height", str(h))

        elif "GetVideoEncoderConfigurations" in action:
            resp = etree.SubElement(body, _qn(NS_TRT, "GetVideoEncoderConfigurationsResponse"))
            cameras = await _get_cameras(db)
            for cam in cameras:
                self._build_vec_element(resp, cam, NS_TT)

        elif "GetAudioSources" in action:
            # Return empty list — NVR doesn't expose audio sources
            etree.SubElement(body, _qn(NS_TRT, "GetAudioSourcesResponse"))

        elif "GetAudioEncoderConfigurations" in action:
            etree.SubElement(body, _qn(NS_TRT, "GetAudioEncoderConfigurationsResponse"))

        elif "GetMetadataConfigurations" in action:
            etree.SubElement(body, _qn(NS_TRT, "GetMetadataConfigurationsResponse"))

        elif "GetProfile" in action and "GetProfiles" not in action:
            # GetProfile (singular) — find by token
            resp = etree.SubElement(body, _qn(NS_TRT, "GetProfileResponse"))
            req_bytes = await request.body()
            profile_token = self._extract_profile_token(req_bytes)
            cam_id = self._profile_token_to_camera_id(profile_token)
            cam = await _get_camera_by_id(db, cam_id) if cam_id else None
            if cam:
                self._build_media_profile(resp, cam)

        elif "GetCompatibleVideoEncoderConfigurations" in action:
            resp = etree.SubElement(body, _qn(NS_TRT, "GetCompatibleVideoEncoderConfigurationsResponse"))
            cameras = await _get_cameras(db)
            for cam in cameras:
                self._build_vec_element(resp, cam, NS_TT)

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

    def _build_media_profile(self, parent: etree.Element, cam: Camera):
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
        w, h = self._parse_resolution(cam.resolution)
        bounds.set("x", "0")
        bounds.set("y", "0")
        bounds.set("width", str(w))
        bounds.set("height", str(h))

        self._build_vec_element(prof, cam, NS_TT)

    def _build_vec_element(self, parent: etree.Element, cam: Camera, ns: str):
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
        w, h = self._parse_resolution(cam.resolution)
        _add_text(res, ns, "Width", w)
        _add_text(res, ns, "Height", h)
        rate = etree.SubElement(cfg, _qn(ns, "RateControl"))
        _add_text(rate, ns, "FrameRateLimit", cam.fps or 25)
        _add_text(rate, ns, "EncodingInterval", "1")
        _add_text(rate, ns, "BitrateLimit", self._parse_bitrate(cam.bitrate))
        if codec == "H264":
            h264 = etree.SubElement(cfg, _qn(ns, "H264"))
            _add_text(h264, ns, "GovLength", 30)
            _add_text(h264, ns, "H264Profile", "Main")

    # =====================================================================
    # Media2 Service (Profile T)
    # =====================================================================

    async def _handle_media2(self, action: str, body: etree.Element, request: Request, db: AsyncSession):
        if "GetProfiles" in action:
            resp = etree.SubElement(body, _qn(NS_TR2, "GetProfilesResponse"))
            cameras = await _get_cameras(db)
            for cam in cameras:
                self._build_media2_profile(resp, cam)

        elif "GetStreamUri" in action:
            resp = etree.SubElement(body, _qn(NS_TR2, "GetStreamUriResponse"))
            profile_token = self._extract_profile_token(await request.body())
            cam_id = self._profile_token_to_camera_id(profile_token)
            cam = await _get_camera_by_id(db, cam_id) if cam_id else None
            uri = self._camera_rtsp_url(request, cam) if cam else ""
            _add_text(resp, NS_TR2, "Uri", uri)
            _add_text(resp, NS_TR2, "InvalidAfterConnect", "false")
            _add_text(resp, NS_TR2, "InvalidAfterReboot", "false")
            _add_text(resp, NS_TR2, "Timeout", "PT0S")

        elif "GetSnapshotUri" in action:
            resp = etree.SubElement(body, _qn(NS_TR2, "GetSnapshotUriResponse"))
            profile_token = self._extract_profile_token(await request.body())
            cam_id = self._profile_token_to_camera_id(profile_token)
            base = _base_xaddr(request)
            uri = f"{base}/api/cameras/{cam_id}/snapshot" if cam_id else ""
            _add_text(resp, NS_TR2, "Uri", uri)

        elif "GetVideoSources" in action:
            resp = etree.SubElement(body, _qn(NS_TR2, "GetVideoSourcesResponse"))
            cameras = await _get_cameras(db)
            for cam in cameras:
                vs = etree.SubElement(resp, _qn(NS_TT, "VideoSources"))
                vs.set("token", f"vs_{cam.id}")
                res = etree.SubElement(vs, _qn(NS_TT, "Resolution"))
                w, h = self._parse_resolution(cam.resolution)
                _add_text(res, NS_TT, "Width", w)
                _add_text(res, NS_TT, "Height", h)
                _add_text(vs, NS_TT, "Framerate", cam.fps or 25)

        elif "GetVideoSourceConfigurations" in action:
            resp = etree.SubElement(body, _qn(NS_TR2, "GetVideoSourceConfigurationsResponse"))
            cameras = await _get_cameras(db)
            for cam in cameras:
                vsc = etree.SubElement(resp, _qn(NS_TT, "Configurations"))
                vsc.set("token", f"vsc_{cam.id}")
                _add_text(vsc, NS_TT, "Name", f"VideoSource {cam.name}")
                _add_text(vsc, NS_TT, "UseCount", "1")
                _add_text(vsc, NS_TT, "SourceToken", f"vs_{cam.id}")
                bounds = etree.SubElement(vsc, _qn(NS_TT, "Bounds"))
                w, h = self._parse_resolution(cam.resolution)
                bounds.set("x", "0")
                bounds.set("y", "0")
                bounds.set("width", str(w))
                bounds.set("height", str(h))

        elif "GetVideoEncoderConfigurations" in action:
            resp = etree.SubElement(body, _qn(NS_TR2, "GetVideoEncoderConfigurationsResponse"))
            cameras = await _get_cameras(db)
            for cam in cameras:
                self._build_vec_element(resp, cam, NS_TT)

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
            profile_token = self._extract_profile_token(req_bytes)
            cam_id = self._profile_token_to_camera_id(profile_token)
            cam = await _get_camera_by_id(db, cam_id) if cam_id else None
            if cam:
                self._build_media2_profile(resp, cam)

        else:
            tag = action.split("}")[-1] if "}" in action else action
            if tag:
                etree.SubElement(body, _qn(NS_TR2, tag + "Response"))

    def _build_media2_profile(self, parent: etree.Element, cam: Camera):
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
        w, h = self._parse_resolution(cam.resolution)
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
        _add_text(rate, NS_TT, "BitrateLimit", self._parse_bitrate(cam.bitrate))

    # =====================================================================
    # PTZ Service (virtual — forwards to underlying camera ONVIF)
    # =====================================================================

    async def _handle_ptz(self, action: str, body: etree.Element, request: Request, db: AsyncSession):
        """
        Virtual PTZ service.  The NVR doesn't move lenses itself — it exposes
        minimal PTZ metadata so VMS clients don't show errors.  Actual PTZ
        commands are forwarded to the camera's own ONVIF endpoint via the
        existing onvif_service helpers when available; otherwise a well-formed
        empty response is returned.
        """
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
            cameras = await _get_cameras(db)
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
            cam_id = self._extract_ptz_token(req_bytes)
            cam = await _get_camera_by_id(db, cam_id) if cam_id else None
            if cam:
                cfg = etree.SubElement(resp, _qn(NS_TPTZ, "PTZConfiguration"))
                cfg.set("token", f"ptz_{cam.id}")
                _add_text(cfg, NS_TT, "Name", f"PTZ {cam.name}")
                _add_text(cfg, NS_TT, "NodeToken", f"ptznode_{cam.id}")

        elif "GetPresets" in action:
            resp = etree.SubElement(body, _qn(NS_TPTZ, "GetPresetsResponse"))
            # Attempt to forward to camera's ONVIF endpoint
            req_bytes = await request.body()
            profile_token = self._extract_profile_token(req_bytes)
            cam_id = self._profile_token_to_camera_id(profile_token)
            cam = await _get_camera_by_id(db, cam_id) if cam_id else None
            if cam:
                try:
                    presets = await self._forward_get_presets(cam)
                    for preset in presets:
                        p = etree.SubElement(resp, _qn(NS_TPTZ, "Preset"))
                        p.set("token", str(preset.get("token", "")))
                        _add_text(p, NS_TT, "Name", preset.get("name", ""))
                except Exception as e:
                    logger.debug(f"PTZ GetPresets forward failed for cam {cam_id}: {e}")
                    # Return empty — valid per ONVIF when no presets defined

        elif "GotoPreset" in action:
            etree.SubElement(body, _qn(NS_TPTZ, "GotoPresetResponse"))
            req_bytes = await request.body()
            profile_token = self._extract_profile_token(req_bytes)
            cam_id = self._profile_token_to_camera_id(profile_token)
            cam = await _get_camera_by_id(db, cam_id) if cam_id else None
            if cam:
                try:
                    preset_token = self._extract_text_field(req_bytes, "PresetToken")
                    await self._forward_goto_preset(cam, profile_token or f"profile_{cam.id}", preset_token or "")
                except Exception as e:
                    logger.debug(f"PTZ GotoPreset forward failed: {e}")

        elif "ContinuousMove" in action:
            etree.SubElement(body, _qn(NS_TPTZ, "ContinuousMoveResponse"))

        elif "RelativeMove" in action:
            etree.SubElement(body, _qn(NS_TPTZ, "RelativeMoveResponse"))

        elif "AbsoluteMove" in action:
            etree.SubElement(body, _qn(NS_TPTZ, "AbsoluteMoveResponse"))

        elif "Stop" in action:
            etree.SubElement(body, _qn(NS_TPTZ, "StopResponse"))

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
            cameras = await _get_cameras(db)
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

    async def _forward_get_presets(self, cam: Camera) -> List[Dict[str, Any]]:
        """Try to get presets from camera's own ONVIF PTZ service."""
        try:
            from app.cameras.onvif_service import get_ptz_presets
            return await get_ptz_presets(cam)
        except Exception:
            return []

    async def _forward_goto_preset(self, cam: Camera, profile_token: str, preset_token: str):
        """Forward GotoPreset to camera's own ONVIF PTZ service."""
        try:
            from app.cameras.onvif_service import goto_ptz_preset
            await goto_ptz_preset(cam, profile_token, preset_token)
        except Exception:
            pass

    # =====================================================================
    # Recording Service (Profile G)
    # =====================================================================

    async def _handle_recording(self, action: str, body: etree.Element, request: Request, db: AsyncSession):
        if "GetRecordings" in action:
            resp = etree.SubElement(body, _qn(NS_TRC, "GetRecordingsResponse"))
            cameras = await _get_cameras(db)
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
            cameras = await _get_cameras(db)
            summary = etree.SubElement(resp, _qn(NS_TRC, "Summary"))
            _add_text(summary, NS_TT, "DataFrom", "1970-01-01T00:00:00Z")
            _add_text(summary, NS_TT, "DataUntil", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
            _add_text(summary, NS_TT, "NumberRecordings", len(cameras))

        elif "GetRecordingConfiguration" in action:
            resp = etree.SubElement(body, _qn(NS_TRC, "GetRecordingConfigurationResponse"))
            req_bytes = await request.body()
            rec_token = self._extract_recording_token(req_bytes)
            cam_id = rec_token.replace("rec_", "") if rec_token and rec_token.startswith("rec_") else None
            cam = await _get_camera_by_id(db, cam_id) if cam_id else None
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
            cameras = await _get_cameras(db)
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

    # =====================================================================
    # Search Service
    # =====================================================================

    async def _handle_search(self, action: str, body: etree.Element, request: Request, db: AsyncSession):
        if "FindRecordings" in action:
            resp = etree.SubElement(body, _qn(NS_TSE, "FindRecordingsResponse"))
            token = f"search_{uuid.uuid4().hex[:8]}"
            self._search_tokens[token] = {"type": "recordings", "created": datetime.now(timezone.utc)}
            _add_text(resp, NS_TSE, "SearchToken", token)

        elif "GetRecordingSearchResults" in action:
            resp = etree.SubElement(body, _qn(NS_TSE, "GetRecordingSearchResultsResponse"))
            req_bytes = await request.body()
            rec_token = self._extract_recording_token(req_bytes)
            start, end = self._extract_time_range(req_bytes)

            cameras = await _get_cameras(db)
            result_list = etree.SubElement(resp, _qn(NS_TSE, "ResultList"))
            _add_text(result_list, NS_TSE, "SearchState", "Completed")
            for cam in cameras:
                if rec_token and f"rec_{cam.id}" != rec_token:
                    continue
                recordings = await _get_recordings_for_camera(db, cam.id, start, end)
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
            self._search_tokens[token] = {"type": "events", "created": datetime.now(timezone.utc)}
            _add_text(resp, NS_TSE, "SearchToken", token)

        elif "GetEventSearchResults" in action:
            resp = etree.SubElement(body, _qn(NS_TSE, "GetEventSearchResultsResponse"))
            result_list = etree.SubElement(resp, _qn(NS_TSE, "ResultList"))
            _add_text(result_list, NS_TSE, "SearchState", "Completed")

        elif "EndSearch" in action:
            resp = etree.SubElement(body, _qn(NS_TSE, "EndSearchResponse"))
            req_bytes = await request.body()
            token = self._extract_search_token(req_bytes)
            if token and token in self._search_tokens:
                self._search_tokens.pop(token, None)

        elif "GetServiceCapabilities" in action:
            resp = etree.SubElement(body, _qn(NS_TSE, "GetServiceCapabilitiesResponse"))
            caps = etree.SubElement(resp, _qn(NS_TSE, "Capabilities"))
            caps.set("MetadataSearch", "false")

        else:
            tag = action.split("}")[-1] if "}" in action else action
            if tag:
                etree.SubElement(body, _qn(NS_TSE, tag + "Response"))

    # =====================================================================
    # Replay Service
    # =====================================================================

    async def _handle_replay(self, action: str, body: etree.Element, request: Request, db: AsyncSession):
        if "GetReplayUri" in action:
            resp = etree.SubElement(body, _qn(NS_TRP, "GetReplayUriResponse"))
            req_bytes = await request.body()
            rec_token = self._extract_recording_token(req_bytes)
            cam_id = rec_token.replace("rec_", "") if rec_token and rec_token.startswith("rec_") else None
            cam = await _get_camera_by_id(db, cam_id) if cam_id else None
            uri = self._camera_rtsp_url(request, cam) if cam else ""
            _add_text(resp, NS_TRP, "Uri", uri)

        elif "GetServiceCapabilities" in action:
            resp = etree.SubElement(body, _qn(NS_TRP, "GetServiceCapabilitiesResponse"))
            caps = etree.SubElement(resp, _qn(NS_TRP, "Capabilities"))
            caps.set("ReversePlayback", "false")
            caps.set("SessionTimeoutRange", "1 60")

        else:
            tag = action.split("}")[-1] if "}" in action else action
            if tag:
                etree.SubElement(body, _qn(NS_TRP, tag + "Response"))

    # =====================================================================
    # Event Service
    # =====================================================================

    async def _handle_event(self, action: str, body: etree.Element, request: Request, db: AsyncSession):
        if "GetEventProperties" in action:
            NS_WSTOP = "http://docs.oasis-open.org/wsn/t-1"
            NS_TOPICS = "http://www.onvif.org/ver10/topics"
            resp = etree.SubElement(body, _qn(NS_TEV, "GetEventPropertiesResponse"))
            _add_text(resp, NS_TEV, "TopicNamespaceLocation",
                      "http://www.onvif.org/onvif/ver10/topics/topicns.xml")
            _add_text(resp, NS_TEV, "FixedTopicSet", "true")
            topic_set = etree.SubElement(resp, _qn(NS_TEV, "TopicSet"))
            topic_set.set(f"{{{NS_TOPICS}}}TopicNamespace",
                          "http://www.onvif.org/ver10/topics")
            # Motion Alarm topic
            vs_el = etree.SubElement(topic_set, _qn(NS_TOPICS, "VideoSource"))
            motion = etree.SubElement(vs_el, _qn(NS_TOPICS, "MotionAlarm"))
            motion.set(_qn(NS_WSTOP, "topic"), "true")
            # DigitalInput topic
            dev_el = etree.SubElement(topic_set, _qn(NS_TOPICS, "Device"))
            trigger = etree.SubElement(dev_el, _qn(NS_TOPICS, "Trigger"))
            di = etree.SubElement(trigger, _qn(NS_TOPICS, "DigitalInput"))
            di.set(_qn(NS_WSTOP, "topic"), "true")
            _add_text(resp, NS_TEV, "TopicExpressionDialect",
                      "http://www.onvif.org/ver10/tev/topicExpression/ConcreteSet")
            _add_text(resp, NS_TEV, "MessageContentFilterDialect",
                      "http://www.onvif.org/ver10/tev/messageContentFilter/ItemFilter")
            _add_text(resp, NS_TEV, "MessageContentSchemaLocation",
                      "http://www.onvif.org/ver10/schema/onvif.xsd")

        elif "CreatePullPointSubscription" in action:
            resp = etree.SubElement(body, _qn(NS_TEV, "CreatePullPointSubscriptionResponse"))
            ref = etree.SubElement(resp, _qn(NS_WSNT, "SubscriptionReference"))
            addr = etree.SubElement(ref, _qn(NS_WSA, "Address"))
            addr.text = f"{_base_xaddr(request)}/onvif/event_service"
            _add_text(resp, NS_WSNT, "CurrentTime",
                      datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
            _add_text(resp, NS_WSNT, "TerminationTime",
                      (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"))

        elif "PullMessages" in action:
            resp = etree.SubElement(body, _qn(NS_TEV, "PullMessagesResponse"))
            _add_text(resp, NS_TEV, "CurrentTime",
                      datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
            _add_text(resp, NS_TEV, "TerminationTime",
                      (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"))
            # Empty NotificationMessage list is valid per ONVIF spec

        elif "Renew" in action:
            resp = etree.SubElement(body, _qn(NS_TEV, "RenewResponse"))
            _add_text(resp, NS_WSNT, "TerminationTime",
                      (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"))
            _add_text(resp, NS_WSNT, "CurrentTime",
                      datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

        elif "Unsubscribe" in action:
            etree.SubElement(body, _qn(NS_TEV, "UnsubscribeResponse"))

        elif "GetServiceCapabilities" in action:
            resp = etree.SubElement(body, _qn(NS_TEV, "GetServiceCapabilitiesResponse"))
            caps = etree.SubElement(resp, _qn(NS_TEV, "Capabilities"))
            caps.set("WSSubscriptionPolicySupport", "false")
            caps.set("WSPullPointSupport", "true")
            caps.set("WSPausableSubscriptionManagerInterfaceSupport", "false")
            caps.set("MaxNotificationProducers", "1")
            caps.set("MaxPullPoints", "10")
            caps.set("PersistentNotificationStorage", "false")

        else:
            tag = action.split("}")[-1] if "}" in action else action
            if tag:
                etree.SubElement(body, _qn(NS_TEV, tag + "Response"))

    # =====================================================================
    # Helpers
    # =====================================================================

    def _camera_rtsp_url(self, request: Request, cam: Optional[Camera]) -> str:
        if not cam:
            return ""
        host = _get_external_host(request).split(":")[0]
        return f"rtsp://{host}:{settings.GO2RTC_RTSP_PORT}/{cam.id}"

    def _parse_resolution(self, res: Optional[str]):
        if not res:
            return 1920, 1080
        try:
            parts = str(res).lower().split("x")
            if len(parts) == 2:
                return int(parts[0]), int(parts[1])
        except Exception:
            pass
        return 1920, 1080

    def _parse_bitrate(self, bitrate: Optional[str]) -> int:
        if not bitrate:
            return 4096
        try:
            return int(str(bitrate).replace("kbps", "").replace(" ", ""))
        except Exception:
            return 4096

    def _extract_profile_token(self, xml_bytes: bytes) -> Optional[str]:
        try:
            root = etree.fromstring(xml_bytes)
            for tag in ("ProfileToken", "{%s}ProfileToken" % NS_TRT, "{%s}ProfileToken" % NS_TR2):
                el = root.find(".//" + tag)
                if el is not None:
                    return el.text
        except Exception:
            pass
        return None

    def _profile_token_to_camera_id(self, token: Optional[str]) -> Optional[str]:
        if not token:
            return None
        if token.startswith("profile_"):
            return token[8:]
        return token

    def _extract_ptz_token(self, xml_bytes: bytes) -> Optional[str]:
        try:
            root = etree.fromstring(xml_bytes)
            for tag in ("PTZConfigurationToken", "{%s}PTZConfigurationToken" % NS_TPTZ):
                el = root.find(".//" + tag)
                if el is not None:
                    t = el.text or ""
                    return t.replace("ptz_", "") if t.startswith("ptz_") else t
        except Exception:
            pass
        return None

    def _extract_text_field(self, xml_bytes: bytes, field: str) -> Optional[str]:
        try:
            root = etree.fromstring(xml_bytes)
            el = root.find(".//" + field)
            if el is None:
                el = root.find(".//{*}" + field)
            if el is not None:
                return el.text
        except Exception:
            pass
        return None

    def _extract_search_token(self, xml_bytes: bytes) -> Optional[str]:
        try:
            root = etree.fromstring(xml_bytes)
            for tag in ("SearchToken", "{%s}SearchToken" % NS_TSE):
                el = root.find(".//" + tag)
                if el is not None:
                    return el.text
        except Exception:
            pass
        return None

    def _extract_recording_token(self, xml_bytes: bytes) -> Optional[str]:
        try:
            root = etree.fromstring(xml_bytes)
            for tag in ("RecordingToken",
                        "{%s}RecordingToken" % NS_TRC,
                        "{%s}RecordingToken" % NS_TSE,
                        "{%s}RecordingToken" % NS_TRP):
                el = root.find(".//" + tag)
                if el is not None:
                    return el.text
        except Exception:
            pass
        return None

    def _extract_time_range(self, xml_bytes: bytes):
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


# Module singleton
onvif_device_service = ONVIFDeviceService()
