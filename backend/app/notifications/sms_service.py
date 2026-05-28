# =============================================================================
# SMS Service — Twilio integration for SMS alerts
# =============================================================================

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class SMSService:
    """Send SMS alerts via Twilio."""

    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from twilio.rest import Client
            from app.settings.service import SettingsService
            import asyncio
            # SettingsService is sync-friendly for reads (cached)
            sid = SettingsService.get_sync("twilio_account_sid", "")
            token = SettingsService.get_sync("twilio_auth_token", "")
            if not sid or not token:
                return None
            self._client = Client(sid, token)
            return self._client
        except Exception as e:
            logger.warning(f"Twilio client init failed: {e}")
            return None

    async def send(
        self,
        to_number: str,
        message: str,
        from_number: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send an SMS. Returns {ok, sid, error}."""
        client = self._get_client()
        if not client:
            return {"ok": False, "error": "Twilio not configured"}

        if not from_number:
            from app.settings.service import SettingsService
            from asyncio import to_thread
            from functools import partial
            from app.database import async_session_maker
            # Try to get from settings; fallback to async read
            try:
                from_number = SettingsService.get_sync("twilio_phone_number", "")
            except Exception:
                from_number = ""

        if not from_number:
            return {"ok": False, "error": "Twilio phone number not configured"}

        try:
            import asyncio
            from asyncio import to_thread
            result = await to_thread(
                lambda: client.messages.create(
                    body=message,
                    from_=from_number,
                    to=to_number,
                )
            )
            return {"ok": True, "sid": result.sid, "status": result.status}
        except Exception as e:
            logger.error(f"SMS send failed: {e}")
            return {"ok": False, "error": str(e)}

    async def send_bulk(
        self,
        recipients: list,
        message: str,
    ) -> list:
        """Send SMS to multiple recipients."""
        results = []
        for recipient in recipients:
            result = await self.send(recipient, message)
            results.append({"to": recipient, **result})
        return results


# Module singleton
sms_service = SMSService()
