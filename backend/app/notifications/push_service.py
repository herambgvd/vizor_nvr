# =============================================================================
# Push Notification Service — Firebase Cloud Messaging (FCM)
# =============================================================================
#
# Handles device token registration and FCM dispatch for:
#   - motion_detected
#   - camera_offline
#   - camera_online
#   - recording_gap
#   - disk_full
#
# Setup:
#   1. Download serviceAccountKey.json from Firebase Console
#   2. Place at backend/data/certs/firebase-adminsdk.json
#   3. Or set FIREBASE_CREDENTIALS_PATH env var
# =============================================================================

import asyncio
import json
import logging
import os
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_maker
from app.config import settings

logger = logging.getLogger(__name__)


class PushNotificationService:
    """
    Async FCM push notification dispatcher.
    Falls back gracefully if Firebase credentials are not configured.
    """

    def __init__(self):
        self._initialized = False
        self._firebase_admin = None
        self._messaging = None
        self._client: Optional[Any] = None  # httpx.AsyncClient for FCM HTTP v1
        self._credential_path: Optional[str] = None
        self._project_id: Optional[str] = None
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def _init_firebase(self) -> bool:
        """Lazy-initialize Firebase Admin SDK. Returns True on success."""
        if self._initialized:
            return self._firebase_admin is not None

        self._initialized = True
        cred_path = os.getenv(
            "FIREBASE_CREDENTIALS_PATH",
            os.path.join(settings.CERT_PATH, "firebase-adminsdk.json"),
        )
        if not os.path.exists(cred_path):
            logger.debug(f"Firebase credentials not found at {cred_path} — push notifications disabled")
            return False

        try:
            import firebase_admin
            from firebase_admin import credentials, messaging

            if not firebase_admin._apps:
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred)

            self._firebase_admin = firebase_admin
            self._messaging = messaging
            self._credential_path = cred_path

            # Extract project_id for HTTP v1 API
            with open(cred_path) as f:
                cred_data = json.load(f)
                self._project_id = cred_data.get("project_id")

            logger.info("Firebase Admin SDK initialized — push notifications enabled")
            return True
        except ImportError:
            logger.warning("firebase-admin not installed — push notifications disabled. "
                           "Install: pip install firebase-admin")
            return False
        except Exception as e:
            logger.error(f"Firebase initialization failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Device token management
    # ------------------------------------------------------------------

    async def register_token(self, user_id: str, fcm_token: str, platform: str = "web") -> bool:
        """Register or update an FCM device token for a user."""
        async with async_session_maker() as db:
            from app.notifications.models import PushToken
            # Delete old tokens with same fcm_token (re-registration)
            await db.execute(
                delete(PushToken).where(PushToken.token == fcm_token)
            )
            pt = PushToken(
                user_id=user_id,
                token=fcm_token,
                platform=platform,
            )
            db.add(pt)
            await db.commit()
        logger.info(f"Push token registered for user {user_id} ({platform})")
        return True

    async def unregister_token(self, user_id: str, fcm_token: str) -> bool:
        """Remove a device token."""
        async with async_session_maker() as db:
            from app.notifications.models import PushToken
            await db.execute(
                delete(PushToken).where(
                    PushToken.user_id == user_id,
                    PushToken.token == fcm_token,
                )
            )
            await db.commit()
        return True

    async def get_user_tokens(self, user_id: str) -> List[str]:
        """Get all active FCM tokens for a user."""
        async with async_session_maker() as db:
            from app.notifications.models import PushToken
            result = await db.execute(
                select(PushToken.token).where(PushToken.user_id == user_id)
            )
            return [r[0] for r in result.all()]

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def send_push(
        self,
        user_id: str,
        title: str,
        body: str,
        data: Optional[Dict[str, str]] = None,
        image_url: Optional[str] = None,
    ) -> bool:
        """Send a push notification to all devices registered to a user."""
        if not self._init_firebase():
            return False

        tokens = await self.get_user_tokens(user_id)
        if not tokens:
            logger.debug(f"No push tokens for user {user_id}")
            return False

        success = False
        for token in tokens:
            try:
                message = self._messaging.Message(
                    notification=self._messaging.Notification(
                        title=title,
                        body=body,
                        image=image_url,
                    ),
                    data=data or {},
                    token=token,
                    android=self._messaging.AndroidConfig(
                        priority="high",
                        notification=self._messaging.AndroidNotification(
                            channel_id="gvd_nvr_alerts",
                            priority="high",
                        ),
                    ),
                    apns=self._messaging.APNSConfig(
                        payload=self._messaging.APNSPayload(
                            aps=self._messaging.Aps(alert={"title": title, "body": body})
                        )
                    ),
                )
                response = self._messaging.send(message)
                logger.debug(f"Push sent to {token[:16]}... — {response}")
                success = True
            except Exception as e:
                logger.warning(f"Push to {token[:16]}... failed: {e}")
                # If token is invalid, delete it
                if "registration-token-not-registered" in str(e).lower():
                    await self.unregister_token(user_id, token)
        return success

    async def notify_event(
        self,
        user_id: str,
        event_type: str,
        camera_id: Optional[str] = None,
        camera_name: Optional[str] = None,
        snapshot_url: Optional[str] = None,
    ):
        """High-level helper to send event-based push notification."""
        titles = {
            "motion_detected": f"🚨 Motion detected — {camera_name or camera_id}",
            "camera_offline": f"⚠️ Camera offline — {camera_name or camera_id}",
            "camera_online": f"✅ Camera online — {camera_name or camera_id}",
            "video_loss": f"❌ Video loss — {camera_name or camera_id}",
            "disk_full": "💾 Storage full",
            "recording_gap": f"⏸️ Recording gap — {camera_name or camera_id}",
        }
        bodies = {
            "motion_detected": f"Motion detected on {camera_name or camera_id}",
            "camera_offline": f"{camera_name or camera_id} is offline",
            "camera_online": f"{camera_name or camera_id} is back online",
            "video_loss": f"Video stream lost for {camera_name or camera_id}",
            "disk_full": "Recording storage is full — old files will be deleted",
            "recording_gap": f"No new recording from {camera_name or camera_id}",
        }

        await self.send_push(
            user_id=user_id,
            title=titles.get(event_type, "NVR Alert"),
            body=bodies.get(event_type, "An event occurred"),
            data={
                "event_type": event_type,
                "camera_id": camera_id or "",
                "click_action": f"/playback?camera={camera_id}" if camera_id else "/events",
            },
            image_url=snapshot_url,
        )


# Module singleton
push_service = PushNotificationService()
