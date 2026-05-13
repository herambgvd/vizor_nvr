# =============================================================================
# ONVIF Device Server — exposes the NVR as an ONVIF-compliant device
# =============================================================================
# Implements:
#   Device, Media, Media2, Recording, Search, Replay, Event
# Profiles: S (streaming) + G (recording)
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
NS_SOAP = "http://www.w3.org/2003/05/soap-envelope"
NS_WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
NS_WSU = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
NS_WSA = "http://www.w3.org/2005/08/addressing"
NS_TDS = "http://www.onvif.org/ver10/device/wsdl"
NS_TRT = "http://www.onvif.org/ver10/media/wsdl"
NS_TR2 = "http://www.onvif.org/ver20/media/wsdl"
NS_TRC = "http://www.onvif.org/ver10/recording/wsdl"
NS_TSE = "http://www.onvif.org/ver10/search/wsdl"
NS_TRP = "http://www.onvif.org/ver10/replay/wsdl"
NS_TEV = "http://www.onvif.org/ver10/events/wsdl"
NS_TT = "http://www.onvif.org/ver10/schema"
NS_WSNT = "http://docs.oasis-open.org/wsn/b-2"
NS_WSRF = "http://docs.oasis-open.org/wsrf/bf-2"

SOAP_ENV = "{%s}" % NS_SOAP
WSA_ENV = "{%s}" % NS_WSA
TDS_ENV = "{%s}" % NS_TDS
TRT_ENV = "{%s}" % NS_TRT
TR2_ENV = "{%s}" % NS_TR2
TRC_ENV = "{%s}" % NS_TRC
TSE_ENV = "{%s}" % NS_TSE
TRP_ENV = "{%s}" % NS_TRP
TEV_ENV = "{%s}" % NS_TEV
TT_ENV = "{%s}" % NS_TT
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
        "tt": NS_TT,
        "tds": NS_TDS,
        "trt": NS_TRT,
        "tr2": NS_TR2,
        "trc": NS_TRC,
        "tse": NS_TSE,
        "trp": NS_TRP,
        "tev": NS_TEV,
        "wsa": NS_WSA,
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
    nonce_el = ut.find("{%s}Nonce" % NS_WSSE)
    created_el = ut.find("{%s}Created" % NS_WSU)

    if username_el is None or password_el is None:
        return False

    username = username_el.text or ""
    password_type = password_el.get("Type", "")
    password_value = password_el.text or ""

    if username != ONVIF_DEVICE_USER:
        return False

    if "PasswordDigest" in password_type:
        if nonce_el is None or created_el is None:
            return False
        nonce = base64.b64decode(nonce_el.text or "")
        created = (created_el.text or "").encode("utf-8")
        secret = ONVIF_DEVICE_PASS.encode("utf-8")
        digest = base64.b64encode(
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
    db: AsyncSession, camera_id: str, start: Optional[datetime] = None, end: Optional[datetime] = None,
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
                if tag.startswith("{"):
                    return tag
                return tag
        except Exception:
            pass
        return ""

    def _fault(self, code: str, text: str) -> Response:
        env = _soap_envelope()
        body = _body(env)
        fault = etree.SubElement(body, _qn(NS_SOAP, "Fault"))
        _add_text(fault, NS_SOAP, "Code", code)
        _add_text(fault, NS_SOAP, "Reason", text)
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

        elif "GetSystemDateAndTime" in action:
            resp = etree.SubElement(body, _qn(NS_TDS, "GetSystemDateAndTimeResponse"))
            await self._build_datetime(resp)

        elif "GetNetworkInterfaces" in action:
            resp = etree.SubElement(body, _qn(NS_TDS, "GetNetworkInterfacesResponse"))
            # Return minimal info
            iface = etree.SubElement(resp, _qn(NS_TDS, "NetworkInterfaces"))
            _add_text(iface, NS_TT, "token", "eth0")
            enabled = etree.SubElement(iface, _qn(NS_TT, "Enabled"))
            enabled.text = "true"
            info = etree.SubElement(iface, _qn(NS_TT, "Info"))
            _add_text(info, NS_TT, "Name", "eth0")

        elif "GetScopes" in action:
            resp = etree.SubElement(body, _qn(NS_TDS, "GetScopesResponse"))
            for scope_def in [
                ("Fixed", "onvif://www.onvif.org/type/video_server"),
                ("Fixed", "onvif://www.onvif.org/type/network_video_transmitter"),
                ("Configurable", f"onvif://www.onvif.org/name/GVD-NVR"),
                ("Fixed", "onvif://www.onvif.org/location/"),
            ]:
                scope = etree.SubElement(resp, _qn(NS_TDS, "Scopes"))
                _add_text(scope, NS_TT, "ScopeDef", scope_def[0])
                _add_text(scope, NS_TT, "ScopeItem", scope_def[1])

        elif "GetHostname" in action:
            resp = etree.SubElement(body, _qn(NS_TDS, "GetHostnameResponse"))
            _add_text(resp, NS_TDS, "Hostname", _get_external_host(request))

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
        etree.SubElement(net, _qn(NS_TT, "IPFilter"))
        etree.SubElement(dev, _qn(NS_TT, "System"))
        etree.SubElement(dev, _qn(NS_TT, "Security"))

        # Media caps (Profile S)
        media = etree.SubElement(parent, _qn(NS_TT, "Media"))
        _add_text(media, NS_TT, "XAddr", f"{base}/onvif/media_service")
        etree.SubElement(media, _qn(NS_TT, "StreamingCapabilities"))

        # Event caps
        evt = etree.SubElement(parent, _qn(NS_TT, "Events"))
        _add_text(evt, NS_TT, "XAddr", f"{base}/onvif/event_service")
        _add_text(evt, NS_TT, "WSSubscriptionPolicySupport", "false")
        _add_text(evt, NS_TT, "WSPullPointSupport", "true")
        _add_text(evt, NS_TT, "WSPausableSubscriptionManagerInterfaceSupport", "false")

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
            (NS_TDS, f"{base}/onvif/device_service", 1, 0),
            (NS_TRT, f"{base}/onvif/media_service", 1, 0),
            (NS_TR2, f"{base}/onvif/media2_service", 2, 0),
            (NS_TRC, f"{base}/onvif/recording_service", 1, 0),
            (NS_TSE, f"{base}/onvif/search_service", 1, 0),
            (NS_TRP, f"{base}/onvif/replay_service", 1, 0),
            (NS_TEV, f"{base}/onvif/event_service", 1, 0),
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
        resp = etree.SubElement(parent, _qn(NS_TDS, "SystemDateAndTime"))
        _add_text(resp, NS_TT, "DateTimeType", "NTP")
        _add_text(resp, NS_TT, "DaylightSavings", "false")
        tz = etree.SubElement(resp, _qn(NS_TT, "TimeZone"))
        _add_text(tz, NS_TT, "TZ", "UTC+0")
        utc = etree.SubElement(resp, _qn(NS_TT, "UTCDateTime"))
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

        elif "GetVideoSources" in action:
            resp = etree.SubElement(body, _qn(NS_TRT, "GetVideoSourcesResponse"))
            cameras = await _get_cameras(db)
            for cam in cameras:
                vs = etree.SubElement(resp, _qn(NS_TT, "VideoSources"))
                _add_text(vs, NS_TT, "token", f"vs_{cam.id}")
                res = etree.SubElement(vs, _qn(NS_TT, "Resolution"))
                w, h = self._parse_resolution(cam.resolution)
                _add_text(res, NS_TT, "Width", w)
                _add_text(res, NS_TT, "Height", h)
                _add_text(vs, NS_TT, "Framerate", cam.fps or 25)

        elif "GetVideoEncoderConfigurations" in action:
            resp = etree.SubElement(body, _qn(NS_TRT, "GetVideoEncoderConfigurationsResponse"))
            cameras = await _get_cameras(db)
            for cam in cameras:
                cfg = etree.SubElement(resp, _qn(NS_TT, "Configurations"))
                _add_text(cfg, NS_TT, "token", f"vec_{cam.id}")
                _add_text(cfg, NS_TT, "Name", f"Encoder {cam.name}")
                _add_text(cfg, NS_TT, "Encoding", (cam.codec or "H264").upper())
                res = etree.SubElement(cfg, _qn(NS_TT, "Resolution"))
                w, h = self._parse_resolution(cam.resolution)
                _add_text(res, NS_TT, "Width", w)
                _add_text(res, NS_TT, "Height", h)
                rate = etree.SubElement(cfg, _qn(NS_TT, "RateControl"))
                _add_text(rate, NS_TT, "FrameRateLimit", cam.fps or 25)
                _add_text(rate, NS_TT, "BitrateLimit", self._parse_bitrate(cam.bitrate))

        else:
            tag = action.split("}")[-1] if "}" in action else action
            if tag:
                etree.SubElement(body, _qn(NS_TRT, tag + "Response"))

    def _build_media_profile(self, parent: etree.Element, cam: Camera):
        prof = etree.SubElement(parent, _qn(NS_TT, "Profiles"))
        _add_text(prof, NS_TT, "token", f"profile_{cam.id}")
        _add_text(prof, NS_TT, "Name", cam.name)
        _add_text(prof, NS_TT, "fixed", "false")

        vsc = etree.SubElement(prof, _qn(NS_TT, "VideoSourceConfiguration"))
        _add_text(vsc, NS_TT, "token", f"vsc_{cam.id}")
        _add_text(vsc, NS_TT, "Name", f"VideoSource {cam.name}")
        _add_text(vsc, NS_TT, "SourceToken", f"vs_{cam.id}")
        bounds = etree.SubElement(vsc, _qn(NS_TT, "Bounds"))
        w, h = self._parse_resolution(cam.resolution)
        bounds.set("x", "0")
        bounds.set("y", "0")
        bounds.set("width", str(w))
        bounds.set("height", str(h))

        vec = etree.SubElement(prof, _qn(NS_TT, "VideoEncoderConfiguration"))
        _add_text(vec, NS_TT, "token", f"vec_{cam.id}")
        _add_text(vec, NS_TT, "Name", f"Encoder {cam.name}")
        _add_text(vec, NS_TT, "Encoding", (cam.codec or "H264").upper())
        res = etree.SubElement(vec, _qn(NS_TT, "Resolution"))
        _add_text(res, NS_TT, "Width", w)
        _add_text(res, NS_TT, "Height", h)
        rate = etree.SubElement(vec, _qn(NS_TT, "RateControl"))
        _add_text(rate, NS_TT, "FrameRateLimit", cam.fps or 25)
        _add_text(rate, NS_TT, "BitrateLimit", self._parse_bitrate(cam.bitrate))

    # =====================================================================
    # Media2 Service
    # =====================================================================

    async def _handle_media2(self, action: str, body: etree.Element, request: Request, db: AsyncSession):
        if "GetProfiles" in action:
            resp = etree.SubElement(body, _qn(NS_TR2, "GetProfilesResponse"))
            cameras = await _get_cameras(db)
            for cam in cameras:
                prof = etree.SubElement(resp, _qn(NS_TR2, "Profiles"))
                _add_text(prof, NS_TR2, "token", f"profile_{cam.id}")
                _add_text(prof, NS_TR2, "Name", cam.name)
                _add_text(prof, NS_TR2, "fixed", "false")
                # Media2 uses Configurations element differently
                configs = etree.SubElement(prof, _qn(NS_TR2, "Configurations"))
                vsc = etree.SubElement(configs, _qn(NS_TT, "VideoSource"))
                _add_text(vsc, NS_TT, "token", f"vs_{cam.id}")
                _add_text(vsc, NS_TT, "Name", cam.name)
                res = etree.SubElement(vsc, _qn(NS_TT, "Resolution"))
                w, h = self._parse_resolution(cam.resolution)
                _add_text(res, NS_TT, "Width", w)
                _add_text(res, NS_TT, "Height", h)

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

        else:
            tag = action.split("}")[-1] if "}" in action else action
            if tag:
                etree.SubElement(body, _qn(NS_TR2, tag + "Response"))

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
                # Indicate continuous recording if active
                _add_text(track, NS_TT, "DataFrom", "1970-01-01T00:00:00Z")
                _add_text(track, NS_TT, "DataTo", datetime.now(timezone.utc).isoformat())

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
            token = self._extract_search_token(req_bytes)
            rec_token = self._extract_recording_token(req_bytes)
            start, end = self._extract_time_range(req_bytes)

            cameras = await _get_cameras(db)
            result_list = etree.SubElement(resp, _qn(NS_TSE, "ResultList"))
            for cam in cameras:
                if rec_token and f"rec_{cam.id}" != rec_token:
                    continue
                recordings = await _get_recordings_for_camera(db, cam.id, start, end)
                for rec in recordings:
                    item = etree.SubElement(result_list, _qn(NS_TSE, "RecordingInformation"))
                    _add_text(item, NS_TT, "RecordingToken", f"rec_{cam.id}")
                    _add_text(item, NS_TT, "TrackToken", f"track_{cam.id}")
                    _add_text(item, NS_TT, "StartTime", rec.start_time.isoformat() if rec.start_time else "")
                    _add_text(item, NS_TT, "EndTime", rec.end_time.isoformat() if rec.end_time else "")
                    _add_text(item, NS_TT, "Content", "Video")

        elif "EndSearch" in action:
            resp = etree.SubElement(body, _qn(NS_TSE, "EndSearchResponse"))
            # No-op
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

        else:
            tag = action.split("}")[-1] if "}" in action else action
            if tag:
                etree.SubElement(body, _qn(NS_TRP, tag + "Response"))

    # =====================================================================
    # Event Service
    # =====================================================================

    async def _handle_event(self, action: str, body: etree.Element, request: Request, db: AsyncSession):
        if "GetEventProperties" in action:
            resp = etree.SubElement(body, _qn(NS_TEV, "GetEventPropertiesResponse"))
            _add_text(resp, NS_TEV, "FixedTopicSet", "true")
            topic_set = etree.SubElement(resp, _qn(NS_TEV, "TopicSet"))
            topic = etree.SubElement(topic_set, _qn(NS_WSNT, "Topic"))
            topic.set("Dialect", "http://www.onvif.org/ver10/tev/topicExpression/ConcreteSet")
            topic.set("Name", "tns1:Device/Trigger/DigitalInput")
            _add_text(resp, NS_TEV, "TopicExpressionDialect", "http://www.onvif.org/ver10/tev/topicExpression/ConcreteSet")
            _add_text(resp, NS_TEV, "MessageContentFilterDialect", "http://www.onvif.org/ver10/tev/messageContentFilter/ItemFilter")
            _add_text(resp, NS_TEV, "MessageContentSchemaLocation", "")

        elif "CreatePullPointSubscription" in action:
            resp = etree.SubElement(body, _qn(NS_TEV, "CreatePullPointSubscriptionResponse"))
            ref = etree.SubElement(resp, _qn(NS_WSNT, "SubscriptionReference"))
            addr = etree.SubElement(ref, _qn(NS_WSA, "Address"))
            addr.text = f"{_base_xaddr(request)}/onvif/event_service"
            _add_text(resp, NS_WSNT, "CurrentTime", datetime.now(timezone.utc).isoformat())
            _add_text(resp, NS_WSNT, "TerminationTime", (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat())

        elif "PullMessages" in action:
            resp = etree.SubElement(body, _qn(NS_TEV, "PullMessagesResponse"))
            _add_text(resp, NS_TEV, "CurrentTime", datetime.now(timezone.utc).isoformat())
            _add_text(resp, NS_TEV, "TerminationTime", (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat())
            # Return empty message set for now
            # VMS will poll periodically; we can inject real events later

        elif "Renew" in action:
            resp = etree.SubElement(body, _qn(NS_TEV, "RenewResponse"))
            _add_text(resp, NS_WSNT, "TerminationTime", (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat())
            _add_text(resp, NS_WSNT, "CurrentTime", datetime.now(timezone.utc).isoformat())

        elif "Unsubscribe" in action:
            resp = etree.SubElement(body, _qn(NS_TEV, "UnsubscribeResponse"))

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
        # Prefer go2rtc RTSP output so VMS connects to the NVR's restream endpoint
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
            for tag in ("RecordingToken", "{%s}RecordingToken" % NS_TRC, "{%s}RecordingToken" % NS_TSE, "{%s}RecordingToken" % NS_TRP):
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
