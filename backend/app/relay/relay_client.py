# =============================================================================
# P2P Relay Client — Easy Remote Access without Port Forwarding
# =============================================================================
#
# Uses a lightweight WebSocket-based tunnel to a public relay server.
# The relay server (self-hosted or SaaS) bridges external HTTPS/WSS
# traffic to the local NVR backend.
#
# Protocol:
#   1. NVR connects to wss://relay.gvd-nvr.com/register with device_id
#   2. Relay assigns a public URL: https://{device_id}.relay.gvd-nvr.com
#   3. External requests → relay → WebSocket tunnel → local NVR
#
# This is similar to ngrok / Cloudflare Tunnel but lighter.
# =============================================================================

import asyncio
import json
import logging
import os
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class RelayClient:
    """
    Async WebSocket tunnel client for P2P remote access.
    """

    def __init__(self):
        self._ws = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._device_id: Optional[str] = None
        self._relay_url: Optional[str] = None
        self._public_url: Optional[str] = None

    @property
    def public_url(self) -> Optional[str]:
        return self._public_url

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    async def start(self, device_id: str, relay_server_url: Optional[str] = None):
        """
        Start the relay tunnel.

        Args:
            device_id: Unique device identifier (persisted in settings).
            relay_server_url: WebSocket URL of the relay server.
                              Defaults to env RELAY_SERVER_URL or built-in.
        """
        if self._running:
            return

        self._device_id = device_id
        self._relay_url = relay_server_url or os.getenv(
            "RELAY_SERVER_URL", "wss://relay.gvd-nvr.com/v1/ws"
        )
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"Relay client starting (device={device_id}, relay={self._relay_url})")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
        logger.info("Relay client stopped")

    async def _loop(self):
        """Maintain WebSocket connection with automatic reconnect."""
        import aiohttp

        retry_delay = 5
        max_retry_delay = 300

        while self._running:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(
                        self._relay_url,
                        params={"device_id": self._device_id, "type": "nvr"},
                        heartbeat=30.0,
                    ) as ws:
                        self._ws = ws
                        logger.info("Relay connected")
                        retry_delay = 5  # Reset on success

                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                await self._handle_message(msg.json())
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                logger.warning(f"Relay WS error: {ws.exception()}")
                                break
                            elif msg.type == aiohttp.WSMsgType.CLOSED:
                                break

            except Exception as e:
                logger.warning(f"Relay connection failed: {e} — retrying in {retry_delay}s")

            self._ws = None
            self._public_url = None
            await asyncio.sleep(retry_delay)
            retry_delay = min(max_retry_delay, retry_delay * 2)

    async def _handle_message(self, msg: dict):
        """Handle incoming relay messages (HTTP requests tunneled over WS)."""
        msg_type = msg.get("type")

        if msg_type == "registered":
            self._public_url = msg.get("public_url")
            logger.info(f"Relay registered — public URL: {self._public_url}")

        elif msg_type == "http_request":
            # Tunnel an HTTP request from the relay to the local backend
            request_id = msg.get("request_id")
            method = msg.get("method", "GET")
            path = msg.get("path", "/")
            headers = msg.get("headers", {})
            body = msg.get("body")

            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    local_url = f"http://localhost:{settings.PORT}{path}"
                    response = await client.request(
                        method=method,
                        url=local_url,
                        headers=headers,
                        content=body,
                    )

                    await self._send({
                        "type": "http_response",
                        "request_id": request_id,
                        "status": response.status_code,
                        "headers": dict(response.headers),
                        "body": response.text,
                    })
            except Exception as e:
                logger.error(f"Relay tunnel request failed: {e}")
                await self._send({
                    "type": "http_response",
                    "request_id": request_id,
                    "status": 502,
                    "body": f"Tunnel error: {e}",
                })

    async def _send(self, data: dict):
        if self._ws and not self._ws.closed:
            await self._ws.send_json(data)


# Module singleton
relay_client = RelayClient()
