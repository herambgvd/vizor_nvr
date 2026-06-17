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

# Static catalog. All current scenarios (frs, ppe, suspect-search) ship as
# standalone microservices under scenarios/ and self-register their manifest via
# POST /api/ai/scenarios/register on boot, so the seed catalog is intentionally
# empty. Add an entry here only for a scenario the NVR must know about before any
# plugin has registered (a builtin bootstrap fallback).
CATALOG: list[dict] = []


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
