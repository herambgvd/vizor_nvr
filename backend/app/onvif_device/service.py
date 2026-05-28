# =============================================================================
# ONVIF Device Server — thin dispatcher
# =============================================================================
# Parses the inbound SOAP envelope, authenticates the WS-UsernameToken, and
# routes to the correct per-ONVIF-service handler module.
#
# Handler modules live under app.onvif_device.handlers.*
# Each exposes:   async def dispatch(action, body, request, db, **ctx)
# =============================================================================

import base64
import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from lxml import etree
from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session_maker
from app.cameras.models import Camera
from app.recordings.models import Recording

from app.onvif_device.handlers._common import (
    NS_SOAP, NS_WSSE, NS_WSU, NS_TDS,
    _qn, _soap_envelope, _body,
    ONVIF_DEVICE_USER, ONVIF_DEVICE_PASS,
)
from app.onvif_device.handlers import (
    device_mgmt, media1, media2, ptz, imaging, recording, search, events
)

logger = logging.getLogger(__name__)


# ── WS-UsernameToken auth ────────────────────────────────────────────────────

def _verify_username_token(xml_bytes: bytes) -> bool:
    try:
        # Tolerate clients that emit leading whitespace / BOM before
        # the <?xml ...?> declaration. Strict lxml rejects that; ONVIF
        # spec is silent on it but many real-world clients (and our own
        # conformance script via textwrap.dedent) produce it.
        if isinstance(xml_bytes, bytes):
            xml_bytes = xml_bytes.lstrip()
        root = etree.fromstring((xml_bytes or b'').lstrip() if isinstance(xml_bytes, (bytes, bytearray)) else xml_bytes)
        header = root.find(_qn(NS_SOAP, "Header"))
        if header is None:
            return True  # No security header → allow (dev mode)
        security = header.find(_qn(NS_WSSE, "Security"))
        if security is None:
            return True
        ut = security.find(_qn(NS_WSSE, "UsernameToken"))
        if ut is None:
            return True
        username_el = ut.find(_qn(NS_WSSE, "Username"))
        password_el = ut.find(_qn(NS_WSSE, "Password"))
        nonce_el    = ut.find(_qn(NS_WSSE, "Nonce"))
        created_el  = ut.find(_qn(NS_WSU, "Created"))

        if username_el is None or password_el is None:
            return False

        username = username_el.text or ""
        pwd_text = password_el.text or ""
        pwd_type = password_el.get("Type", "")

        if username != ONVIF_DEVICE_USER:
            return False

        if "PasswordDigest" in pwd_type:
            if nonce_el is None or created_el is None:
                return False
            nonce_b64 = nonce_el.text or ""
            created   = created_el.text or ""
            nonce_bytes = base64.b64decode(nonce_b64)
            expected = base64.b64encode(
                hashlib.sha1(nonce_bytes + created.encode() + ONVIF_DEVICE_PASS.encode()).digest()
            ).decode()
            return pwd_text == expected
        else:
            return pwd_text == ONVIF_DEVICE_PASS
    except Exception as e:
        logger.debug(f"UsernameToken verify error: {e}")
        return False


# ── DB helpers ───────────────────────────────────────────────────────────────

async def _get_cameras(db: AsyncSession) -> List[Camera]:
    result = await db.execute(select(Camera).where(Camera.is_enabled == True))
    return result.scalars().all()


async def _get_camera_by_id(db: AsyncSession, camera_id: str) -> Optional[Camera]:
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    return result.scalar_one_or_none()


async def _get_recordings_for_camera(
    db: AsyncSession,
    camera_id: str,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
) -> List[Recording]:
    q = select(Recording).where(Recording.camera_id == camera_id)
    if start:
        q = q.where(Recording.start_time >= start)
    if end:
        q = q.where(Recording.end_time <= end)
    q = q.order_by(Recording.start_time.desc()).limit(100)
    result = await db.execute(q)
    return result.scalars().all()


# ── SOAP fault helper ────────────────────────────────────────────────────────

