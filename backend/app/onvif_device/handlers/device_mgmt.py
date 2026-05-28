# =============================================================================
# ONVIF Device Management Service handler
# Covers: GetSystemDateAndTime, GetDeviceInformation, GetCapabilities,
#         GetServices, GetServiceCapabilities, GetScopes, GetNetworkInterfaces,
#         GetHostname, GetUsers, CreateUsers, SetUser, GetSystemUris,
#         SystemReboot, SetSystemFactoryDefault
# =============================================================================

import logging
from datetime import datetime, timezone
from typing import Any

from lxml import etree
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from ._common import (
    NS_TDS, NS_TRT, NS_TR2, NS_TRC, NS_TSE, NS_TRP, NS_TEV, NS_TPTZ, NS_TIMG,
    NS_TT, NS_WSNT, NS_WSA,
    _qn, _add_text, _base_xaddr, _get_external_host, ONVIF_DEVICE_USER,
)

logger = logging.getLogger(__name__)


async def dispatch(action: str, body: etree.Element, request: Request, db: AsyncSession, **ctx):
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
        await _build_capabilities(caps, request)

    elif "GetServices" in action:
        resp = etree.SubElement(body, _qn(NS_TDS, "GetServicesResponse"))
        await _build_services(resp, request)

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
        await _build_datetime(resp)

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
        _add_text(resp, NS_TDS, "SystemLogUris", "")

    elif "SystemReboot" in action:
        resp = etree.SubElement(body, _qn(NS_TDS, "SystemRebootResponse"))
        _add_text(resp, NS_TDS, "Message", "Reboot not supported on this NVR")

    elif "SetSystemFactoryDefault" in action:
        etree.SubElement(body, _qn(NS_TDS, "SetSystemFactoryDefaultResponse"))

    else:
        tag = action.split("}")[-1] if "}" in action else action
        if tag:
            etree.SubElement(body, _qn(NS_TDS, tag + "Response"))


async def _build_capabilities(parent: etree.Element, request: Request):
    base = _base_xaddr(request)
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

    media = etree.SubElement(parent, _qn(NS_TT, "Media"))
    _add_text(media, NS_TT, "XAddr", f"{base}/onvif/media_service")
    sc = etree.SubElement(media, _qn(NS_TT, "StreamingCapabilities"))
    sc.set("RTPMulticast", "false")
    sc.set("RTP_TCP", "true")
    sc.set("RTP_RTSP_TCP", "true")

    evt = etree.SubElement(parent, _qn(NS_TT, "Events"))
    _add_text(evt, NS_TT, "XAddr", f"{base}/onvif/event_service")
    _add_text(evt, NS_TT, "WSSubscriptionPolicySupport", "false")
    _add_text(evt, NS_TT, "WSPullPointSupport", "true")
    _add_text(evt, NS_TT, "WSPausableSubscriptionManagerInterfaceSupport", "false")

    ptz = etree.SubElement(parent, _qn(NS_TT, "PTZ"))
    _add_text(ptz, NS_TT, "XAddr", f"{base}/onvif/ptz_service")

    img = etree.SubElement(parent, _qn(NS_TT, "Imaging"))
    _add_text(img, NS_TT, "XAddr", f"{base}/onvif/imaging_service")

    ext = etree.SubElement(parent, _qn(NS_TT, "Extension"))

    media2 = etree.SubElement(ext, _qn(NS_TT, "Media"))
    _add_text(media2, NS_TT, "XAddr", f"{base}/onvif/media2_service")

    rec = etree.SubElement(ext, _qn(NS_TT, "Recording"))
    _add_text(rec, NS_TT, "XAddr", f"{base}/onvif/recording_service")

    search = etree.SubElement(ext, _qn(NS_TT, "Search"))
    _add_text(search, NS_TT, "XAddr", f"{base}/onvif/search_service")

    replay = etree.SubElement(ext, _qn(NS_TT, "Replay"))
    _add_text(replay, NS_TT, "XAddr", f"{base}/onvif/replay_service")


async def _build_services(parent: etree.Element, request: Request):
    base = _base_xaddr(request)
    from ._common import NS_TDS as _TDS
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


async def _build_datetime(parent: etree.Element):
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
