# =============================================================================
# Notification Service — webhook dispatch, event handling
# =============================================================================

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import (
    WebhookConfig, NotificationLog, NotificationEvent,
)
from app.database import async_session_maker

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Handles webhook notifications for various system events.
    
    Usage:
        await notification_service.notify(
            event=NotificationEvent.CAMERA_OFFLINE,
            data={"camera_id": "...", "camera_name": "..."},
            camera_id="..."
        )
    """

    # Bound the in-memory queue so a backend stall (slow/blocked dispatch)
    # can't grow it without limit and OOM the process. When full, the oldest
    # queued notification is dropped (see notify()).
    _MAX_QUEUE_SIZE = 10000
    # Per-channel dispatch retry policy (transient failures).
    _DISPATCH_MAX_ATTEMPTS = 3

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=self._MAX_QUEUE_SIZE)
        self._worker_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        """Start the notification worker."""
        if self._running:
            return
        self._running = True
        self._client = httpx.AsyncClient(timeout=30)
        self._worker_task = asyncio.create_task(self._worker())
        logger.info("Notification service started")

    async def stop(self):
        """Stop the notification worker."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.aclose()
        logger.info("Notification service stopped")

    async def _worker(self):
        """Background worker that processes notification queue."""
        while self._running:
            try:
                # Wait for notification with timeout
                try:
                    item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                event, data, camera_id = item
                await self._dispatch(event, data, camera_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Notification worker error: {e}")

    async def notify(
        self,
        event: NotificationEvent,
        data: Dict[str, Any],
        camera_id: Optional[str] = None,
    ):
        """
        Queue a notification for dispatch.
        
        Args:
            event: The event type
            data: Event payload data
            camera_id: Optional camera ID for filtering
        """
        try:
            self._queue.put_nowait((event, data, camera_id))
        except asyncio.QueueFull:
            # Queue is at the bounded cap — drop the OLDEST item to make room
            # rather than block the caller or grow unbounded. Log loudly so the
            # backpressure is visible.
            try:
                dropped = self._queue.get_nowait()
                logger.error(
                    f"Notification queue full ({self._MAX_QUEUE_SIZE}) — "
                    f"dropped oldest queued event {dropped[0].value if dropped else '?'}"
                )
            except asyncio.QueueEmpty:
                pass
            try:
                self._queue.put_nowait((event, data, camera_id))
            except asyncio.QueueFull:
                logger.error(
                    f"Notification queue still full after eviction — dropping {event.value}"
                )

    async def notify_sync(
        self,
        event: NotificationEvent,
        data: Dict[str, Any],
        camera_id: Optional[str] = None,
    ):
        """Send notification synchronously (blocking)."""
        await self._dispatch(event, data, camera_id)

    async def _dispatch(
        self,
        event: NotificationEvent,
        data: Dict[str, Any],
        camera_id: Optional[str],
    ):
        """Dispatch notification to all matching webhooks AND email if configured."""
        async with async_session_maker() as db:
            # ── Webhooks ─────────────────────────────────────────────
            result = await db.execute(
                select(WebhookConfig).where(
                    WebhookConfig.is_active.is_(True)
                )
            )
            webhooks = result.scalars().all()

            for webhook in webhooks:
                if event.value not in webhook.events:
                    continue
                if webhook.camera_ids and camera_id:
                    if camera_id not in webhook.camera_ids:
                        continue
                await self._send_webhook(db, webhook, event, data)

            await db.commit()

        # ── Email ─────────────────────────────────────────────────────
        await self._send_email_if_configured(event, data)

        # ── Push Notifications (FCM) ──────────────────────────────────
        await self._send_push_if_configured(event, data, camera_id)

        # ── SMS (Twilio) ──────────────────────────────────────────────
        await self._send_sms_if_configured(event, data)

        # ── WhatsApp (Twilio) ─────────────────────────────────────────
        await self._send_whatsapp_if_configured(event, data)

    async def _send_webhook(
        self,
        db: AsyncSession,
        webhook: WebhookConfig,
        event: NotificationEvent,
        data: Dict[str, Any],
    ):
        """Send a single webhook notification with retries."""
        payload = {
            "event": event.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }

        # Create log entry
        log = NotificationLog(
            webhook_id=webhook.id,
            event_type=event.value,
            payload=payload,
            status="pending",
        )
        db.add(log)
        await db.flush()

        # Build headers
        headers = {"Content-Type": "application/json"}
        if webhook.custom_headers:
            headers.update(webhook.custom_headers)

        # Add HMAC signature if secret is configured
        body = json.dumps(payload)
        if webhook.secret:
            signature = hmac.new(
                webhook.secret.encode(),
                body.encode(),
                hashlib.sha256,
            ).hexdigest()
            headers["X-Webhook-Signature"] = f"sha256={signature}"

        # SSRF guard — block webhooks aimed at loopback / link-local / private /
        # cloud-metadata addresses before any request leaves the box.
        from app.core.ssrf import validate_outbound_url, OutboundURLError
        try:
            await asyncio.to_thread(validate_outbound_url, webhook.url)
        except OutboundURLError as exc:
            log.status = "failed"
            # Use the real column (error_message); `log.error` was a no-op
            # attribute that never persisted, leaving failed rows with no reason.
            # Keep the operator-facing text clean (don't echo internal host/IP).
            log.error_message = "Blocked: destination address is not allowed"
            logger.warning(f"Webhook {webhook.name} blocked by SSRF guard: {exc}")
            await db.flush()
            return

        # Send with retries
        last_error = None
        for attempt in range(webhook.retry_count + 1):
            log.attempts = attempt + 1
            try:
                response = await self._client.post(
                    webhook.url,
                    content=body,
                    headers=headers,
                    timeout=webhook.timeout_seconds,
                )

                log.response_code = response.status_code
                log.response_body = response.text[:1000] if response.text else None

                if response.is_success:
                    log.status = "sent"
                    webhook.success_count += 1
                    webhook.last_triggered_at = datetime.utcnow()
                    logger.debug(
                        f"Webhook sent: {webhook.name} -> {event.value} "
                        f"(status={response.status_code})"
                    )
                    return
                else:
                    last_error = f"HTTP {response.status_code}"
                    logger.warning(
                        f"Webhook failed: {webhook.name} -> {event.value} "
                        f"(status={response.status_code}, attempt={attempt + 1})"
                    )

            except httpx.TimeoutException:
                last_error = "Endpoint timed out"
                logger.warning(
                    f"Webhook timeout: {webhook.name} (attempt={attempt + 1})"
                )
            except httpx.RequestError as e:
                # Clean, non-technical reason for the log/DLQ; full error → server log.
                last_error = "Couldn't reach endpoint"
                logger.warning(
                    f"Webhook error: {webhook.name} -> {e} (attempt={attempt + 1})"
                )

            # Wait before retry (exponential backoff)
            if attempt < webhook.retry_count:
                await asyncio.sleep(2 ** attempt)

        # All retries failed
        log.status = "failed"
        log.error_message = last_error
        webhook.failure_count += 1
        logger.error(
            f"Webhook failed after {webhook.retry_count + 1} attempts: "
            f"{webhook.name} -> {event.value}"
        )

    # ------------------------------------------------------------------
    # CRUD Operations
    # ------------------------------------------------------------------

    @staticmethod
    async def get_all_webhooks(db: AsyncSession) -> List[WebhookConfig]:
        result = await db.execute(
            select(WebhookConfig).order_by(WebhookConfig.created_at)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_webhook(db: AsyncSession, webhook_id: str) -> Optional[WebhookConfig]:
        result = await db.execute(
            select(WebhookConfig).where(WebhookConfig.id == webhook_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_webhook(db: AsyncSession, data) -> WebhookConfig:
        webhook = WebhookConfig(
            name=data.name,
            url=data.url,
            secret=data.secret,
            events=data.events,
            camera_ids=data.camera_ids,
            is_active=data.is_active,
            retry_count=data.retry_count,
            timeout_seconds=data.timeout_seconds,
            custom_headers=data.custom_headers,
        )
        db.add(webhook)
        await db.commit()
        await db.refresh(webhook)
        return webhook

    @staticmethod
    async def update_webhook(
        db: AsyncSession, webhook_id: str, data
    ) -> Optional[WebhookConfig]:
        webhook = await NotificationService.get_webhook(db, webhook_id)
        if not webhook:
            return None
        update = data.model_dump(exclude_unset=True)
        for k, v in update.items():
            setattr(webhook, k, v)
        await db.commit()
        await db.refresh(webhook)
        return webhook

    @staticmethod
    async def delete_webhook(db: AsyncSession, webhook_id: str) -> bool:
        webhook = await NotificationService.get_webhook(db, webhook_id)
        if not webhook:
            return False
        await db.delete(webhook)
        await db.commit()
        return True

    @staticmethod
    async def get_logs(
        db: AsyncSession,
        webhook_id: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[List[NotificationLog], int]:
        from sqlalchemy import func
        base = select(NotificationLog)
        count_q = select(func.count(NotificationLog.id))
        if webhook_id:
            base = base.where(NotificationLog.webhook_id == webhook_id)
            count_q = count_q.where(NotificationLog.webhook_id == webhook_id)
        if event_type:
            base = base.where(NotificationLog.event_type == event_type)
            count_q = count_q.where(NotificationLog.event_type == event_type)
        total = (await db.execute(count_q)).scalar() or 0
        query = base.order_by(NotificationLog.created_at.desc()).limit(limit).offset(offset)
        result = await db.execute(query)
        return list(result.scalars().all()), total

    async def test_webhook(
        self,
        url: str,
        secret: Optional[str] = None,
        custom_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Send a test webhook to verify configuration."""
        payload = {
            "event": "test",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {"message": "This is a test notification from Vizor NVR"},
        }

        headers = {"Content-Type": "application/json"}
        if custom_headers:
            headers.update(custom_headers)

        body = json.dumps(payload)
        if secret:
            signature = hmac.new(
                secret.encode(),
                body.encode(),
                hashlib.sha256,
            ).hexdigest()
            headers["X-Webhook-Signature"] = f"sha256={signature}"

        # SSRF guard on the on-demand test path too. Don't echo the raw guard
        # reason (it can name internal IPs/hosts) — give clean operator copy.
        from app.core.ssrf import validate_outbound_url, OutboundURLError
        try:
            await asyncio.to_thread(validate_outbound_url, url)
        except OutboundURLError:
            return {
                "success": False,
                "error": "That URL isn't allowed. Use a public HTTPS endpoint.",
            }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(url, content=body, headers=headers)
                if response.is_success:
                    return {
                        "success": True,
                        "status_code": response.status_code,
                    }
                # Non-2xx: report the status class without echoing the response
                # body (which may contain internal error detail from the target).
                return {
                    "success": False,
                    "status_code": response.status_code,
                    "error": (
                        f"The endpoint responded with HTTP {response.status_code}. "
                        "Check the URL and that it accepts POST requests."
                    ),
                }
        except httpx.TimeoutException:
            return {"success": False, "error": "The endpoint didn't respond in time."}
        except httpx.RequestError:
            # DNS failure / connection refused / TLS error — don't leak raw text.
            return {"success": False, "error": "Couldn't reach the endpoint. Check the URL is correct and reachable."}

    # ------------------------------------------------------------------
    # Channel dispatch with NotificationLog + retry (DLQ pattern)
    # ------------------------------------------------------------------

    async def _dispatch_channel(
        self,
        channel: str,
        event: NotificationEvent,
        payload: Dict[str, Any],
        send_coro_factory,
    ) -> None:
        """Run a per-channel send (email/SMS/WhatsApp/push) with a NotificationLog
        row and bounded retry — mirrors the webhook log+retry pattern.

        - Creates a NotificationLog row (webhook_id=None, status="pending").
        - Calls ``send_coro_factory()`` (a zero-arg callable returning a coroutine)
          up to _DISPATCH_MAX_ATTEMPTS times with exponential backoff on failure.
        - On success → status="sent". On final failure → status="failed" with the
          error preserved. The failed row IS the DLQ: a queryable record of every
          notification that never went out (rather than a silently swallowed error).

        ``send_coro_factory`` should raise on hard failure. send_bulk-style helpers
        that return per-recipient dicts are inspected: if every recipient failed,
        that is treated as a failure for retry/logging purposes.
        """
        log_payload = {
            "channel": channel,
            "event": event.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": payload,
        }
        log = NotificationLog(
            webhook_id=None,
            event_type=event.value,
            payload=log_payload,
            status="pending",
        )

        last_error: Optional[str] = None
        succeeded = False
        for attempt in range(self._DISPATCH_MAX_ATTEMPTS):
            log.attempts = attempt + 1
            try:
                result = await send_coro_factory()
                # send_bulk returns a list of {"to":..., "ok":bool,...}. Treat
                # "all recipients failed" as a retryable error; partial success
                # counts as sent (per-recipient errors are captured in the result).
                if isinstance(result, list) and result:
                    oks = [r for r in result if isinstance(r, dict) and r.get("ok")]
                    if not oks:
                        errs = "; ".join(
                            str(r.get("error")) for r in result
                            if isinstance(r, dict) and r.get("error")
                        )
                        # If every recipient is no_retry (e.g. invalid number,
                        # opted out, rate-limited), don't waste retries.
                        all_no_retry = all(
                            isinstance(r, dict) and r.get("no_retry")
                            for r in result
                        )
                        last_error = errs or "all recipients failed"
                        if all_no_retry:
                            break
                        raise RuntimeError(last_error)
                succeeded = True
                break
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    f"{channel} dispatch failed for {event.value} "
                    f"(attempt {attempt + 1}/{self._DISPATCH_MAX_ATTEMPTS}): {e}"
                )
                if attempt < self._DISPATCH_MAX_ATTEMPTS - 1:
                    await asyncio.sleep(2 ** attempt)

        log.status = "sent" if succeeded else "failed"
        if not succeeded:
            log.error_message = last_error
            logger.error(
                f"{channel} dispatch FAILED after {self._DISPATCH_MAX_ATTEMPTS} "
                f"attempts for {event.value}: {last_error}"
            )

        # Persist the log row (this is the queryable DLQ for failed sends).
        try:
            async with async_session_maker() as db:
                db.add(log)
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to persist NotificationLog for {channel}/{event.value}: {e}")

    # ------------------------------------------------------------------
    # Email dispatch
    # ------------------------------------------------------------------

    async def _send_email_if_configured(
        self,
        event: NotificationEvent,
        data: Dict[str, Any],
    ) -> None:
        """Send email notification if SMTP is configured and event is subscribed."""
        try:
            from app.settings.service import SettingsService
            from app.notifications.smtp_service import smtp_service

            async with async_session_maker() as db:
                enabled = await SettingsService.get_bool(db, "smtp_enabled", False)
                if not enabled:
                    return

                alert_events_raw = await SettingsService.get_value(
                    db, "smtp_alert_events",
                    "camera_offline,recording_error,storage_low,storage_full,recording_gap"
                )
                alert_events = [e.strip() for e in alert_events_raw.split(",")]
                if event.value not in alert_events:
                    return

                recipients_raw = await SettingsService.get_value(db, "smtp_recipients", "")
                recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]
                if not recipients:
                    return

                smtp_config = {
                    "host":       await SettingsService.get_value(db, "smtp_host"),
                    "port":       await SettingsService.get_value(db, "smtp_port", "587"),
                    "username":   await SettingsService.get_value(db, "smtp_username"),
                    "password":   await SettingsService.get_value(db, "smtp_password"),
                    "use_tls":    await SettingsService.get_value(db, "smtp_use_tls", "true"),
                    "use_ssl":    await SettingsService.get_value(db, "smtp_use_ssl", "false"),
                    "from_email": await SettingsService.get_value(db, "smtp_from_email"),
                    "from_name":  await SettingsService.get_value(db, "smtp_from_name", "Vizor NVR"),
                }

            async def _send():
                ok = await smtp_service.send_event_email(
                    event_type=event.value,
                    data=data,
                    recipients=recipients,
                    smtp_config=smtp_config,
                )
                if not ok:
                    raise RuntimeError("SMTP send returned failure")
                return ok

            await self._dispatch_channel("email", event, {"recipients": recipients, **data}, _send)
        except Exception as e:
            logger.error(f"Email dispatch error for {event.value}: {e}")

    async def send_test_email(self, recipients: List[str], smtp_config: dict) -> Dict[str, Any]:
        """Send a test email to verify SMTP configuration.

        Returns {success, recipients, reason} where ``reason`` is a short, clean
        category (not raw SMTP error text) that the router maps to operator copy.
        """
        from app.notifications.smtp_service import smtp_service
        success, reason = await smtp_service.send_event_email_detailed(
            event_type="test",
            data={"system_name": smtp_config.get("from_name", "Vizor NVR")},
            recipients=recipients,
            smtp_config=smtp_config,
        )
        return {"success": success, "recipients": recipients, "reason": reason}

    # ------------------------------------------------------------------
    # Push notification dispatch
    # ------------------------------------------------------------------

    async def _send_push_if_configured(
        self,
        event: NotificationEvent,
        data: Dict[str, Any],
        camera_id: Optional[str],
    ) -> None:
        """Send FCM push notification to all users with push tokens."""
        try:
            from app.notifications.push_service import push_service
            from app.database import async_session_maker
            from app.auth.models import User
            from sqlalchemy import select

            async with async_session_maker() as db:
                # For now, send to all users. In future, filter by camera access.
                result = await db.execute(select(User))
                users = result.scalars().all()

            if not users:
                return

            async def _send():
                for user in users:
                    await push_service.notify_event(
                        user_id=user.id,
                        event_type=event.value,
                        camera_id=camera_id,
                        camera_name=data.get("camera_name"),
                        snapshot_url=data.get("snapshot_url"),
                    )
                return True

            await self._dispatch_channel("push", event, {"camera_id": camera_id, **data}, _send)
        except Exception as e:
            logger.error(f"Push dispatch error for {event.value}: {e}")

    # ------------------------------------------------------------------
    # SMS dispatch (Twilio)
    # ------------------------------------------------------------------

    async def _send_sms_if_configured(
        self,
        event: NotificationEvent,
        data: Dict[str, Any],
    ) -> None:
        try:
            from app.settings.service import SettingsService
            from app.notifications.sms_service import sms_service

            async with async_session_maker() as db:
                alert_events_raw = await SettingsService.get_value(
                    db, "sms_alert_events",
                    "camera_offline,recording_error,storage_full"
                )
                alert_events = [e.strip() for e in alert_events_raw.split(",")]
                if event.value not in alert_events:
                    return

                recipients_raw = await SettingsService.get_value(db, "sms_recipients", "")
                recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]
                if not recipients:
                    return

            message = f"Vizor NVR Alert: {event.value}"
            if data.get("camera_name"):
                message += f" | {data['camera_name']}"
            if data.get("message"):
                message += f" | {data['message']}"

            await self._dispatch_channel(
                "sms", event, {"recipients": recipients, **data},
                lambda: sms_service.send_bulk(recipients, message),
            )
        except Exception as e:
            logger.error(f"SMS dispatch error for {event.value}: {e}")

    # ------------------------------------------------------------------
    # WhatsApp dispatch (Twilio)
    # ------------------------------------------------------------------

    async def _send_whatsapp_if_configured(
        self,
        event: NotificationEvent,
        data: Dict[str, Any],
    ) -> None:
        try:
            from app.settings.service import SettingsService
            from app.notifications.whatsapp_service import whatsapp_service

            async with async_session_maker() as db:
                alert_events_raw = await SettingsService.get_value(
                    db, "whatsapp_alert_events",
                    "camera_offline,recording_error,storage_full"
                )
                alert_events = [e.strip() for e in alert_events_raw.split(",")]
                if event.value not in alert_events:
                    return

                recipients_raw = await SettingsService.get_value(db, "whatsapp_recipients", "")
                recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]
                if not recipients:
                    return

            message = f"*Vizor NVR Alert*: {event.value}"
            if data.get("camera_name"):
                message += f"\nCamera: {data['camera_name']}"
            if data.get("message"):
                message += f"\nDetails: {data['message']}"

            await self._dispatch_channel(
                "whatsapp", event, {"recipients": recipients, **data},
                lambda: whatsapp_service.send_bulk(recipients, message),
            )
        except Exception as e:
            logger.error(f"WhatsApp dispatch error for {event.value}: {e}")


# Module singleton
notification_service = NotificationService()
