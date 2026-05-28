# =============================================================================
# Shared constants and XML helpers used across all ONVIF handler modules.
# Handlers import from here — nothing from service.py directly.
# =============================================================================

import logging
import os
from typing import Optional, Any

from lxml import etree
from fastapi import Request

from app.config import settings

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
        "timg": NS_TIMG,
        "wsnt": NS_WSNT,
        "wsa":  NS_WSA,
    })
    return env


def _body(envelope: etree.Element) -> etree.Element:
    return etree.SubElement(envelope, _qn(NS_SOAP, "Body"))


def _add_text(parent: etree.Element, ns: str, tag: str, text: Any) -> etree.Element:
    el = etree.SubElement(parent, _qn(ns, tag))
    el.text = str(text)
    return el


def _get_external_host(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    if fwd:
        return fwd
    return request.url.hostname or "localhost"


def _base_xaddr(request: Request) -> str:
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = _get_external_host(request)
    return f"{scheme}://{host}"


def _extract_profile_token(xml_bytes: bytes) -> Optional[str]:
    try:
        root = etree.fromstring((xml_bytes or b'').lstrip() if isinstance(xml_bytes, (bytes, bytearray)) else xml_bytes)
        for tag in ("ProfileToken", "{%s}ProfileToken" % NS_TRT, "{%s}ProfileToken" % NS_TR2):
            el = root.find(".//" + tag)
            if el is not None:
                return el.text
    except Exception:
        pass
    return None


def _profile_token_to_camera_id(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    if token.startswith("profile_"):
        return token[8:]
    return token


def _extract_text_field(xml_bytes: bytes, field: str) -> Optional[str]:
    try:
        root = etree.fromstring((xml_bytes or b'').lstrip() if isinstance(xml_bytes, (bytes, bytearray)) else xml_bytes)
        el = root.find(".//" + field)
        if el is None:
            el = root.find(".//{*}" + field)
        if el is not None:
            return el.text
    except Exception:
        pass
    return None


def _extract_recording_token(xml_bytes: bytes) -> Optional[str]:
    try:
        root = etree.fromstring((xml_bytes or b'').lstrip() if isinstance(xml_bytes, (bytes, bytearray)) else xml_bytes)
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


def _extract_subscription_token(xml_bytes: bytes) -> Optional[str]:
    try:
        root = etree.fromstring((xml_bytes or b'').lstrip() if isinstance(xml_bytes, (bytes, bytearray)) else xml_bytes)
        for tag in ("{%s}SubscriptionId" % NS_TEV, "SubscriptionId"):
            el = root.find(".//" + tag)
            if el is not None and el.text:
                return el.text.strip()
    except Exception:
        pass
    return None


def _parse_iso_duration(dur: str, default: int = 300) -> int:
    import re
    try:
        m = re.search(r"PT(\d+(?:\.\d+)?)H", dur)
        if m:
            return int(float(m.group(1)) * 3600)
        m = re.search(r"PT(\d+(?:\.\d+)?)M", dur)
        if m:
            return int(float(m.group(1)) * 60)
        m = re.search(r"PT(\d+(?:\.\d+)?)S", dur)
        if m:
            return int(float(m.group(1)))
    except Exception:
        pass
    return default
