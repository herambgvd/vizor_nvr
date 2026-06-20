"""Shared router dependencies.

The service-token guard + camera-scope dependency come from the shared Vizor SDK
(fail-CLOSED + hmac constant-time + insecure-token-set behaviour). Re-exported
under the names every router uses.
"""
from __future__ import annotations

from vizor_sdk import allowed_camera_ids, service_token_guard  # noqa: F401

from config import VIZOR_SERVICE_TOKEN

require_service_token = service_token_guard(VIZOR_SERVICE_TOKEN)
