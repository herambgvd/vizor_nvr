# =============================================================================
# ONVIF credential helper
# =============================================================================
#
# Centralises decryption of a camera's stored ONVIF username/password so the
# many ONVIF sub-routers don't each have to handle decryption failure.
#
# When the encryption key changes (e.g. JWT_SECRET_KEY rotated, or the host
# machine-fingerprint changed because the container was rebuilt/moved), the
# Fernet token stored at rest can no longer be verified and decrypt_value()
# raises ValueError. Previously that propagated as an unhandled HTTP 500 on
# every ONVIF endpoint (imaging, io, system, ...). Instead we translate it into
# a clear, actionable 424 so the UI can tell the operator to re-enter the
# camera's ONVIF credentials — without ever exposing the secret values.
# =============================================================================

import logging
from typing import Tuple

from fastapi import HTTPException

from app.core.crypto import decrypt_value

logger = logging.getLogger(__name__)

_REENTER_DETAIL = (
    "Stored ONVIF credentials for this camera could not be decrypted. This "
    "usually means the server encryption key changed since the credentials "
    "were saved. Please re-enter the camera's ONVIF username and password in "
    "camera settings."
)


def onvif_credentials(camera, default_user: str = "admin") -> Tuple[str, str]:
    """Return (username, password) for a camera's ONVIF connection.

    Raises HTTPException(424) — instead of letting decrypt_value's ValueError
    surface as a 500 — when the stored ciphertext can't be decrypted with the
    current keys. Secret values are never logged or included in the response.
    """
    try:
        username = decrypt_value(camera.onvif_username) or default_user
        password = decrypt_value(camera.onvif_password or "")
    except ValueError:
        logger.warning(
            "ONVIF credential decryption failed for camera %s; encryption key "
            "likely changed. Credentials must be re-entered.",
            getattr(camera, "id", "?"),
        )
        raise HTTPException(status_code=424, detail=_REENTER_DETAIL)
    return username, password
