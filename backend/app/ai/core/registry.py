# =============================================================================
# Scenario registry — register a self-describing scenario from its manifest.
#
# A scenario plugin ships a `scenario.json` manifest. Registering it upserts an
# `ai_scenarios` catalog row from the manifest's static metadata, WITHOUT
# touching operator/licensing state (enabled / camera_limit / licensed). After
# upsert we re-project the signed license so a just-registered scenario whose
# `license_feature` is already entitled flips `licensed=true` immediately.
#
# This replaces the hardcoded seed CATALOG as the source of truth: scenarios
# self-register on boot, or the bridge registers manifests from a scenarios.d/
# directory. The seed remains only as a builtin bootstrap fallback.
# =============================================================================
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AIScenario

logger = logging.getLogger("app.ai.registry")

# Manifest keys copied verbatim onto the catalog row (static metadata only).
_METADATA_KEYS = (
    "name", "description", "category", "icon", "grpc_endpoint",
    "module_tabs", "event_types", "camera_config_schema",
    "version", "capabilities", "license_feature",
)
_REQUIRED = ("slug", "name")


class ManifestError(ValueError):
    """Raised when a scenario manifest is malformed."""


def validate_manifest(manifest: Dict[str, Any]) -> None:
    if not isinstance(manifest, dict):
        raise ManifestError("manifest must be an object")
    for k in _REQUIRED:
        if not manifest.get(k):
            raise ManifestError(f"manifest missing required field: {k}")
    slug = manifest["slug"]
    if not isinstance(slug, str) or not slug.isidentifier() and "-" not in slug:
        # allow kebab/identifier-ish slugs
        if not all(c.isalnum() or c in "-_" for c in slug):
            raise ManifestError(f"invalid slug: {slug!r}")


async def register_manifest(db: AsyncSession, manifest: Dict[str, Any]) -> AIScenario:
    """Upsert a scenario catalog row from a manifest. Preserves operator state.
    Does NOT commit — caller commits (so it can batch + re-sync licensing)."""
    validate_manifest(manifest)
    slug = manifest["slug"]
    # default license_feature to the slug when the manifest omits it.
    manifest.setdefault("license_feature", slug)

    row = (await db.execute(
        select(AIScenario).where(AIScenario.slug == slug)
    )).scalar_one_or_none()

    # naive UTC — ai_scenarios timestamps are TIMESTAMP WITHOUT TIME ZONE.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if row is None:
        row = AIScenario(slug=slug)
        db.add(row)
        logger.info("[ai-registry] registering new scenario %s v%s",
                    slug, manifest.get("version"))
    else:
        logger.info("[ai-registry] re-registering scenario %s v%s",
                    slug, manifest.get("version"))

    for k in _METADATA_KEYS:
        if k in manifest:
            setattr(row, k, manifest[k])
    row.manifest = manifest
    row.source = "manifest"
    row.registered = True
    row.registered_at = now
    return row


async def unregister(db: AsyncSession, slug: str) -> bool:
    """Soft-unregister: mark the scenario uninstalled but keep the row + its
    per-camera config (so re-install restores state). Returns False if unknown."""
    row = (await db.execute(
        select(AIScenario).where(AIScenario.slug == slug)
    )).scalar_one_or_none()
    if row is None:
        return False
    row.registered = False
    row.enabled = False
    await db.commit()
    logger.info("[ai-registry] unregistered scenario %s", slug)
    return True
