"""ANPR feature settings — the singleton config row (region/regex, raw-read +
low-light toggles, det/ocr thresholds, speed). One helper to read/update,
creating the row on first access."""
from __future__ import annotations

import config
from db import session
from db.models import ANPRSettings

_SINGLETON_ID = "singleton"

_ALLOWED = {
    "region", "plate_regex", "allow_raw_reads", "lowlight_enhance",
    "det_conf", "ocr_conf", "min_plate_w", "min_reads", "speed_enabled",
}


def get_settings() -> dict:
    """Return the settings as a plain dict, creating the row if absent. Falls back
    to the platform (env) defaults for any unset field."""
    with session() as s:
        row = s.get(ANPRSettings, _SINGLETON_ID)
        if row is None:
            row = ANPRSettings(
                id=_SINGLETON_ID,
                region=config.PLATE_REGION,
                plate_regex=config.PLATE_REGEX,
                allow_raw_reads=config.ALLOW_RAW_READS,
                lowlight_enhance=config.LOWLIGHT_ENHANCE,
                speed_enabled=config.SPEED_ENABLED_DEFAULT,
            )
            s.add(row)
            s.commit()
            s.refresh(row)
        return {
            "region": row.region or config.PLATE_REGION,
            "plate_regex": row.plate_regex or config.PLATE_REGEX,
            "allow_raw_reads": bool(row.allow_raw_reads),
            "lowlight_enhance": bool(row.lowlight_enhance),
            "det_conf": row.det_conf if row.det_conf is not None else config.DET_CONF,
            "ocr_conf": row.ocr_conf if row.ocr_conf is not None else config.OCR_CONF,
            "min_plate_w": row.min_plate_w if row.min_plate_w is not None else config.MIN_PLATE_W,
            "min_reads": row.min_reads if row.min_reads is not None else config.MIN_READS,
            "speed_enabled": bool(row.speed_enabled),
        }


def update_settings(**patch) -> dict:
    """Update allowed fields."""
    with session() as s:
        row = s.get(ANPRSettings, _SINGLETON_ID)
        if row is None:
            row = ANPRSettings(id=_SINGLETON_ID)
            s.add(row)
        for k, v in patch.items():
            if k in _ALLOWED:
                setattr(row, k, v)
        s.commit()
    return get_settings()
