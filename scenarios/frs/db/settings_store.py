"""FRS feature settings — the singleton config row (public dashboard + ingest
API toggles + ingest API key). One helper to read/update, creating the row on
first access."""
from __future__ import annotations

import secrets

from db import session
from db.models import FRSSettings

_SINGLETON_ID = "singleton"


def get_settings() -> dict:
    """Return the settings as a plain dict, creating the row if absent."""
    with session() as s:
        row = s.get(FRSSettings, _SINGLETON_ID)
        if row is None:
            row = FRSSettings(id=_SINGLETON_ID)
            s.add(row)
            s.commit()
            s.refresh(row)
        return {
            "public_dashboard_enabled": bool(row.public_dashboard_enabled),
            "ingest_api_enabled": bool(row.ingest_api_enabled),
            "ingest_api_key": row.ingest_api_key,
            "public_show_names": bool(row.public_show_names),
        }


def update_settings(**patch) -> dict:
    """Update allowed fields. Generates an ingest_api_key when ingest is turned on
    and none exists yet."""
    allowed = {"public_dashboard_enabled", "ingest_api_enabled",
               "public_show_names", "ingest_api_key"}
    with session() as s:
        row = s.get(FRSSettings, _SINGLETON_ID)
        if row is None:
            row = FRSSettings(id=_SINGLETON_ID)
            s.add(row)
        for k, v in patch.items():
            if k in allowed:
                setattr(row, k, v)
        # Mint a key the first time ingest is enabled.
        if patch.get("ingest_api_enabled") and not row.ingest_api_key:
            row.ingest_api_key = "frsk_" + secrets.token_urlsafe(32)
        s.commit()
    return get_settings()


def rotate_ingest_key() -> str:
    """Generate a fresh ingest API key, invalidating the old one."""
    new_key = "frsk_" + secrets.token_urlsafe(32)
    with session() as s:
        row = s.get(FRSSettings, _SINGLETON_ID)
        if row is None:
            row = FRSSettings(id=_SINGLETON_ID)
            s.add(row)
        row.ingest_api_key = new_key
        s.commit()
    return new_key


def verify_ingest_key(presented: str | None) -> bool:
    """Constant-time check of a presented ingest key against the stored one.
    Returns False if ingest is disabled or no key is set."""
    import hmac

    st = get_settings()
    if not st["ingest_api_enabled"] or not st["ingest_api_key"]:
        return False
    return bool(presented) and hmac.compare_digest(str(presented), str(st["ingest_api_key"]))
