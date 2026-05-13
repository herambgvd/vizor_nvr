# =============================================================================
# ONVIF WS-Discovery Publisher — announces the NVR on the local network
# =============================================================================

import asyncio
import logging
import socket
import uuid
import os
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from wsdiscovery import WSDiscovery, QName, Scope
    from wsdiscovery.service import Service
    _HAS_WSDISCOVERY = True
except ImportError:
    _HAS_WSDISCOVERY = False
    logger.info("WSDiscovery not installed — ONVIF device discovery disabled")


class ONVIFDiscoveryPublisher:
    """Publishes the NVR as an ONVIF device via WS-Discovery Hello multicasts."""

    HELLO_INTERVAL = 60  # seconds

    def __init__(self):
        self._wsd: Optional[WSDiscovery] = None
        self._service: Optional[Service] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._epr = uuid.uuid4().urn

    def _get_advertise_host(self) -> str:
        env_host = os.getenv("ONVIF_XADDR_HOST", "")
        if env_host:
            return env_host
        # Try to find primary non-loopback IP
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            pass
        return "127.0.0.1"

    def _build_service(self) -> Service:
        host = self._get_advertise_host()
        xaddr = f"http://{host}/onvif/device_service"
        return Service(
            types=[QName("http://www.onvif.org/ver10/network/wsdl", "NetworkVideoTransmitter")],
            scopes=[Scope("onvif://www.onvif.org/name/GVD-NVR")],
            xAddrs=[xaddr],
            epr=self._epr,
            instanceId=1,
        )

    async def start(self):
        if not _HAS_WSDISCOVERY:
            return
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="onvif_discovery")
        logger.info("ONVIF discovery publisher started")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._wsd and self._service:
            try:
                self._wsd._sendBye(self._service)
            except Exception as e:
                logger.debug(f"WS-Discovery Bye failed: {e}")
            try:
                self._wsd.stop()
            except Exception:
                pass
        logger.info("ONVIF discovery publisher stopped")

    async def _run(self):
        try:
            self._wsd = WSDiscovery()
            self._wsd.start()
            self._service = self._build_service()
            # Initial Hello
            self._wsd._sendHello(self._service)
        except Exception as e:
            logger.warning(f"ONVIF discovery init failed: {e}")
            return

        while self._running:
            try:
                await asyncio.sleep(self.HELLO_INTERVAL)
                if not self._running:
                    break
                # Rebuild service in case IP changed
                self._service = self._build_service()
                self._wsd._sendHello(self._service)
                logger.debug("ONVIF discovery Hello sent")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"ONVIF discovery heartbeat error: {e}")


# Module singleton
onvif_discovery_publisher = ONVIFDiscoveryPublisher()
