# =============================================================================
# WhatsApp Service — Twilio WhatsApp Business API integration
# =============================================================================
# Configuration (env vars take precedence over DB settings):
#   TWILIO_ACCOUNT_SID    — Twilio account SID (starts with "AC")
#   TWILIO_AUTH_TOKEN     — Twilio auth token
#   TWILIO_WHATSAPP_FROM  — WhatsApp-approved sender number, e.g. +14155551234
#   WA_RATE_LIMIT_PER_HOUR — Max messages per recipient per hour (default 5)
#
# WHATSAPP ONBOARDING
# ───────────────────
# The "From" number must be a Twilio-approved WhatsApp Business number.
# 1. Go to: https://console.twilio.com/us1/develop/sms/whatsapp/learn
# 2. Follow the sandbox setup or apply for a dedicated business number.
# 3. Set TWILIO_WHATSAPP_FROM to the approved number (E.164, no "whatsapp:"
#    prefix — the service adds it automatically).
#
# Note: WhatsApp prohibits unsolicited messages; recipients must opt in by
# messaging the business number first (or via template messages after approval).
#
# RATE LIMITING + ERROR CLASSIFICATION
# ─────────────────────────────────────
# Same behaviour as SMSService: per-recipient sliding 1-hour window.
# Twilio 4xx errors classified: invalid number, opted-out, permission, etc.
# =============================================================================

import logging
import time
from collections import defaultdict, deque
from typing import Optional, Dict, Any, List

from app.config import settings

logger = logging.getLogger(__name__)

_NO_RETRY_CODES = {21211, 21212, 21408, 21610, 21614, 21615, 63003, 63007}

_TWILIO_ERRORS = {
    21211: "Invalid 'To' number — check E.164 format",
    21212: "Invalid 'From' number — check TWILIO_WHATSAPP_FROM configuration",
    21408: "Permission denied — number not approved for this region",
    21610: "Recipient opted out — do not retry",
    63003: "Channel capability error — recipient not reachable on WhatsApp",
    63007: "WhatsApp account not found for 'To' number",
}


