# =============================================================================
# AI scenario catalog seed. Runs at startup (idempotent upsert by slug).
#
# Catalog = the set of scenarios the NVR knows how to drive. `licensed` is
# (re)derived from the signed license `features` on every boot by
# `sync_licensing()`; the seed only ensures the rows + static metadata exist.
# =============================================================================
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AIScenario

logger = logging.getLogger(__name__)

# Static catalog. `grpc_endpoint` is the standalone scenario service address
# (overridable via env on the bridge, not here). `module_tabs` drives the UI.
CATALOG = [
    {
        "slug": "frs",
        "name": "Face Recognition",
        "description": "Detect, recognize and track enrolled faces. Liveness, "
                       "watchlist alerts, attendance and forensic search.",
        "category": "security",
        "icon": "scan-face",
        "grpc_endpoint": "frs:50051",
        "module_tabs": ["cameras", "live", "events", "groups", "persons",
                        "recognize", "investigate", "transit", "attendance",
                        "tour", "reports"],
        "event_types": ["face_recognized", "face_unknown", "spoof_detected"],
        "camera_config_schema": {
            "fields": [
                # ── Recognition ──────────────────────────────────────────
                {"key": "min_confidence", "type": "float", "label": "Match threshold",
                 "group": "Recognition", "default": 0.6, "min": 0.3, "max": 0.99, "step": 0.01,
                 "help": "Minimum cosine similarity to call a face a known person."},
                {"key": "recognition_enabled", "type": "bool", "label": "Recognition",
                 "group": "Recognition", "default": True,
                 "help": "Match faces against the enrolled gallery."},
                {"key": "detection_enabled", "type": "bool", "label": "Detection only",
                 "group": "Recognition", "default": False,
                 "help": "Emit face-detected events without identifying."},
                # ── Liveness / anti-spoof ────────────────────────────────
                {"key": "liveness_enabled", "type": "bool", "label": "Anti-spoof",
                 "group": "Liveness", "default": True},
                {"key": "liveness_threshold", "type": "float", "label": "Liveness threshold",
                 "group": "Liveness", "default": 0.7, "min": 0.3, "max": 0.99, "step": 0.01},
                # ── Quality gates ────────────────────────────────────────
                {"key": "min_face_px", "type": "int", "label": "Min face size (px)",
                 "group": "Quality", "default": 80, "min": 20, "max": 400, "step": 10},
                {"key": "dwell_min_frames", "type": "int", "label": "Dwell frames",
                 "group": "Quality", "default": 5, "min": 1, "max": 30, "step": 1,
                 "help": "Frames a track must persist before an event fires."},
                # ── Alerting ─────────────────────────────────────────────
                {"key": "alert_suppress_seconds", "type": "int", "label": "Alert cooldown (s)",
                 "group": "Alerting", "default": 300, "min": 0, "max": 3600, "step": 30,
                 "help": "Minimum gap between repeat alerts for the same person."},
                # ── Stream ───────────────────────────────────────────────
                {"key": "fps", "type": "int", "label": "Analyze FPS",
                 "group": "Stream", "default": 5, "min": 1, "max": 15, "step": 1},
                {"key": "roi", "type": "roi", "label": "Region of interest",
                 "group": "Stream"},
            ]
        },
    },
    {
        "slug": "ppe",
        "name": "PPE Compliance",
        "description": "Detect personal protective equipment per worker — helmet, "
                       "vest, mask, gloves, goggles, shoes — and flag violations.",
        "category": "safety",
        "icon": "hard-hat",
        "grpc_endpoint": "ppe:50052",
        "module_tabs": ["cameras", "ppe_detect", "live", "events", "reports"],
        "event_types": ["ppe_violation", "ppe_compliant"],
        "camera_config_schema": {
            "fields": [
                # ── Compliance ───────────────────────────────────────────
                {"key": "required_ppe", "type": "multiselect", "label": "Required PPE",
                 "group": "Compliance",
                 "options": ["helmet", "vest", "mask", "gloves", "goggles", "safety_shoe"],
                 "default": ["helmet", "vest"],
                 "help": "A worker missing any of these is flagged non-compliant."},
                {"key": "min_confidence", "type": "float", "label": "Detection threshold",
                 "group": "Compliance", "default": 0.35, "min": 0.2, "max": 0.9, "step": 0.01},
                # ── Quality gates ────────────────────────────────────────
                {"key": "min_person_px", "type": "int", "label": "Min person size (px)",
                 "group": "Quality", "default": 60, "min": 20, "max": 400, "step": 10},
                {"key": "dwell_min_frames", "type": "int", "label": "Dwell frames",
                 "group": "Quality", "default": 4, "min": 1, "max": 30, "step": 1},
                # ── Alerting ─────────────────────────────────────────────
                {"key": "alert_suppress_seconds", "type": "int", "label": "Alert cooldown (s)",
                 "group": "Alerting", "default": 300, "min": 0, "max": 3600, "step": 30},
                # ── Stream ───────────────────────────────────────────────
                {"key": "fps", "type": "int", "label": "Analyze FPS",
                 "group": "Stream", "default": 4, "min": 1, "max": 15, "step": 1},
                {"key": "roi", "type": "roi", "label": "Region of interest",
                 "group": "Stream"},
            ]
        },
    },
]


async def seed_scenarios(db: AsyncSession) -> None:
    """BOOTSTRAP fallback only. The catalog is now manifest-driven (scenarios
    register via POST /api/ai/scenarios/register — see core/registry.py). This
    seed just guarantees the builtin scenarios EXIST on a fresh DB so the system
    is usable before any manifest is registered.

    Non-destructive: a row already sourced from a manifest (`source=="manifest"`)
    is left untouched — the live plugin manifest wins over the static seed."""
    for entry in CATALOG:
        row = (await db.execute(
            select(AIScenario).where(AIScenario.slug == entry["slug"])
        )).scalar_one_or_none()
        if row is None:
            db.add(AIScenario(source="builtin", **entry))
            logger.info("[ai-seed] bootstrap created scenario %s", entry["slug"])
        elif row.source != "manifest":
            # Refresh static metadata on builtin rows only; never clobber a
            # manifest-registered plugin or operator state.
            for k in ("name", "description", "category", "icon", "grpc_endpoint",
                      "module_tabs", "event_types", "camera_config_schema"):
                setattr(row, k, entry[k])
    await db.commit()
