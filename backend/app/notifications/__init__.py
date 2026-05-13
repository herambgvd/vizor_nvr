# =============================================================================
# Notifications Module
# =============================================================================

from app.notifications.service import notification_service, NotificationService
from app.notifications.models import NotificationEvent
from app.notifications.router import router

__all__ = [
    "notification_service",
    "NotificationService", 
    "NotificationEvent",
    "router",
]