class WhatsAppService:
    """Send WhatsApp alerts via Twilio WhatsApp Business API.

    Credentials loaded from environment variables (preferred) or DB settings.
    The 'whatsapp:' prefix is added automatically to both From and To numbers.
    """

    def __init__(self):
        self._client = None
        self._rate_windows: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=settings.WA_RATE_LIMIT_PER_HOUR + 1)
        )

    # ── Twilio client ──────────────────────────────────────────────────

    async def _get_client(self):
        """Lazy-init Twilio client.  Env vars > DB settings (async read).

        DB settings are read through SettingsService.get_value which transparently
        decrypts sensitive keys (e.g. twilio_auth_token, encrypted at rest)."""
        if self._client is not None:
            return self._client
        try:
            from twilio.rest import Client

            sid = settings.TWILIO_ACCOUNT_SID
            token = settings.TWILIO_AUTH_TOKEN

            if not sid or not token:
                try:
                    from app.settings.service import SettingsService
                    from app.database import async_session_maker
                    async with async_session_maker() as db:
                        sid = sid or await SettingsService.get_value(db, "twilio_account_sid", "")
                        token = token or await SettingsService.get_value(db, "twilio_auth_token", "")
                except Exception as exc:
                    logger.debug(f"[whatsapp] DB settings read failed: {exc}")

            if not sid or not token:
                return None

            self._client = Client(sid, token)
            return self._client
        except ImportError:
            logger.warning("[whatsapp] twilio package not installed — WhatsApp disabled")
            return None
        except Exception as exc:
            logger.warning(f"[whatsapp] Twilio client init failed: {exc}")
            return None

    async def _get_from_number(self) -> str:
        from_number = settings.TWILIO_WHATSAPP_FROM
        if not from_number:
            try:
                from app.settings.service import SettingsService
                from app.database import async_session_maker
                async with async_session_maker() as db:
                    from_number = await SettingsService.get_value(db, "twilio_whatsapp_number", "")
            except Exception as exc:
                logger.debug(f"[whatsapp] DB from-number read failed: {exc}")
        return from_number

    # ── Rate limiting ──────────────────────────────────────────────────

    def _is_rate_limited(self, to_number: str) -> bool:
        limit = settings.WA_RATE_LIMIT_PER_HOUR
        now = time.time()
        window = self._rate_windows[to_number]
        while window and now - window[0] > 3600:
            window.popleft()
        return len(window) >= limit

    def _record_send(self, to_number: str):
        self._rate_windows[to_number].append(time.time())

    # ── Send ───────────────────────────────────────────────────────────

    async def send(
        self,
        to_number: str,
        message: str,
        from_number: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a WhatsApp message.  Returns {ok, sid, status} or {ok: False, error}."""
        if self._is_rate_limited(to_number):
            logger.warning(
                f"[whatsapp] Rate limit reached for {to_number} "
                f"({settings.WA_RATE_LIMIT_PER_HOUR}/hour) — dropping"
            )
            try:
                from app.core.metrics import GVD_WHATSAPP_RATE_LIMITED
                GVD_WHATSAPP_RATE_LIMITED.inc()
            except Exception:
                pass
            return {
                "ok": False,
                "error": (
                    f"Rate limit: max {settings.WA_RATE_LIMIT_PER_HOUR} "
                    "WhatsApp messages per recipient per hour"
                ),
                "no_retry": True,
            }

        client = await self._get_client()
        if not client:
            return {
                "ok": False,
                "error": (
                    "Twilio not configured for WhatsApp. "
                    "Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_WHATSAPP_FROM. "
                    "Get your WhatsApp Business number at: "
                    "https://console.twilio.com/us1/develop/sms/whatsapp/learn"
                ),
            }

        _from = from_number or await self._get_from_number()
        if not _from:
            return {
                "ok": False,
                "error": (
                    "WhatsApp sender number not configured (TWILIO_WHATSAPP_FROM). "
                    "Register a WhatsApp Business number at: "
                    "https://console.twilio.com/us1/develop/sms/whatsapp/learn"
                ),
            }

        # Ensure whatsapp: prefix
        wa_from = _from if _from.startswith("whatsapp:") else f"whatsapp:{_from}"
        wa_to = to_number if to_number.startswith("whatsapp:") else f"whatsapp:{to_number}"

        try:
            from asyncio import to_thread
            result = await to_thread(
                lambda: client.messages.create(body=message, from_=wa_from, to=wa_to)
            )
            self._record_send(to_number)
            try:
                from app.core.metrics import GVD_WHATSAPP_SENT
                GVD_WHATSAPP_SENT.inc()
            except Exception:
                pass
            logger.info(f"[whatsapp] Sent to {to_number} sid={result.sid}")
            return {"ok": True, "sid": result.sid, "status": result.status}

        except Exception as exc:
            no_retry = False
            # Clean, non-technical default — never surface raw SDK/exception text.
            error_msg = "Couldn't send the WhatsApp message. Check the number and Twilio settings."

            try:
                from twilio.base.exceptions import TwilioRestException
                if isinstance(exc, TwilioRestException):
                    code = exc.code
                    explanation = _TWILIO_ERRORS.get(code)
                    error_msg = explanation or "The WhatsApp provider rejected the message."
                    no_retry = code in _NO_RETRY_CODES
                    logger.error(
                        f"[whatsapp] Twilio rejected send to {to_number}: "
                        f"code={code} status={exc.status}"
                    )
            except ImportError:
                pass

            try:
                from app.core.metrics import GVD_WHATSAPP_FAILED
                reason = "twilio_rejected" if no_retry else "send_error"
                GVD_WHATSAPP_FAILED.labels(reason=reason).inc()
            except Exception:
                pass

            if not no_retry:
                logger.error(f"[whatsapp] Send failed to {to_number}: {exc}")

            return {"ok": False, "error": error_msg, "no_retry": no_retry}

    async def send_bulk(self, recipients: List[str], message: str) -> list:
        """Send WhatsApp to multiple recipients."""
        results = []
        for recipient in recipients:
            result = await self.send(recipient, message)
            results.append({"to": recipient, **result})
        return results


# Module singleton
whatsapp_service = WhatsAppService()
