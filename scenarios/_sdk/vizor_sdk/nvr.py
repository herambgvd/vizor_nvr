"""NVR proxy integration — the contract every scenario plugin shares with the
licensed NVR backend.

Three concerns, identical across plugins:
  1. Inbound auth — gate plugin routes behind the NVR<->plugin service token, and
     read the operator's allowed-camera scope the proxy forwards.
  2. Self-registration — POST the manifest to the NVR scenario catalog on boot.
  3. (Plugins store events in their own DB; the NVR reads them back through the
     proxy. A push helper is provided for plugins that also emit to the NVR.)

Extracted from the proven FRS deps/auth.py + registration/register.py.
"""
from __future__ import annotations

import hmac
import json
import logging
import time
from pathlib import Path

import httpx
from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)

# A blank / shipped-default token leaves every internal route open. Fail CLOSED.
_INSECURE_TOKENS = {"", "dev-ai-service-token", "changeme", "default"}


def service_token_guard(expected_token: str):
    """Build a FastAPI dependency that gates routes behind the shared service
    token. Fails CLOSED (503) if no strong token is configured; constant-time
    compare so the secret can't leak via timing.

    Usage:
        require_token = service_token_guard(config.VIZOR_SERVICE_TOKEN)
        @router.get("/x", dependencies=[Depends(require_token)])
    """
    token_ok = bool(expected_token) and expected_token not in _INSECURE_TOKENS

    def _require(x_vizor_service_token: str | None = Header(None)) -> None:
        if not token_ok:
            raise HTTPException(503, "service token not configured")
        if not x_vizor_service_token or not hmac.compare_digest(
            str(x_vizor_service_token), str(expected_token)
        ):
            raise HTTPException(401, "invalid service token")

    return _require


def allowed_camera_ids(
    x_vizor_allowed_camera_ids: str | None = Header(None),
) -> list[str] | None:
    """Camera scope the NVR proxy forwards. Read routes MUST constrain queries to
    this set so a user can't see data from cameras they aren't assigned to.

    Returns the explicit allowed list, or None when the header is absent (no
    scoping — only outside the proxy, e.g. internal jobs). An empty list means
    "scoped to nothing" -> the route returns no rows.
    """
    if x_vizor_allowed_camera_ids is None:
        return None
    return [c.strip() for c in x_vizor_allowed_camera_ids.split(",") if c.strip()]


class NvrClient:
    """HTTP client for the plugin -> NVR backend direction: manifest registration,
    camera catalogue, event emission. All calls are best-effort and logged; a
    plugin keeps running if the NVR is briefly unreachable."""

    def __init__(self, base_url: str, api_key: str = "", slug: str = "", timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.slug = slug
        self.timeout = timeout

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["X-Vizor-API-Key"] = self.api_key
        return h

    def register_manifest(self, manifest_path: str | Path, attempts: int = 15) -> bool:
        """POST the scenario manifest to the NVR catalog on boot, with backoff.
        Returns True on success. Skips (returns False) if no API key is set."""
        if not self.api_key:
            logger.warning("[%s] VIZOR_API_KEY missing; manifest registration skipped", self.slug)
            return False
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        if self.slug:
            manifest["slug"] = self.slug
        url = f"{self.base_url}/ai/scenarios/register"
        for attempt in range(1, attempts + 1):
            try:
                resp = httpx.post(url, json=manifest, headers=self._headers(), timeout=self.timeout)
                resp.raise_for_status()
                logger.info("[%s] registered manifest (%s)", self.slug, resp.status_code)
                return True
            except Exception as exc:  # noqa: BLE001
                logger.warning("[%s] registration attempt %d failed: %s", self.slug, attempt, exc)
                time.sleep(min(2 * attempt, 20))
        return False

    async def list_cameras(self) -> list[dict]:
        """Fetch the camera catalogue the plugin is licensed to analyse."""
        url = f"{self.base_url}/ai/scenarios/{self.slug}/cameras"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                resp = await c.get(url, headers=self._headers())
                resp.raise_for_status()
                data = resp.json()
                return data.get("items", data) if isinstance(data, dict) else data
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] camera catalogue fetch failed: %s", self.slug, exc)
            return []

    async def emit_event(self, event: dict) -> bool:
        """Push a scenario event to the NVR (for plugins that emit directly rather
        than only persisting locally). Best-effort."""
        url = f"{self.base_url}/ai/scenarios/{self.slug}/events"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                resp = await c.post(url, json=event, headers=self._headers())
                resp.raise_for_status()
                return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] event emit failed: %s", self.slug, exc)
            return False
