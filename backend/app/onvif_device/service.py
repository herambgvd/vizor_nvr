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

import asyncio
import logging
import base64
import hashlib
import uuid
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple

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
NS_TIMG  = "http://www.onvif.org/ver20/imaging/wsdl"
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
TIMG_ENV = "{%s}" % NS_TIMG
TT_ENV   = "{%s}" % NS_TT
WSNT_ENV = "{%s}" % NS_WSNT
WSRF_ENV = "{%s}" % NS_WSRF

# ── ONVIF Device credentials ────────────────────────────────────────────────
ONVIF_DEVICE_USER = os.getenv("ONVIF_DEVICE_USERNAME", "admin")
ONVIF_DEVICE_PASS = os.getenv("ONVIF_DEVICE_PASSWORD", "admin")

# ── PullPoint subscription state ─────────────────────────────────────────────
# keyed by subscription token (UUID hex string)
subscription_queues: Dict[str, asyncio.Queue] = {}
subscription_expires: Dict[str, datetime] = {}
_QUEUE_MAX_SIZE = 200
_SUBSCRIPTION_TTL_SECONDS = 300  # 5 minutes default

# ── Audio encoder configuration cache ────────────────────────────────────────
# keyed by camera_id → (list_of_configs, cached_at)
_audio_encoder_cache: Dict[str, Tuple[list, datetime]] = {}
_AUDIO_CACHE_TTL = 300  # 5 minutes

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
        "timg": NS_TIMG,
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