class _SOAPFault(Exception):
    def __init__(self, code: str, text: str):
        self.code = code
        self.text = text


def _make_fault_response(code: str, text: str) -> Response:
    env = _soap_envelope()
    bd = _body(env)
    fault = etree.SubElement(bd, _qn(NS_SOAP, "Fault"))
    code_el = etree.SubElement(fault, _qn(NS_SOAP, "Code"))
    val = etree.SubElement(code_el, _qn(NS_SOAP, "Value"))
    val.text = code
    reason_el = etree.SubElement(fault, _qn(NS_SOAP, "Reason"))
    text_el = etree.SubElement(reason_el, _qn(NS_SOAP, "Text"))
    text_el.set("{http://www.w3.org/XML/1998/namespace}lang", "en")
    text_el.text = text
    xml_str = etree.tostring(env, pretty_print=True, xml_declaration=True, encoding="UTF-8")
    return Response(content=xml_str, media_type="application/soap+xml; charset=utf-8", status_code=500)


# ── Main service class ───────────────────────────────────────────────────────

class ONVIFDeviceService:
    """Thin dispatcher — routes SOAP requests to per-service handler modules."""

    def __init__(self):
        # Search token registry (owned here, passed to search handler)
        self._search_tokens: Dict[str, Dict[str, Any]] = {}

    async def handle(self, service_path: str, request: Request) -> Response:
        body_bytes = await request.body()
        action = self._extract_action(body_bytes, request)
        logger.debug(f"ONVIF {service_path} action={action}")

        if not _verify_username_token(body_bytes):
            return _make_fault_response("ter:NotAuthorized", "Authentication failed")

        envelope = _soap_envelope()
        resp_body = _body(envelope)

        # Shared context injected into each handler
        ctx = dict(
            soap_fault_cls=_SOAPFault,
            get_cameras=_get_cameras,
            get_camera_by_id=_get_camera_by_id,
            get_recordings_for_camera=_get_recordings_for_camera,
            search_tokens=self._search_tokens,
        )

        try:
            async with async_session_maker() as db:
                if service_path == "/onvif/device_service":
                    await device_mgmt.dispatch(action, resp_body, request, db, **ctx)
                elif service_path == "/onvif/media_service":
                    await media1.dispatch(action, resp_body, request, db, **ctx)
                elif service_path == "/onvif/media2_service":
                    await media2.dispatch(action, resp_body, request, db, **ctx)
                elif service_path == "/onvif/ptz_service":
                    await ptz.dispatch(action, resp_body, request, db, **ctx)
                elif service_path == "/onvif/imaging_service":
                    await imaging.dispatch(action, resp_body, request, db, **ctx)
                elif service_path == "/onvif/recording_service":
                    await recording.dispatch(action, resp_body, request, db, **ctx)
                elif service_path == "/onvif/search_service":
                    await search.dispatch(action, resp_body, request, db, **ctx)
                elif service_path == "/onvif/replay_service":
                    await self._handle_replay(action, resp_body, request, db)
                elif service_path == "/onvif/event_service":
                    await events.dispatch(action, resp_body, request, db, **ctx)
                else:
                    return _make_fault_response("ter:ActionNotSupported", f"Unknown service {service_path}")
        except _SOAPFault as sf:
            return _make_fault_response(sf.code, sf.text)
        except Exception as e:
            logger.exception(f"ONVIF handler error for {action}: {e}")
            return _make_fault_response("ter:Receiver", "Internal error")

        xml_str = etree.tostring(envelope, pretty_print=True, xml_declaration=True, encoding="UTF-8")
        return Response(content=xml_str, media_type="application/soap+xml; charset=utf-8")

    def _extract_action(self, body_bytes: bytes, request: Request) -> str:
        action = request.headers.get("soapaction", "").strip('"')
        if action:
            return action
        try:
            root = etree.fromstring((body_bytes or b"").lstrip())
            body = root.find(_qn(NS_SOAP, "Body"))
            if body is not None and len(body) > 0:
                return body[0].tag
        except Exception:
            pass
        return ""

    # ── Replay service is already split into replay.py / replay_manager.py ──

    async def _handle_replay(self, action: str, body: etree.Element, request: Request, db: AsyncSession):
        from app.onvif_device.handlers._common import NS_TRP, _qn as _q, _add_text as _at
        _NS_TT = "http://www.onvif.org/ver10/schema"

        if "GetReplayUri" in action:
            from app.onvif_device.replay import handle_get_replay_uri
            req_bytes = await request.body()
            from app.onvif_device.handlers._common import _extract_recording_token
            rec_token = _extract_recording_token(req_bytes)
            uri, fault_code = await handle_get_replay_uri(req_bytes, rec_token, request, db)
            if fault_code:
                raise _SOAPFault(fault_code, f"Replay URI not available: {fault_code}")
            resp = etree.SubElement(body, _q(NS_TRP, "GetReplayUriResponse"))
            _at(resp, NS_TRP, "Uri", uri or "")

        elif "GetReplayConfiguration" in action:
            from app.onvif_device.replay_manager import replay_manager as _rm
            timeout_secs = await _rm.get_session_timeout()
            if timeout_secs % 60 == 0:
                iso_dur = f"PT{timeout_secs // 60}M"
            else:
                iso_dur = f"PT{timeout_secs}S"
            resp = etree.SubElement(body, _q(NS_TRP, "GetReplayConfigurationResponse"))
            config = etree.SubElement(resp, _q(NS_TRP, "Configuration"))
            _at(config, _NS_TT, "SessionTimeout", iso_dur)

        elif "SetReplayConfiguration" in action:
            req_bytes = await request.body()
            try:
                _root = etree.fromstring((req_bytes or b"").lstrip())
                _st_el = _root.find(".//{http://www.onvif.org/ver10/schema}SessionTimeout")
                if _st_el is None:
                    _st_el = _root.find(".//SessionTimeout")
                if _st_el is not None and _st_el.text:
                    import re as _re
                    _dur_text = _st_el.text.strip()
                    _m_min = _re.search(r"PT(\d+)M", _dur_text)
                    _m_sec = _re.search(r"PT(\d+)S", _dur_text)
                    if _m_min:
                        _timeout = int(_m_min.group(1)) * 60
                    elif _m_sec:
                        _timeout = int(_m_sec.group(1))
                    else:
                        _timeout = 300
                    _timeout = max(60, min(3600, _timeout))
                    from app.onvif_device.replay_manager import replay_manager as _rm
                    await _rm.set_session_timeout(_timeout)
                    logger.info(f"SetReplayConfiguration: session timeout → {_timeout}s")
            except Exception as _e:
                logger.warning(f"SetReplayConfiguration parse error: {_e}")
            etree.SubElement(body, _q(NS_TRP, "SetReplayConfigurationResponse"))

        elif "GetServiceCapabilities" in action:
            resp = etree.SubElement(body, _q(NS_TRP, "GetServiceCapabilitiesResponse"))
            caps = etree.SubElement(resp, _q(NS_TRP, "Capabilities"))
            caps.set("ReversePlayback", "false")
            caps.set("SessionTimeoutRange", "1 300")

        else:
            tag = action.split("}")[-1] if "}" in action else action
            if tag:
                etree.SubElement(body, _q(NS_TRP, tag + "Response"))


# ── Background tasks (re-exported from events handler for main.py compat) ────
sweep_expired_subscriptions = events.sweep_expired_subscriptions
push_delivery_worker        = events.push_delivery_worker

# ── NVR event injection (re-exported for callers outside this module) ─────────
inject_nvr_event = events.inject_nvr_event

# ── Legacy re-exports so existing imports still work ─────────────────────────
subscription_queues  = events.subscription_queues
subscription_expires = events.subscription_expires
push_subscriptions   = events.push_subscriptions

# Module singleton
onvif_device_service = ONVIFDeviceService()
