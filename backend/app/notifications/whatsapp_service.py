# =============================================================================
# WhatsApp Service — Twilio WhatsApp Business API integration
# =============================================================================

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class WhatsAppService:
    """Send WhatsApp alerts via Twilio WhatsApp Business API."""

    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from twilio.rest import Client
            from app.settings.service import SettingsService
            sid = SettingsService.get_sync("twilio_account_sid", "")
            token = SettingsService.get_sync("twilio_auth_token", "")
            if not sid or not token:
                return None
            self._client = Client(sid, token)
            return self._client
        except Exception as e:
            logger.warning(f"Twilio WhatsApp client init failed: {e}")
            return None

    async def send(
        self,
        to_number: str,
        message: str,
        from_number: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a WhatsApp message. Returns {ok, sid, error}."""
        client = self._get_client()
        if not client:
            return {"ok": False, "error": "Twilio not configured"}

        if not from_number:
            from app.settings.service import SettingsService
            try:
                from_number = SettingsService.get_sync("twilio_whatsapp_number", "")
            except Exception:
                from_number = ""
        if not from_number:
            return {"ok": False, "error": "Twilio WhatsApp number not configured"}

        # Ensure numbers have whatsapp: prefix
        if not from_number.startswith("whatsapp:"):
            from_number = f"whatsapp:{from_number}"
        if not to_number.startswith("whatsapp:"):
            to_number = f"whatsapp:{to_number}"

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
            logger.error(f"WhatsApp send failed: {e}")
            return {"ok": False, "error": str(e)}

    async def send_bulk(
        self,
        recipients: list,
        message: str,
    ) -> list:
        """Send WhatsApp to multiple recipients."""
        results = []
        for recipient in recipients:
            result = await self.send(recipient, message)
            results.append({"to": recipient, **result})
        return results


# Module singleton
whatsapp_service = WhatsAppService()
