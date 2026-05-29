"""
WebSocket Router - Real-time updates for cameras, events, and system status
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends, status
from jose import jwt, JWTError
from typing import Optional
import asyncio
import json
import logging

# Seconds to wait for the client's first-message auth frame before closing.
WS_AUTH_TIMEOUT = 10

from app.config import settings
from app.core.websocket import ws_manager as connection_manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


async def get_current_user_ws(token: str) -> Optional[dict]:
    """
    Validate JWT token for WebSocket connections.
    Returns user data or None if invalid.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        user_id = payload.get("sub")
        if user_id is None:
            return None
        return {
            "id": user_id,
            "username": payload.get("username", "unknown"),
            "role": payload.get("role", "viewer")
        }
    except JWTError as e:
        logger.warning(f"WebSocket JWT validation failed: {e}")
        return None


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    channels: str = Query("all", description="Comma-separated channels: cameras,events,system,all")
):
    """
    WebSocket endpoint for real-time updates.

    Authentication: after the socket opens, the client must send an auth frame
    as its FIRST message: {"type": "auth", "token": "<jwt>"}. The token is NOT
    accepted as a query parameter — that would leak it into access logs, proxy
    logs, and browser history.

    Channels:
      - cameras: Camera status changes (online/offline/error)
      - system: System notifications (errors, maintenance)
      - all: Subscribe to all channels

    Example: ws://localhost:8000/api/ws?channels=cameras,system
    """
    # Parse channels (non-sensitive — fine to pass via query)
    requested_channels = [ch.strip() for ch in channels.split(",")]
    valid_channels = {"cameras", "events", "system", "all"}
    channel_list = [ch for ch in requested_channels if ch in valid_channels]

    if not channel_list:
        channel_list = ["all"]

    # Accept the socket, then require an auth frame before doing anything else.
    await websocket.accept()

    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=WS_AUTH_TIMEOUT)
        auth_msg = json.loads(raw)
    except (asyncio.TimeoutError, json.JSONDecodeError, WebSocketDisconnect):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    if not isinstance(auth_msg, dict) or auth_msg.get("type") != "auth":
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user = await get_current_user_ws(auth_msg.get("token") or "")
    if not user:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user_id = user["id"]

    # Register all channels at once.
    # NOTE: connection_manager.connect() must NOT call websocket.accept()
    # because the accept already happened above.
    await connection_manager.connect(websocket, channel_list, user_id)
    
    # Send welcome message
    await websocket.send_json({
        "type": "connected",
        "user": user["username"],
        "channels": channel_list,
        "message": "WebSocket connection established"
    })
    
    logger.info(f"WebSocket connected: user={user['username']}, channels={channel_list}")
    
    try:
        while True:
            # Receive and handle client messages
            data = await websocket.receive_text()
            
            try:
                message = json.loads(data)
                msg_type = message.get("type")
                
                if msg_type == "ping":
                    await websocket.send_json({"type": "pong"})
                
                elif msg_type == "subscribe":
                    # Subscribe to additional channels
                    new_channels = [
                        ch for ch in message.get("channels", [])
                        if ch in valid_channels and ch not in channel_list
                    ]
                    if new_channels:
                        await connection_manager.connect(websocket, new_channels)
                        channel_list.extend(new_channels)
                    await websocket.send_json({
                        "type": "subscribed",
                        "channels": list(set(channel_list))
                    })

                elif msg_type == "unsubscribe":
                    # Unsubscribe from specific channels
                    remove_channels = message.get("channels", [])
                    for ch in remove_channels:
                        if ch in channel_list:
                            connection_manager.disconnect_channel(websocket, ch)
                            channel_list.remove(ch)
                    await websocket.send_json({
                        "type": "unsubscribed",
                        "channels": channel_list
                    })
                
                else:
                    # Echo unknown message types for debugging
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Unknown message type: {msg_type}"
                    })
                    
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON"
                })
                
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: user={user['username']}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        # Remove from all channels and user map
        connection_manager.disconnect(websocket, user_id)
