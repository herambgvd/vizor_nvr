# =============================================================================
# Notifications Router — webhook CRUD, test, logs
# =============================================================================

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.notifications.models import (
    WebhookCreate, WebhookUpdate, WebhookResponse,
    NotificationLogResponse, TestWebhookRequest, NotificationEvent,
    PushTokenRegisterRequest,
)
from app.notifications.service import notification_service, NotificationService
from app.notifications.push_service import push_service
from app.core.dependencies import get_admin_user, require_permission
from app.core.audit_logger import write_audit, client_ip

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/notifications", tags=["Notifications"])


# ------------------------------------------------------------------
# Webhook CRUD
# ------------------------------------------------------------------

@router.get("/webhooks", response_model=List[WebhookResponse])
async def list_webhooks(
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """List all webhook configurations."""
    webhooks = await NotificationService.get_all_webhooks(db)
    return [
        WebhookResponse(
            **{
                **w.__dict__,
                "secret": "***" if w.secret else None,  # Mask secret
            }
        )
        for w in webhooks
    ]


@router.get("/webhooks/{webhook_id}", response_model=WebhookResponse)
async def get_webhook(
    webhook_id: str,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single webhook configuration."""
    webhook = await NotificationService.get_webhook(db, webhook_id)
    if not webhook:
        raise HTTPException(404, "Webhook not found")
    return WebhookResponse(
        **{**webhook.__dict__, "secret": "***" if webhook.secret else None}
    )


@router.post("/webhooks", response_model=WebhookResponse, status_code=201)
async def create_webhook(
    data: WebhookCreate,
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new webhook configuration."""
    # Validate events
    valid_events = {e.value for e in NotificationEvent}
    invalid = set(data.events) - valid_events
    if invalid:
        raise HTTPException(400, f"Invalid events: {invalid}")

    webhook = await NotificationService.create_webhook(db, data)
    
    await write_audit(
        db, action="webhook_create", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="webhook", resource_id=webhook.id,
        description=f"Webhook created: {webhook.name}",
    )
    await db.commit()

    return WebhookResponse(
        **{**webhook.__dict__, "secret": "***" if webhook.secret else None}
    )


@router.put("/webhooks/{webhook_id}", response_model=WebhookResponse)
async def update_webhook(
    webhook_id: str,
    data: WebhookUpdate,
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a webhook configuration."""
    # Validate events if provided
    if data.events:
        valid_events = {e.value for e in NotificationEvent}
        invalid = set(data.events) - valid_events
        if invalid:
            raise HTTPException(400, f"Invalid events: {invalid}")

    webhook = await NotificationService.update_webhook(db, webhook_id, data)
    if not webhook:
        raise HTTPException(404, "Webhook not found")

    await write_audit(
        db, action="webhook_update", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="webhook", resource_id=webhook_id,
        details=data.model_dump(exclude_unset=True),
    )
    await db.commit()

    return WebhookResponse(
        **{**webhook.__dict__, "secret": "***" if webhook.secret else None}
    )


@router.delete("/webhooks/{webhook_id}", status_code=204)
async def delete_webhook(
    webhook_id: str,
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a webhook configuration."""
    if not await NotificationService.delete_webhook(db, webhook_id):
        raise HTTPException(404, "Webhook not found")

    await write_audit(
        db, action="webhook_delete", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="webhook", resource_id=webhook_id,
        severity="warning",
    )
    await db.commit()


# ------------------------------------------------------------------
# Test & Events
# ------------------------------------------------------------------

@router.post("/webhooks/test")
async def test_webhook(
    data: TestWebhookRequest,
    user: dict = Depends(get_admin_user),
):
    """Test a webhook URL with a sample payload."""
    result = await notification_service.test_webhook(
        url=data.url,
        secret=data.secret,
        custom_headers=data.custom_headers,
    )
    return result


@router.get("/events")
async def list_events(
    user: dict = Depends(get_admin_user),
):
    """List all available notification event types."""
    return [
        {"value": e.value, "name": e.name}
        for e in NotificationEvent
    ]


# ------------------------------------------------------------------
# Logs
# ------------------------------------------------------------------

@router.get("/logs", response_model=List[NotificationLogResponse])
async def get_logs(
    webhook_id: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 100,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Get notification delivery logs."""
    logs = await NotificationService.get_logs(db, webhook_id, event_type, limit)
    return [NotificationLogResponse(**log.__dict__) for log in logs]


# ------------------------------------------------------------------
# Email / SMTP
# ------------------------------------------------------------------

class SMTPConfigRequest(BaseModel):
    host: str
    port: int = 587
    username: str = ""
    password: str = ""
    use_tls: bool = True
    use_ssl: bool = False
    from_email: str = ""
    from_name: str = "Vizor NVR"
    recipients: List[str]


@router.post("/email/test")
async def test_email(
    data: SMTPConfigRequest,
    user: dict = Depends(get_admin_user),
):
    """
    Send a test email using the provided SMTP config.
    Use this to verify settings before saving.
    """
    smtp_config = data.model_dump(exclude={"recipients"})
    result = await notification_service.send_test_email(
        recipients=data.recipients,
        smtp_config=smtp_config,
    )
    if not result["success"]:
        raise HTTPException(400, "Test email failed — check SMTP settings and server logs")
    return result


# ------------------------------------------------------------------
# Push Notifications (FCM)
# ------------------------------------------------------------------

@router.post("/push/register")
async def register_push_token(
    data: PushTokenRegisterRequest,
    user: dict = Depends(require_permission("view_live")),
):
    """Register an FCM device token for the current user."""
    ok = await push_service.register_token(user["id"], data.token, data.platform)
    return {"success": ok}


@router.post("/push/unregister")
async def unregister_push_token(
    data: PushTokenRegisterRequest,
    user: dict = Depends(require_permission("view_live")),
):
    """Unregister an FCM device token."""
    ok = await push_service.unregister_token(user["id"], data.token)
    return {"success": ok}


@router.post("/push/test")
async def test_push(
    user: dict = Depends(require_permission("view_live")),
):
    """Send a test push notification to the current user's devices."""
    from app.notifications.push_service import push_service
    ok = await push_service.send_push(
        user_id=user["id"],
        title="Vizor NVR Test",
        body="Push notifications are working!",
        data={"event_type": "test", "click_action": "/"},
    )
    if not ok:
        raise HTTPException(400, "Push test failed — no registered devices or FCM error")
    return {"success": True}


# ------------------------------------------------------------------
# SMS / WhatsApp (Twilio)
# ------------------------------------------------------------------

class SMSTestRequest(BaseModel):
    to: str
    message: Optional[str] = "Vizor NVR SMS test"


@router.post("/sms/test")
async def test_sms(
    request: Request,
    body: SMSTestRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_admin_user),
):
    """Send a test SMS via Twilio (admin only).  Audited."""
    from app.notifications.sms_service import sms_service
    result = await sms_service.send(body.to, body.message or "Vizor NVR SMS test")
    await write_audit(
        db,
        action="sms_test",
        user_id=str(user.get("id") or ""),
        username=user.get("username", "admin"),
        ip_address=client_ip(request),
        description="Test SMS sent",
        details={"to": body.to, "ok": result.get("ok"), "error": result.get("error")},
    )
    await db.commit()
    if not result["ok"]:
        raise HTTPException(
            status_code=400,
            detail=result.get("error", "SMS send failed"),
        )
    return result


class WhatsAppTestRequest(BaseModel):
    to: str
    message: Optional[str] = "Vizor NVR WhatsApp test"


@router.post("/whatsapp/test")
async def test_whatsapp(
    request: Request,
    body: WhatsAppTestRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_admin_user),
):
    """Send a test WhatsApp message via Twilio (admin only).  Audited."""
    from app.notifications.whatsapp_service import whatsapp_service
    result = await whatsapp_service.send(body.to, body.message or "Vizor NVR WhatsApp test")
    await write_audit(
        db,
        action="whatsapp_test",
        user_id=str(user.get("id") or ""),
        username=user.get("username", "admin"),
        ip_address=client_ip(request),
        description="Test WhatsApp sent",
        details={"to": body.to, "ok": result.get("ok"), "error": result.get("error")},
    )
    await db.commit()
    if not result["ok"]:
        raise HTTPException(
            status_code=400,
            detail=result.get("error", "WhatsApp send failed"),
        )
    return result
