# =============================================================================
# SMS Service — Twilio integration for SMS alerts
# =============================================================================
# Configuration (env vars take precedence over DB settings):
#   TWILIO_ACCOUNT_SID   — Twilio account SID (starts with "AC")
#   TWILIO_AUTH_TOKEN    — Twilio auth token
#   TWILIO_FROM_NUMBER   — Sender E.164 number, e.g. +12015551234
#   SMS_RATE_LIMIT_PER_HOUR — Max SMS per recipient per hour (default 5)
#
# RATE LIMITING
# ─────────────
# An in-memory sliding window (per recipient phone number) caps sends to
# SMS_RATE_LIMIT_PER_HOUR per hour.  Excess sends are dropped and the
# gvd_sms_rate_limited_total counter is incremented.  The window resets
# after 1 hour from the first send in the window.
#
# ERROR CLASSIFICATION
# ────────────────────
# Twilio 4xx errors are classified before retry:
#   21211 — invalid "To" number (don't retry)
#   21212 — invalid "From" number (config error, don't retry)
#   21408 — permission error / number not SMS-capable
#   21610 — recipient opted out (don't retry)
#   Others — logged and returned as-is
# =============================================================================

import logging
import time
from collections import defaultdict, deque
from typing import Optional, Dict, Any, List

from app.config import settings

logger = logging.getLogger(__name__)

# Twilio error codes that should NOT be retried
_NO_RETRY_CODES = {21211, 21212, 21408, 21610, 21614, 21615}

# Human-readable Twilio error explanations
_TWILIO_ERRORS = {
    21211: "Invalid 'To' phone number — check the recipient number format (E.164 required)",
    21212: "Invalid sender number — check the SMS sender configuration",
    21408: "SMS sending is not permitted to this region",
    21610: "Recipient has opted out (blacklisted) — do not retry",
    21614: "'To' number is not a valid mobile number",
    21615: "'To' number is not SMS-capable",
}


class SMSService:
    """Send SMS alerts via Twilio.

    Credentials loaded from environment variables (preferred) or DB settings.
    """

    def __init__(self):
        self._client = None
        # Rate limiting: {phone_number: deque of send timestamps (epoch seconds)}
        self._rate_windows: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=settings.SMS_RATE_LIMIT_PER_HOUR + 1)
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

            # Fall back to DB settings when env vars are not set
            if not sid or not token:
                try:
                    from app.settings.service import SettingsService
                    from app.database import async_session_maker
                    async with async_session_maker() as db:
                        sid = sid or await SettingsService.get_value(db, "twilio_account_sid", "")
                        token = token or await SettingsService.get_value(db, "twilio_auth_token", "")
                except Exception as exc:
                    logger.debug(f"[sms] DB settings read failed: {exc}")

            if not sid or not token:
                return None

            self._client = Client(sid, token)
            return self._client
        except ImportError:
            logger.warning("[sms] twilio package not installed — SMS disabled")
            return None
        except Exception as exc:
            logger.warning(f"[sms] Twilio client init failed: {exc}")
            return None

    async def _get_from_number(self) -> str:
        from_number = settings.TWILIO_FROM_NUMBER
        if not from_number:
            try:
                from app.settings.service import SettingsService
                from app.database import async_session_maker
                async with async_session_maker() as db:
                    from_number = await SettingsService.get_value(db, "twilio_phone_number", "")
            except Exception as exc:
                logger.debug(f"[sms] DB from-number read failed: {exc}")
        return from_number

    # ── Rate limiting ──────────────────────────────────────────────────

    def _is_rate_limited(self, to_number: str) -> bool:
        """Return True if this recipient has exceeded the per-hour cap."""
        limit = settings.SMS_RATE_LIMIT_PER_HOUR
        now = time.time()
        window = self._rate_windows[to_number]
        # Evict entries older than 1 hour
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
        """Send an SMS.  Returns {ok, sid, status} or {ok: False, error, no_retry}."""
        if self._is_rate_limited(to_number):
            logger.warning(
                f"[sms] Rate limit reached for {to_number} "
                f"({settings.SMS_RATE_LIMIT_PER_HOUR}/hour) — dropping"
            )
            try:
                from app.core.metrics import GVD_SMS_RATE_LIMITED
                GVD_SMS_RATE_LIMITED.inc()
            except Exception:
                pass
            return {
                "ok": False,
                "error": f"Rate limit: max {settings.SMS_RATE_LIMIT_PER_HOUR} SMS per recipient per hour",
                "no_retry": True,
            }

        client = await self._get_client()
        if not client:
            return {"ok": False, "error": "SMS is not configured yet. Add your SMS provider credentials in settings."}

        _from = from_number or await self._get_from_number()
        if not _from:
            return {"ok": False, "error": "No SMS sender number is configured. Add one in settings."}

        try:
            from asyncio import to_thread
            result = await to_thread(
                lambda: client.messages.create(body=message, from_=_from, to=to_number)
            )
            self._record_send(to_number)
            try:
                from app.core.metrics import GVD_SMS_SENT
                GVD_SMS_SENT.inc()
            except Exception:
                pass
            logger.info(f"[sms] Sent to {to_number} sid={result.sid}")
            return {"ok": True, "sid": result.sid, "status": result.status}

        except Exception as exc:
            no_retry = False
            # Clean, non-technical default — never surface raw SDK/exception text
            # to the operator. Classified Twilio codes get a specific message.
            error_msg = "Couldn't send the SMS. Check the number and SMS settings."

            # Classify Twilio REST exceptions
            try:
                from twilio.base.exceptions import TwilioRestException
                if isinstance(exc, TwilioRestException):
                    code = exc.code
                    explanation = _TWILIO_ERRORS.get(code)
                    error_msg = explanation or "The SMS provider rejected the message."
                    no_retry = code in _NO_RETRY_CODES
                    logger.error(
                        f"[sms] Twilio rejected send to {to_number}: "
                        f"code={code} status={exc.status}"
                    )
            except ImportError:
                pass

            try:
                from app.core.metrics import GVD_SMS_FAILED
                reason = "twilio_rejected" if no_retry else "send_error"
                GVD_SMS_FAILED.labels(reason=reason).inc()
            except Exception:
                pass

            if not no_retry:
                logger.error(f"[sms] Send failed to {to_number}: {exc}")

            return {"ok": False, "error": error_msg, "no_retry": no_retry}

    async def send_bulk(self, recipients: List[str], message: str) -> list:
        """Send SMS to multiple recipients (honours per-recipient rate limit)."""
        results = []
        for recipient in recipients:
            result = await self.send(recipient, message)
            results.append({"to": recipient, **result})
        return results


# Module singleton
sms_service = SMSService()
