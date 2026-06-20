from __future__ import annotations

# Service-token gate via the shared Vizor SDK. Fails CLOSED (503) when no strong
# token is configured + constant-time compare — hardens the prior local check
# that let blank tokens through. Same `require_service_token` name so the routers
# (Depends(require_service_token)) are unchanged.
from vizor_sdk import allowed_camera_ids, service_token_guard

from config.settings import VIZOR_SERVICE_TOKEN

require_service_token = service_token_guard(VIZOR_SERVICE_TOKEN)

__all__ = ["require_service_token", "allowed_camera_ids"]