class _SOAPFault(Exception):
    """Internal sentinel to signal a SOAP fault from within service handlers."""
    def __init__(self, code: str, text: str):
        self.code = code
        self.text = text
        super().__init__(text)


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
                elif service_path == "/onvif/imaging_service":
                    await self._handle_imaging(action, resp_body, request, db)
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
        except _SOAPFault as sf:
            return self._fault(sf.code, sf.text)
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

        img = etree.SubElement(parent, _qn(NS_TT, "Imaging"))
        _add_text(img, NS_TT, "XAddr", f"{base}/onvif/imaging_service")

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
            (NS_TIMG, f"{base}/onvif/imaging_service",    2, 0),
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

        elif "GetAudioEncoderConfiguration" in action and "GetAudioEncoderConfigurations" not in action:
            resp = etree.SubElement(body, _qn(NS_TRT, "GetAudioEncoderConfigurationResponse"))
            req_bytes = await request.body()
            aec_token = self._extract_text_field(req_bytes, "ConfigurationToken") or ""
            cam_id = aec_token.replace("aec_", "") if aec_token.startswith("aec_") else None
            cam = await _get_camera_by_id(db, cam_id) if cam_id else None
            if cam:
                cfgs = await self._get_audio_encoder_configs(cam)
                for cfg in cfgs:
                    self._build_aec_element(resp, cam.id, cfg, NS_TRT)

        elif "GetAudioEncoderConfigurations" in action:
            resp = etree.SubElement(body, _qn(NS_TRT, "GetAudioEncoderConfigurationsResponse"))
            cameras = await _get_cameras(db)
            for cam in cameras:
                cfgs = await self._get_audio_encoder_configs(cam)
                for cfg in cfgs:
                    self._build_aec_element(resp, cam.id, cfg, NS_TRT)

        elif "GetCompatibleAudioEncoderConfigurations" in action:
            resp = etree.SubElement(body, _qn(NS_TRT, "GetCompatibleAudioEncoderConfigurationsResponse"))
            req_bytes = await request.body()
            profile_token = self._extract_profile_token(req_bytes)
            cam_id = self._profile_token_to_camera_id(profile_token)
            cam = await _get_camera_by_id(db, cam_id) if cam_id else None
            if cam:
                cfgs = await self._get_audio_encoder_configs(cam)
                for cfg in cfgs:
                    self._build_aec_element(resp, cam.id, cfg, NS_TRT)

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
            req_bytes = await request.body()
            profile_token = self._extract_profile_token(req_bytes)
            cam_id = self._profile_token_to_camera_id(profile_token)
            cam = await _get_camera_by_id(db, cam_id) if cam_id else None
            if cam:
                try:
                    velocity = self._extract_velocity(req_bytes)
                    await self._forward_move(cam, "continuous", velocity, profile_token)
                except Exception as e:
                    logger.debug(f"PTZ ContinuousMove forward failed: {e}")

        elif "RelativeMove" in action:
            etree.SubElement(body, _qn(NS_TPTZ, "RelativeMoveResponse"))
            req_bytes = await request.body()
            profile_token = self._extract_profile_token(req_bytes)
            cam_id = self._profile_token_to_camera_id(profile_token)
            cam = await _get_camera_by_id(db, cam_id) if cam_id else None
            if cam:
                try:
                    translation = self._extract_velocity(req_bytes)
                    await self._forward_move(cam, "relative", translation, profile_token)
                except Exception as e:
                    logger.debug(f"PTZ RelativeMove forward failed: {e}")

        elif "AbsoluteMove" in action:
            etree.SubElement(body, _qn(NS_TPTZ, "AbsoluteMoveResponse"))
            req_bytes = await request.body()
            profile_token = self._extract_profile_token(req_bytes)
            cam_id = self._profile_token_to_camera_id(profile_token)
            cam = await _get_camera_by_id(db, cam_id) if cam_id else None
            if cam:
                try:
                    position = self._extract_velocity(req_bytes)
                    await self._forward_move(cam, "absolute", position, profile_token)
                except Exception as e:
                    logger.debug(f"PTZ AbsoluteMove forward failed: {e}")

        elif "Stop" in action:
            etree.SubElement(body, _qn(NS_TPTZ, "StopResponse"))
            req_bytes = await request.body()
            profile_token = self._extract_profile_token(req_bytes)
            cam_id = self._profile_token_to_camera_id(profile_token)
            cam = await _get_camera_by_id(db, cam_id) if cam_id else None
            if cam:
                try:
                    await self._forward_stop(cam, profile_token)
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

    async def _forward_goto_preset(self, cam: Camera, profile_token: str, preset_token: str):
        """Forward GotoPreset to camera's own ONVIF PTZ service."""
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

    async def _forward_move(self, cam: Camera, move_type: str, params: dict, profile_token: str):
        """Forward ContinuousMove/RelativeMove/AbsoluteMove to camera PTZ."""
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

    async def _forward_stop(self, cam: Camera, profile_token: str):
        """Forward Stop to camera PTZ."""
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

    def _extract_velocity(self, xml_bytes: bytes) -> dict:
        """Parse Velocity/Position element from PTZ request body."""
        try:
            root = etree.fromstring(xml_bytes)
            vel = root.find(".//{%s}Velocity" % NS_TPTZ)
            if vel is not None:
                pt = vel.find("{%s}PanTilt" % NS_TT)
                zoom = vel.find("{%s}Zoom" % NS_TT)
                return {
                    "x": float(pt.get("x", 0)) if pt is not None else 0.0,
                    "y": float(pt.get("y", 0)) if pt is not None else 0.0,
                    "z": float(zoom.get("x", 0)) if zoom is not None else 0.0,
                }
            # Try Position for AbsoluteMove
            pos = root.find(".//{%s}Position" % NS_TPTZ)
            if pos is not None:
                pt = pos.find("{%s}PanTilt" % NS_TT)
                zoom = pos.find("{%s}Zoom" % NS_TT)
                return {
                    "x": float(pt.get("x", 0)) if pt is not None else 0.0,
                    "y": float(pt.get("y", 0)) if pt is not None else 0.0,
                    "z": float(zoom.get("x", 0)) if zoom is not None else 0.0,
                }
        except Exception:
            pass
        return {"x": 0.0, "y": 0.0, "z": 0.0}

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
    # Imaging Service
    # =====================================================================

    async def _handle_imaging(self, action: str, body: etree.Element, request: Request, db: AsyncSession):
        if "GetServiceCapabilities" in action:
            resp = etree.SubElement(body, _qn(NS_TIMG, "GetServiceCapabilitiesResponse"))
            caps = etree.SubElement(resp, _qn(NS_TIMG, "Capabilities"))
            caps.set("ImageStabilization", "false")
            caps.set("Presets", "false")

        elif "GetImagingSettings" in action:
            resp = etree.SubElement(body, _qn(NS_TIMG, "GetImagingSettingsResponse"))
            req_bytes = await request.body()
            vs_token = self._extract_video_source_token(req_bytes)
            cam = await self._camera_from_video_source_token(db, vs_token)
            if cam and cam.onvif_host:
                from app.cameras.onvif_service import onvif_service
                from app.core.crypto import decrypt_value
                try:
                    settings = await onvif_service.get_imaging_settings(
                        cam.onvif_host, cam.onvif_port or 80,
                        decrypt_value(cam.onvif_username) or "admin",
                        decrypt_value(cam.onvif_password) or "admin",
                    )
                    self._build_imaging_settings(resp, settings)
                except Exception as e:
                    logger.debug(f"GetImagingSettings proxy failed for {cam.id}: {e}")
                    self._build_imaging_settings(resp, {})
            else:
                self._build_imaging_settings(resp, {})

        elif "SetImagingSettings" in action:
            resp = etree.SubElement(body, _qn(NS_TIMG, "SetImagingSettingsResponse"))
            req_bytes = await request.body()
            vs_token = self._extract_video_source_token(req_bytes)
            cam = await self._camera_from_video_source_token(db, vs_token)
            settings_patch = self._extract_imaging_settings_patch(req_bytes)
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
                    if not ok:
                        raise _SOAPFault("ter:Action", "Camera rejected imaging settings")
                except Exception as e:
                    logger.debug(f"SetImagingSettings proxy failed for {cam.id}: {e}")
                    raise _SOAPFault("ter:Action", "Failed to apply imaging settings")

        elif "GetOptions" in action:
            resp = etree.SubElement(body, _qn(NS_TIMG, "GetOptionsResponse"))
            req_bytes = await request.body()
            vs_token = self._extract_video_source_token(req_bytes)
            cam = await self._camera_from_video_source_token(db, vs_token)
            if cam and cam.onvif_host:
                from app.cameras.onvif_service import onvif_service
                from app.core.crypto import decrypt_value
                try:
                    opts = await onvif_service.get_imaging_options(
                        cam.onvif_host, cam.onvif_port or 80,
                        decrypt_value(cam.onvif_username) or "admin",
                        decrypt_value(cam.onvif_password) or "admin",
                    )
                    self._build_imaging_options(resp, opts)
                except Exception as e:
                    logger.debug(f"GetOptions proxy failed for {cam.id}: {e}")
                    self._build_imaging_options(resp, {})
            else:
                self._build_imaging_options(resp, {})

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
            resp = etree.SubElement(body, _qn(NS_TIMG, "MoveResponse"))
            req_bytes = await request.body()
            vs_token = self._extract_video_source_token(req_bytes)
            cam = await self._camera_from_video_source_token(db, vs_token)
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
            vs_token = self._extract_video_source_token(req_bytes)
            cam = await self._camera_from_video_source_token(db, vs_token)
            if cam and cam.onvif_host:
                from app.cameras.onvif_service import onvif_service
                from app.core.crypto import decrypt_value
                try:
                    settings = await onvif_service.get_imaging_settings(
                        cam.onvif_host, cam.onvif_port or 80,
                        decrypt_value(cam.onvif_username) or "admin",
                        decrypt_value(cam.onvif_password) or "admin",
                    )
                    status = etree.SubElement(resp, _qn(NS_TIMG, "Status"))
                    _add_text(status, NS_TT, "Brightness", settings.get("brightness", 50))
                    _add_text(status, NS_TT, "Contrast", settings.get("contrast", 50))
                    _add_text(status, NS_TT, "ColorSaturation", settings.get("color_saturation", 50))
                    _add_text(status, NS_TT, "Sharpness", settings.get("sharpness", 50))
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

    def _build_imaging_settings(self, parent: etree.Element, settings: dict):
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

    def _build_imaging_options(self, parent: etree.Element, opts: dict):
        img_opts = etree.SubElement(parent, _qn(NS_TIMG, "ImagingOptions"))
        for field in ("brightness", "color_saturation", "contrast", "sharpness"):
            if field in opts:
                fmin = opts[field].get("min", 0)
                fmax = opts[field].get("max", 100)
                el = etree.SubElement(img_opts, _qn(NS_TT, field.capitalize()))
                rng = etree.SubElement(el, _qn(NS_TT, "MinMax"))
                _add_text(rng, NS_TT, "Min", fmin)
                _add_text(rng, NS_TT, "Max", fmax)

    def _extract_video_source_token(self, xml_bytes: bytes) -> Optional[str]:
        try:
            root = etree.fromstring(xml_bytes)
            for tag in ("VideoSourceToken", "{%s}VideoSourceToken" % NS_TT):
                el = root.find(".//" + tag)
                if el is not None:
                    return el.text
        except Exception:
            pass
        return None

    async def _camera_from_video_source_token(self, db: AsyncSession, vs_token: Optional[str]) -> Optional[Camera]:
        if not vs_token:
            return None
        cam_id = vs_token.replace("vs_", "") if vs_token.startswith("vs_") else vs_token
        return await _get_camera_by_id(db, cam_id)

    def _extract_imaging_settings_patch(self, xml_bytes: bytes) -> Optional[dict]:
        try:
            root = etree.fromstring(xml_bytes)
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

    # =====================================================================
    # Replay Service
    # =====================================================================

    async def _handle_replay(self, action: str, body: etree.Element, request: Request, db: AsyncSession):
        if "GetReplayUri" in action:
            from app.onvif_device.replay import handle_get_replay_uri
            req_bytes = await request.body()
            rec_token = self._extract_recording_token(req_bytes)
            uri, fault_code = await handle_get_replay_uri(req_bytes, rec_token, request, db)
            if fault_code:
                raise _SOAPFault(fault_code, f"Replay URI not available: {fault_code}")
            resp = etree.SubElement(body, _qn(NS_TRP, "GetReplayUriResponse"))
            _add_text(resp, NS_TRP, "Uri", uri or "")

        elif "GetReplayConfiguration" in action:
            from app.onvif_device.replay_manager import replay_manager as _rm
            timeout_secs = await _rm.get_session_timeout()
            # Format as ISO 8601 duration (PT<N>S or PT<N>M)
            if timeout_secs % 60 == 0:
                iso_dur = f"PT{timeout_secs // 60}M"
            else:
                iso_dur = f"PT{timeout_secs}S"
            resp = etree.SubElement(body, _qn(NS_TRP, "GetReplayConfigurationResponse"))
            config = etree.SubElement(resp, _qn(NS_TRP, "Configuration"))
            _add_text(config, NS_TT, "SessionTimeout", iso_dur)

        elif "SetReplayConfiguration" in action:
            # Parse SessionTimeout from body (ISO 8601 duration PTnS or PTnM)
            req_bytes = await request.body()
            try:
                _root = etree.fromstring(req_bytes)
                _st_el = _root.find(".//{http://www.onvif.org/ver10/schema}SessionTimeout")
                if _st_el is None:
                    _st_el = _root.find(".//SessionTimeout")
                if _st_el is not None and _st_el.text:
                    _dur_text = _st_el.text.strip()
                    import re as _re
                    _m_min = _re.search(r"PT(\d+)M", _dur_text)
                    _m_sec = _re.search(r"PT(\d+)S", _dur_text)
                    if _m_min:
                        _timeout = int(_m_min.group(1)) * 60
                    elif _m_sec:
                        _timeout = int(_m_sec.group(1))
                    else:
                        _timeout = 300
                    # Clamp to 60–3600 seconds
                    _timeout = max(60, min(3600, _timeout))
                    from app.onvif_device.replay_manager import replay_manager as _rm
                    await _rm.set_session_timeout(_timeout)
                    logger.info(f"SetReplayConfiguration: session timeout → {_timeout}s")
            except Exception as _e:
                logger.warning(f"SetReplayConfiguration parse error: {_e}")
            etree.SubElement(body, _qn(NS_TRP, "SetReplayConfigurationResponse"))

        elif "GetServiceCapabilities" in action:
            resp = etree.SubElement(body, _qn(NS_TRP, "GetServiceCapabilitiesResponse"))
            caps = etree.SubElement(resp, _qn(NS_TRP, "Capabilities"))
            caps.set("ReversePlayback", "false")
            caps.set("SessionTimeoutRange", "1 300")

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
            sub_token = uuid.uuid4().hex
            subscription_queues[sub_token] = asyncio.Queue(maxsize=_QUEUE_MAX_SIZE)
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(seconds=_SUBSCRIPTION_TTL_SECONDS)
            subscription_expires[sub_token] = expires_at
            resp = etree.SubElement(body, _qn(NS_TEV, "CreatePullPointSubscriptionResponse"))
            ref = etree.SubElement(resp, _qn(NS_WSNT, "SubscriptionReference"))
            addr = etree.SubElement(ref, _qn(NS_WSA, "Address"))
            addr.text = f"{_base_xaddr(request)}/onvif/event_service"
            # Embed token in ReferenceParameters so PullMessages can identify the queue
            ref_params = etree.SubElement(ref, _qn(NS_WSA, "ReferenceParameters"))
            token_el = etree.SubElement(ref_params, _qn(NS_TEV, "SubscriptionId"))
            token_el.text = sub_token
            _add_text(resp, NS_WSNT, "CurrentTime",
                      now.strftime("%Y-%m-%dT%H:%M:%SZ"))
            _add_text(resp, NS_WSNT, "TerminationTime",
                      expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"))
            logger.debug(f"ONVIF CreatePullPointSubscription: token={sub_token}")

        elif "PullMessages" in action:
            req_bytes = await request.body()
            # Extract subscription token from request or use oldest active queue
            sub_token = self._extract_subscription_token(req_bytes)
            # If token not found or unknown, fall back to first available queue
            if not sub_token or sub_token not in subscription_queues:
                sub_token = next(iter(subscription_queues), None)

            # Parse timeout from request (ISO 8601 duration PT<N>S)
            timeout_str = self._extract_text_field(req_bytes, "Timeout") or "PT5S"
            try:
                if "PT" in timeout_str and "S" in timeout_str:
                    pull_timeout = float(timeout_str.replace("PT", "").replace("S", ""))
                else:
                    pull_timeout = 5.0
            except Exception:
                pull_timeout = 5.0
            pull_timeout = min(pull_timeout, 30.0)  # cap at 30s

            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(seconds=_SUBSCRIPTION_TTL_SECONDS)
            if sub_token and sub_token in subscription_expires:
                expires_at = subscription_expires[sub_token]

            resp = etree.SubElement(body, _qn(NS_TEV, "PullMessagesResponse"))
            _add_text(resp, NS_TEV, "CurrentTime",
                      now.strftime("%Y-%m-%dT%H:%M:%SZ"))
            _add_text(resp, NS_TEV, "TerminationTime",
                      expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"))

            # Drain available events from queue (up to MessageLimit or 50)
            msg_limit_str = self._extract_text_field(req_bytes, "MessageLimit") or "50"
            try:
                msg_limit = int(msg_limit_str)
            except Exception:
                msg_limit = 50

            events: list = []
            q = subscription_queues.get(sub_token) if sub_token else None
            if q is not None:
                # Wait for at least one event (up to pull_timeout), then drain the rest
                try:
                    first = await asyncio.wait_for(q.get(), timeout=pull_timeout)
                    events.append(first)
                except asyncio.TimeoutError:
                    pass
                # Non-blocking drain of remaining items
                while len(events) < msg_limit:
                    try:
                        events.append(q.get_nowait())
                    except asyncio.QueueEmpty:
                        break

            for evt in events:
                self._build_notification_message(resp, evt)

        elif "Renew" in action:
            req_bytes = await request.body()
            sub_token = self._extract_subscription_token(req_bytes)
            now = datetime.now(timezone.utc)
            new_expires = now + timedelta(seconds=_SUBSCRIPTION_TTL_SECONDS)
            if sub_token and sub_token in subscription_expires:
                subscription_expires[sub_token] = new_expires
            resp = etree.SubElement(body, _qn(NS_TEV, "RenewResponse"))
            _add_text(resp, NS_WSNT, "TerminationTime",
                      new_expires.strftime("%Y-%m-%dT%H:%M:%SZ"))
            _add_text(resp, NS_WSNT, "CurrentTime",
                      now.strftime("%Y-%m-%dT%H:%M:%SZ"))

        elif "Unsubscribe" in action:
            req_bytes = await request.body()
            sub_token = self._extract_subscription_token(req_bytes)
            if sub_token:
                subscription_queues.pop(sub_token, None)
                subscription_expires.pop(sub_token, None)
                logger.debug(f"ONVIF Unsubscribe: removed token={sub_token}")
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

    def _extract_subscription_token(self, xml_bytes: bytes) -> Optional[str]:
        """Extract subscription token from SOAP request (ReferenceParameters or header)."""
        try:
            root = etree.fromstring(xml_bytes)
            # Try SubscriptionId in ReferenceParameters
            for tag in (
                "{%s}SubscriptionId" % NS_TEV,
                "SubscriptionId",
            ):
                el = root.find(".//" + tag)
                if el is not None and el.text:
                    return el.text.strip()
        except Exception:
            pass
        return None

    def _build_notification_message(self, parent: etree.Element, evt: dict):
        """Build a WS-Notification NotificationMessage element from an event dict."""
        NS_WSTOP = "http://docs.oasis-open.org/wsn/t-1"
        msg_el = etree.SubElement(parent, _qn(NS_WSNT, "NotificationMessage"))
        topic_el = etree.SubElement(msg_el, _qn(NS_WSNT, "Topic"))
        topic_el.set("Dialect", "http://www.onvif.org/ver10/tev/topicExpression/ConcreteSet")
        topic_el.text = evt.get("topic", "tns1:VideoSource/MotionAlarm")
        prod_ref = etree.SubElement(msg_el, _qn(NS_WSNT, "ProducerReference"))
        addr_el = etree.SubElement(prod_ref, _qn(NS_WSA, "Address"))
        addr_el.text = evt.get("source", "")
        msg_inner = etree.SubElement(msg_el, _qn(NS_WSNT, "Message"))
        tt_msg = etree.SubElement(msg_inner, _qn(NS_TT, "Message"))
        ts = evt.get("timestamp", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        tt_msg.set("UtcTime", ts)
        tt_msg.set("PropertyOperation", "Changed")
        src_el = etree.SubElement(tt_msg, _qn(NS_TT, "Source"))
        si = etree.SubElement(src_el, _qn(NS_TT, "SimpleItem"))
        si.set("Name", "VideoSourceConfigurationToken")
        si.set("Value", evt.get("camera_id", ""))
        data_el = etree.SubElement(tt_msg, _qn(NS_TT, "Data"))
        di = etree.SubElement(data_el, _qn(NS_TT, "SimpleItem"))
        di.set("Name", "IsMotion")
        di.set("Value", str(evt.get("value", "true")).lower())
        # Include any extra metadata as SimpleItems
        for k, v in evt.get("metadata", {}).items():
            if k not in ("onvif_topic", "source"):
                extra = etree.SubElement(data_el, _qn(NS_TT, "SimpleItem"))
                extra.set("Name", str(k))
                extra.set("Value", str(v))

    async def _get_audio_encoder_configs(self, cam: Camera) -> list:
        """Query camera's audio encoder configurations (cached 5 min). Returns list of dicts."""
        from datetime import datetime as _dt
        cache_entry = _audio_encoder_cache.get(cam.id)
        if cache_entry:
            cached_list, cached_at = cache_entry
            if (_dt.now(timezone.utc) - cached_at).total_seconds() < _AUDIO_CACHE_TTL:
                return cached_list

        configs = await self._fetch_audio_encoder_configs(cam)
        _audio_encoder_cache[cam.id] = (configs, datetime.now(timezone.utc))
        return configs

    async def _fetch_audio_encoder_configs(self, cam: Camera) -> list:
        """Attempt to query audio encoder configurations from the camera via ONVIF."""
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

    def _build_aec_element(self, parent: etree.Element, cam_id: str, cfg: dict, ns: str):
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


async def sweep_expired_subscriptions():
    """Background task: remove expired PullPoint subscriptions every 30s."""
    while True:
        try:
            await asyncio.sleep(30)
            now = datetime.now(timezone.utc)
            expired = [
                token for token, exp in list(subscription_expires.items())
                if exp <= now
            ]
            for token in expired:
                subscription_queues.pop(token, None)
                subscription_expires.pop(token, None)
                logger.debug(f"ONVIF: swept expired subscription token={token}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug(f"sweep_expired_subscriptions error: {e}")


# ── NVR event injection helper ───────────────────────────────────────────────
# Called by linkage_engine, motion_service, and other subsystems to push
# NVR-internal events into active ONVIF PullPoint subscription queues.

async def inject_nvr_event(
    camera_id: Optional[str] = None,
    event_type: str = "motion_detected",
    severity: str = "alarm",
    title: str = "",
    metadata: Optional[Dict[str, Any]] = None,
):
    """Push an NVR-internal event into all active ONVIF PullPoint queues."""
    if not subscription_queues:
        return
    topic_map = {
        "motion_detected": "tns1:VideoSource/MotionAlarm",
        "camera_tamper":   "tns1:VideoSource/ImageTooBlurry",
        "video_loss":      "tns1:VideoSource/ConnectionFailed",
        "line_crossing":   "tns1:RuleEngine/LineDetector/Crossed",
        "zone_intrusion":  "tns1:RuleEngine/FieldDetector/ObjectInside",
        "audio_alarm":     "tns1:AudioAnalytics/Audio/DetectedSound",
        "system_error":    "tns1:Device/Trigger/DigitalInput",
    }
    topic = topic_map.get(event_type, "tns1:VideoSource/MotionAlarm")
    evt = {
        "topic": topic,
        "camera_id": camera_id or "",
        "source": f"camera:{camera_id}" if camera_id else "nvr:system",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "value": "true",
        "metadata": metadata or {"nvr_event_type": event_type, "severity": severity},
    }
    for q in list(subscription_queues.values()):
        try:
            q.put_nowait(evt)
        except Exception:
            pass  # Queue full — drop event


# Module singleton
onvif_device_service = ONVIFDeviceService()
