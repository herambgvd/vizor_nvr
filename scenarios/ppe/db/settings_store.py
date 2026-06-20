"""PPE feature settings — the singleton config row (default required PPE +
temporal thresholds + whether to emit positive compliant events). One helper to
read/update, creating the row on first access."""
from __future__ import annotations

import config
from db import session
from db.models import PPESettings

_SINGLETON_ID = "singleton"


def get_settings() -> dict:
    """Return the settings as a plain dict, creating the row if absent. Falls back
    to the platform (env) defaults for any unset field."""
    with session() as s:
        row = s.get(PPESettings, _SINGLETON_ID)
        if row is None:
            row = PPESettings(id=_SINGLETON_ID, required_ppe=list(config.REQUIRED_PPE_DEFAULT))
            s.add(row)
            s.commit()
            s.refresh(row)
        return {
            "required_ppe": row.required_ppe or list(config.REQUIRED_PPE_DEFAULT),
            "emit_compliant": bool(row.emit_compliant),
            "missing_grace": row.missing_grace if row.missing_grace is not None else config.MISSING_GRACE,
            "min_present": row.min_present if row.min_present is not None else config.MIN_PRESENT,
            "cooldown": row.cooldown if row.cooldown is not None else config.COOLDOWN,
        }


def update_settings(**patch) -> dict:
    """Update allowed fields."""
    allowed = {"required_ppe", "emit_compliant", "missing_grace", "min_present", "cooldown"}
    with session() as s:
        row = s.get(PPESettings, _SINGLETON_ID)
        if row is None:
            row = PPESettings(id=_SINGLETON_ID)
            s.add(row)
        for k, v in patch.items():
            if k in allowed:
                setattr(row, k, v)
        s.commit()
    return get_settings()
