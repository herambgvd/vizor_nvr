# =============================================================================
# WebSocket Manager — real-time updates for frontend
# =============================================================================

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Set, Any, Optional

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages WebSocket connections for real-time updates.
    
    Supports multiple channels:
    - "cameras": Camera status updates
    - "system": System-wide notifications
    """

    def __init__(self):
        # Map channel -> set of active WebSocket connections
        self._connections: Dict[str, Set[WebSocket]] = {
            "cameras": set(),
            "system": set(),
            "events": set(),
            "all": set(),
        }
        self._user_connections: Dict[str, WebSocket] = {}  # user_id -> websocket

    async def connect(
        self,
        websocket: WebSocket,
        channels: List[str],
        user_id: Optional[str] = None,
    ):
        """
        Register an already-accepted WebSocket to the given channels.
        The caller (websocket_router) is responsible for calling websocket.accept()
        BEFORE this method.
        """
        for channel in channels:
            if channel not in self._connections:
                self._connections[channel] = set()
            self._connections[channel].add(websocket)

        if user_id:
            self._user_connections[str(user_id)] = websocket

        logger.debug(f"WebSocket registered: channels={channels}, user={user_id}")

    def disconnect(self, websocket: WebSocket, user_id: Optional[str] = None):
        """Remove a connection from ALL channels (called on full disconnect)."""
        for channel_connections in self._connections.values():
            channel_connections.discard(websocket)

        if user_id and str(user_id) in self._user_connections:
            del self._user_connections[str(user_id)]

        logger.debug(f"WebSocket fully disconnected: user={user_id}")

    def disconnect_channel(self, websocket: WebSocket, channel: str):
        """Remove a connection from a specific channel only (unsubscribe)."""
        self._connections.get(channel, set()).discard(websocket)
        logger.debug(f"WebSocket unsubscribed from channel: {channel}")

    async def broadcast(self, channel: str, message: dict):
        """Send message to all connections in a channel."""
        payload = json.dumps({
            "channel": channel,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **message,
        })
        
        # Send to specific channel
        targets = self._connections.get(channel, set()).copy()
        # Also send to "all" subscribers
        targets.update(self._connections.get("all", set()))
        
        disconnected = []
        for connection in targets:
            try:
                await connection.send_text(payload)
            except Exception:
                disconnected.append(connection)
        
        # Clean up disconnected
        for conn in disconnected:
            self.disconnect(conn)

    async def send_to_user(self, user_id: str, message: dict):
        """Send message to a specific user."""
        websocket = self._user_connections.get(user_id)
        if websocket:
            try:
                payload = json.dumps({
                    "channel": "user",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    **message,
                })
                await websocket.send_text(payload)
            except Exception:
                self.disconnect(websocket, user_id)

    @property
    def connection_count(self) -> int:
        """Total unique connections."""
        all_connections = set()
        for connections in self._connections.values():
            all_connections.update(connections)
        return len(all_connections)

    # ── Convenience methods for specific event types ────────────────

    async def broadcast_camera_status(
        self,
        camera_id: str,
        status: str,
        is_recording: bool,
        camera_name: Optional[str] = None,
    ):
        """Broadcast camera status update."""
        await self.broadcast("cameras", {
            "type": "camera_status",
            "data": {
                "camera_id": camera_id,
                "camera_name": camera_name,
                "status": status,
                "is_recording": is_recording,
            },
        })

    async def broadcast_system_event(
        self,
        event_type: str,
        message: str,
        severity: str = "info",
        data: Optional[dict] = None,
    ):
        """Broadcast system-wide event."""
        await self.broadcast("system", {
            "type": event_type,
            "severity": severity,
            "message": message,
            "data": data or {},
        })


# Module singleton
ws_manager = ConnectionManager()
