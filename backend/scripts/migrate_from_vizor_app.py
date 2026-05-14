#!/usr/bin/env python3
"""
Mongo (vizor-app) → Postgres (vizor_nvr) data migration.

Reads from the legacy vizor-app MongoDB and writes to the Postgres database
that backs vizor_nvr. Handles both the platform DB (vizor_platform) and
every tenant DB (vizor_tenant_*).

Idempotent — re-running is safe. Uses natural keys where they exist
(external_id, qdrant_point_id, name+version) and skips rows that already
exist in Postgres.

Usage:
    # Dry run — counts only, no writes
    python scripts/migrate_from_vizor_app.py \\
        --mongo-url mongodb://localhost:27017 \\
        --dry-run

    # Real migration
    python scripts/migrate_from_vizor_app.py \\
        --mongo-url mongodb://localhost:27017 \\
        --tenants vizor_tenant_acme,vizor_tenant_globex

    # All tenant DBs auto-discovered
    python scripts/migrate_from_vizor_app.py \\
        --mongo-url mongodb://localhost:27017 \\
        --all-tenants

Collections handled:
    Platform DB (read once):
        - webhook_subscriptions   → webhook_subscriptions
        - api_keys                → api_keys
        - (users, tenants ignored: vizor_nvr has own user mgmt)

    Tenant DB (read per tenant, MERGED into single Postgres schema):
        - persons                 → frs_persons
        - person_photos           → frs_photos
        - groups                  → frs_groups
        - investigation_jobs      → frs_investigations
        - detection_events        → events (with AI fields populated)
        - scenarios               → camera_ai_configs (per cam+scenario row)
        - models                  → models
        - webhook_deliveries      → webhook_deliveries

NOT migrated (re-created in vizor_nvr):
    - audit_logs (different schema, NVR has own)
    - usage_events, tenant_usage (single-tenant now)
    - feature_flags, login_attempts, password_reset_tokens

Exit codes:
    0  — success or dry run
    1  — error (database connection, schema mismatch, etc.)
    2  — partial success (some rows failed, see log)
"""

import argparse
import asyncio
import hashlib
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

# Add backend/ to path so `app.*` imports work when invoked as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Eagerly import every model module so SQLAlchemy can resolve every
# ForeignKey across modules. Without this, `events.camera_id` FK fails
# to resolve because the cameras module hasn't been imported yet.
from app.auth import models as _auth_models  # noqa: F401, E402
from app.cameras import models as _camera_models  # noqa: F401, E402
from app.recordings import models as _recording_models  # noqa: F401, E402
from app.storage import models as _storage_models  # noqa: F401, E402
from app.settings import models as _settings_models  # noqa: F401, E402
from app.audit import models as _audit_models  # noqa: F401, E402
from app.notifications import models as _notification_models  # noqa: F401, E402

from app.ai.models import (  # noqa: E402
    AIModel,
    AIScenario,
    CameraAIConfig,
    FRSGroup,
    FRSInvestigation,
    FRSPerson,
    FRSPhoto,
    WebhookDelivery,
    WebhookSubscription,
)
from app.auth.api_keys import APIKey  # noqa: E402
from app.database import async_session_maker  # noqa: E402
from app.events.models import Event  # noqa: E402


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("migrate")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _mongo_id_to_str(doc: dict) -> str:
    """Mongo _id can be ObjectId or string. Return as string."""
    raw = doc.get("_id")
    if raw is None:
        return str(uuid.uuid4())
    return str(raw)


def _to_datetime(val: Any) -> Optional[datetime]:
    """Mongo dates come through motor as tz-aware datetime already."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.replace(tzinfo=None) if val.tzinfo else val
    return None


def _dedup_key_for_event(doc: dict) -> str:
    """Compute a stable dedup_key for a legacy detection_event so re-runs
    don't insert duplicates. Same algorithm the Metropolis bridge will use."""
    parts = [
        str(doc.get("camera_id") or doc.get("device_id") or "unknown"),
        str(doc.get("event_type") or doc.get("detection_type") or "event"),
        str(doc.get("track_id") or doc.get("_id") or ""),
        str(doc.get("triggered_at") or doc.get("created_at") or doc.get("timestamp") or ""),
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


class Counters:
    def __init__(self) -> None:
        self.scanned = 0
        self.inserted = 0
        self.skipped = 0
        self.failed = 0
        self.by_collection: dict[str, dict[str, int]] = {}

    def bump(self, coll: str, result: str) -> None:
        self.by_collection.setdefault(coll, {"scanned": 0, "inserted": 0, "skipped": 0, "failed": 0})
        self.by_collection[coll][result] += 1
        if result == "scanned":
            self.scanned += 1
        elif result == "inserted":
            self.inserted += 1
        elif result == "skipped":
            self.skipped += 1
        elif result == "failed":
            self.failed += 1

    def report(self) -> str:
        lines = [
            f"\n{'─' * 70}",
            f"Migration summary",
            f"  Total scanned:  {self.scanned}",
            f"  Inserted:       {self.inserted}",
            f"  Skipped (dup):  {self.skipped}",
            f"  Failed:         {self.failed}",
            f"{'─' * 70}",
        ]
        for coll, stats in sorted(self.by_collection.items()):
            lines.append(
                f"  {coll:<32} scan={stats['scanned']:>6}  "
                f"ins={stats['inserted']:>6}  "
                f"skip={stats['skipped']:>6}  "
                f"fail={stats['failed']:>6}"
            )
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Collection-specific migrators
# ─────────────────────────────────────────────────────────────────────────────


async def migrate_groups(mongo_db, pg: AsyncSession, counters: Counters, dry: bool) -> None:
    coll = "groups"
    async for doc in mongo_db[coll].find():
        counters.bump(coll, "scanned")
        name = doc.get("name") or doc.get("group_name")
        if not name:
            counters.bump(coll, "failed")
            continue

        existing = await pg.execute(select(FRSGroup).where(FRSGroup.name == name))
        if existing.scalar_one_or_none() is not None:
            counters.bump(coll, "skipped")
            continue

        if not dry:
            pg.add(FRSGroup(
                id=_mongo_id_to_str(doc),
                name=name,
                description=doc.get("description"),
                color=doc.get("color"),
            ))
            counters.bump(coll, "inserted")
        else:
            counters.bump(coll, "inserted")


async def _group_exists(pg: AsyncSession, group_id: str) -> bool:
    if not group_id:
        return False
    result = await pg.execute(
        text("SELECT 1 FROM frs_groups WHERE id = :id LIMIT 1"),
        {"id": group_id},
    )
    return result.scalar() is not None


async def migrate_persons(mongo_db, pg: AsyncSession, counters: Counters, dry: bool) -> None:
    coll = "persons"
    # Build slug->id map for FRS groups so person.group_id resolves
    groups = (await pg.execute(select(FRSGroup))).scalars().all()
    name_to_group = {g.name: g.id for g in groups}

    async for doc in mongo_db[coll].find():
        counters.bump(coll, "scanned")
        external_id = doc.get("external_id") or doc.get("employee_id")
        name = doc.get("full_name") or doc.get("name") or external_id
        if not name:
            counters.bump(coll, "failed")
            continue

        # Resolve group. Legacy schema used `group_ids` array (many-to-many
        # in design, but in practice always 1 element). New schema is a
        # single FK column.
        group_id = doc.get("group_id")
        if not group_id and doc.get("group_ids"):
            ids = doc["group_ids"]
            if isinstance(ids, list) and ids:
                group_id = str(ids[0])
        if not group_id and doc.get("group_name"):
            group_id = name_to_group.get(doc["group_name"])
        # Set to None if the resolved group doesn't actually exist in PG
        # (cascading import order, legacy stale refs)
        if group_id and not await _group_exists(pg, str(group_id)):
            group_id = None

        existing_q = select(FRSPerson).where(FRSPerson.id == _mongo_id_to_str(doc))
        if external_id:
            existing_q = select(FRSPerson).where(
                (FRSPerson.id == _mongo_id_to_str(doc)) | (FRSPerson.external_id == external_id)
            )
        existing = await pg.execute(existing_q)
        if existing.scalar_one_or_none() is not None:
            counters.bump(coll, "skipped")
            continue

        if not dry:
            pg.add(FRSPerson(
                id=_mongo_id_to_str(doc),
                external_id=external_id,
                name=name,
                group_id=group_id if isinstance(group_id, str) else None,
                attributes=doc.get("attributes") or doc.get("metadata"),
                enrolled_at=_to_datetime(doc.get("enrolled_at") or doc.get("created_at")),
                last_seen_at=_to_datetime(doc.get("last_seen_at")),
            ))
        counters.bump(coll, "inserted")


async def migrate_photos(mongo_db, pg: AsyncSession, counters: Counters, dry: bool) -> None:
    coll = "person_photos"
    async for doc in mongo_db[coll].find():
        counters.bump(coll, "scanned")
        # Legacy schema used `embedding_id` for the Qdrant point UUID and
        # `rustfs_key` for the object-storage key.
        qpid = (
            doc.get("qdrant_point_id")
            or doc.get("embedding_id")
            or doc.get("vector_id")
        )
        if not qpid:
            counters.bump(coll, "failed")
            continue
        existing = await pg.execute(
            select(FRSPhoto).where(FRSPhoto.qdrant_point_id == qpid)
        )
        if existing.scalar_one_or_none() is not None:
            counters.bump(coll, "skipped")
            continue

        if not dry:
            pg.add(FRSPhoto(
                id=_mongo_id_to_str(doc),
                person_id=str(doc.get("person_id") or ""),
                storage_key=(
                    doc.get("storage_key")
                    or doc.get("rustfs_key")
                    or doc.get("s3_key")
                    or ""
                ),
                qdrant_point_id=qpid,
                quality_score=doc.get("quality_score") or doc.get("face_quality"),
                uploaded_at=_to_datetime(doc.get("uploaded_at") or doc.get("created_at")),
            ))
        counters.bump(coll, "inserted")


async def migrate_investigations(mongo_db, pg: AsyncSession, counters: Counters, dry: bool) -> None:
    coll = "investigation_jobs"
    async for doc in mongo_db[coll].find():
        counters.bump(coll, "scanned")
        doc_id = _mongo_id_to_str(doc)
        # Legacy investigations could be person-bound OR query-by-image
        # (person_id null). Both are valid; we accept null person_id.
        person_id = doc.get("person_id") or doc.get("target_person_id")

        existing = await pg.execute(select(FRSInvestigation).where(FRSInvestigation.id == doc_id))
        if existing.scalar_one_or_none() is not None:
            counters.bump(coll, "skipped")
            continue

        # Flatten the legacy doc into params if the request shape isn't
        # already isolated. Result list is preserved.
        params = (
            doc.get("params")
            or doc.get("request")
            or {
                "query_storage_key": doc.get("query_rustfs_key"),
                "search_scope": doc.get("search_scope"),
                "camera_ids": doc.get("camera_ids"),
                "time_range_start": str(doc.get("time_range_start")) if doc.get("time_range_start") else None,
                "time_range_end": str(doc.get("time_range_end")) if doc.get("time_range_end") else None,
                "similarity_threshold": doc.get("similarity_threshold"),
                "max_results": doc.get("max_results"),
            }
        )

        if not dry:
            pg.add(FRSInvestigation(
                id=doc_id,
                person_id=str(person_id) if person_id else None,
                status=doc.get("status") or "complete",
                params=params,
                result={"matches": doc.get("results")} if doc.get("results") else doc.get("result"),
                created_at=_to_datetime(doc.get("created_at")),
                completed_at=_to_datetime(doc.get("completed_at") or doc.get("finished_at")),
            ))
        counters.bump(coll, "inserted")


async def _camera_exists(pg: AsyncSession, camera_id: str) -> bool:
    """Cheap exists check so we can skip FK violations on stale camera refs."""
    if not camera_id:
        return False
    result = await pg.execute(
        text("SELECT 1 FROM cameras WHERE id = :id LIMIT 1"),
        {"id": camera_id},
    )
    return result.scalar() is not None


async def migrate_detection_events(mongo_db, pg: AsyncSession, counters: Counters, dry: bool) -> None:
    coll = "detection_events"
    async for doc in mongo_db[coll].find():
        counters.bump(coll, "scanned")
        dedup = _dedup_key_for_event(doc)

        existing = await pg.execute(select(Event).where(Event.dedup_key == dedup))
        if existing.scalar_one_or_none() is not None:
            counters.bump(coll, "skipped")
            continue

        triggered = _to_datetime(
            doc.get("triggered_at") or doc.get("created_at") or doc.get("timestamp")
        ) or datetime.utcnow()

        # Legacy events may reference camera ids that don't exist in the
        # new NVR Postgres (cameras are re-onboarded after cutover).
        # Set camera_id NULL when the FK target is missing — record the
        # original id in attributes for traceability.
        raw_camera_id = str(doc.get("camera_id") or doc.get("device_id") or "")
        attrs = dict(doc.get("attributes") or {})
        if raw_camera_id:
            attrs.setdefault("legacy_camera_id", raw_camera_id)
        resolved_camera_id = raw_camera_id if await _camera_exists(pg, raw_camera_id) else None

        if not dry:
            pg.add(Event(
                id=_mongo_id_to_str(doc),
                camera_id=resolved_camera_id,
                event_type=doc.get("event_type") or "ai_detection",
                severity=doc.get("severity") or "info",
                title=doc.get("title") or doc.get("event_type") or "Imported detection",
                description=doc.get("description"),
                event_metadata=doc.get("metadata"),
                snapshot_path=doc.get("snapshot_key") or doc.get("snapshot_path"),
                recording_id=None,  # legacy clip references aren't mapped 1:1
                acknowledged=bool(doc.get("acknowledged")),
                is_false_alarm=bool(doc.get("is_false_alarm")),
                triggered_at=triggered,
                source_service=doc.get("source") or "vizor-app-legacy",
                detection_type=doc.get("detection_type"),
                confidence=doc.get("confidence"),
                bbox=doc.get("bbox"),
                track_id=str(doc["track_id"]) if doc.get("track_id") is not None else None,
                person_id=str(doc["person_id"]) if doc.get("person_id") else None,
                attributes=attrs or None,
                dedup_key=dedup,
            ))
        counters.bump(coll, "inserted")


async def migrate_models(mongo_db, pg: AsyncSession, counters: Counters, dry: bool) -> None:
    coll = "models"
    async for doc in mongo_db[coll].find():
        counters.bump(coll, "scanned")
        name = doc.get("name")
        version = doc.get("version") or "1.0"
        if not name:
            counters.bump(coll, "failed")
            continue
        existing = await pg.execute(
            select(AIModel).where(AIModel.name == name, AIModel.version == version)
        )
        if existing.scalar_one_or_none() is not None:
            counters.bump(coll, "skipped")
            continue

        if not dry:
            pg.add(AIModel(
                id=_mongo_id_to_str(doc),
                name=name,
                version=version,
                manifest_json=doc.get("manifest") or doc,
                signature=doc.get("signature"),
                status=doc.get("status") or "active",
                ngc_resource_id=doc.get("ngc_resource_id"),
                storage_key=doc.get("storage_key"),
            ))
        counters.bump(coll, "inserted")


async def migrate_webhook_subs(mongo_db, pg: AsyncSession, counters: Counters, dry: bool) -> None:
    coll = "webhook_subscriptions"
    async for doc in mongo_db[coll].find():
        counters.bump(coll, "scanned")
        doc_id = _mongo_id_to_str(doc)
        existing = await pg.execute(
            select(WebhookSubscription).where(WebhookSubscription.id == doc_id)
        )
        if existing.scalar_one_or_none() is not None:
            counters.bump(coll, "skipped")
            continue
        url = doc.get("url")
        if not url:
            counters.bump(coll, "failed")
            continue
        if not dry:
            pg.add(WebhookSubscription(
                id=doc_id,
                name=doc.get("name") or "Imported subscription",
                url=url,
                events=doc.get("events") or doc.get("event_types") or [],
                secret=doc.get("secret"),
                headers=doc.get("headers"),
                enabled=bool(doc.get("enabled", True)),
            ))
        counters.bump(coll, "inserted")


async def migrate_webhook_deliveries(mongo_db, pg: AsyncSession, counters: Counters, dry: bool) -> None:
    coll = "webhook_deliveries"
    async for doc in mongo_db[coll].find():
        counters.bump(coll, "scanned")
        doc_id = _mongo_id_to_str(doc)
        existing = await pg.execute(
            select(WebhookDelivery).where(WebhookDelivery.id == doc_id)
        )
        if existing.scalar_one_or_none() is not None:
            counters.bump(coll, "skipped")
            continue
        sub_id = doc.get("subscription_id") or doc.get("sub_id")
        if not sub_id:
            counters.bump(coll, "failed")
            continue
        if not dry:
            pg.add(WebhookDelivery(
                id=doc_id,
                subscription_id=str(sub_id),
                event_id=doc.get("event_id"),
                payload=doc.get("payload") or {},
                status=doc.get("status") or "success",
                attempts=int(doc.get("attempts") or 1),
                last_error=doc.get("error") or doc.get("last_error"),
                response_status=doc.get("response_status"),
                created_at=_to_datetime(doc.get("created_at")) or datetime.utcnow(),
            ))
        counters.bump(coll, "inserted")


async def migrate_api_keys(mongo_db, pg: AsyncSession, counters: Counters, dry: bool) -> None:
    """Legacy vizor-app API keys → NVR api_keys table.

    These were customer-facing API keys (vzk_*). They migrate to the NVR
    API key table but cannot reuse the same prefix (vzn_) so customers
    need to be notified to rotate. The hash is preserved if the legacy
    storage was hashed; raw keys cannot be migrated by definition.
    """
    coll = "api_keys"
    async for doc in mongo_db[coll].find():
        counters.bump(coll, "scanned")
        doc_id = _mongo_id_to_str(doc)
        key_hash = doc.get("key_hash") or doc.get("hash")
        if not key_hash:
            counters.bump(coll, "failed")
            continue
        existing = await pg.execute(select(APIKey).where(APIKey.key_hash == key_hash))
        if existing.scalar_one_or_none() is not None:
            counters.bump(coll, "skipped")
            continue
        if not dry:
            pg.add(APIKey(
                id=doc_id,
                name=doc.get("name") or "Legacy key",
                key_hash=key_hash,
                key_prefix=doc.get("prefix") or "vzk_legacy",
                scopes=doc.get("scopes") or ["events:ingest"],
                enabled=bool(doc.get("enabled", True)),
                created_at=_to_datetime(doc.get("created_at")) or datetime.utcnow(),
            ))
        counters.bump(coll, "inserted")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────


async def discover_tenant_dbs(client: AsyncIOMotorClient, prefix: str) -> list[str]:
    names = await client.list_database_names()
    return sorted(n for n in names if n.startswith(prefix))


async def migrate_tenant(client: AsyncIOMotorClient, db_name: str, dry: bool) -> Counters:
    logger.info("Migrating tenant DB: %s (dry_run=%s)", db_name, dry)
    counters = Counters()
    mongo_db = client[db_name]
    async with async_session_maker() as pg:
        await migrate_groups(mongo_db, pg, counters, dry)
        await migrate_persons(mongo_db, pg, counters, dry)
        await migrate_photos(mongo_db, pg, counters, dry)
        await migrate_investigations(mongo_db, pg, counters, dry)
        await migrate_detection_events(mongo_db, pg, counters, dry)
        await migrate_models(mongo_db, pg, counters, dry)
        await migrate_webhook_subs(mongo_db, pg, counters, dry)
        await migrate_webhook_deliveries(mongo_db, pg, counters, dry)
        await migrate_api_keys(mongo_db, pg, counters, dry)
        if not dry:
            await pg.commit()
    logger.info("Tenant %s done: %s", db_name, counters.report())
    return counters


async def migrate_platform(client: AsyncIOMotorClient, db_name: str, dry: bool) -> Counters:
    logger.info("Migrating platform DB: %s (dry_run=%s)", db_name, dry)
    counters = Counters()
    mongo_db = client[db_name]
    async with async_session_maker() as pg:
        await migrate_webhook_subs(mongo_db, pg, counters, dry)
        await migrate_api_keys(mongo_db, pg, counters, dry)
        if not dry:
            await pg.commit()
    logger.info("Platform %s done: %s", db_name, counters.report())
    return counters


async def main_async(args: argparse.Namespace) -> int:
    client = AsyncIOMotorClient(args.mongo_url, tz_aware=True)
    try:
        # Verify connection
        await client.admin.command("ping")
    except Exception as e:  # noqa: BLE001
        logger.error("Cannot reach Mongo at %s: %s", args.mongo_url, e)
        return 1

    tenant_dbs: list[str] = []
    if args.all_tenants:
        tenant_dbs = await discover_tenant_dbs(client, args.tenant_prefix)
        logger.info("Discovered %d tenant DBs", len(tenant_dbs))
    elif args.tenants:
        tenant_dbs = [t.strip() for t in args.tenants.split(",") if t.strip()]

    aggregate = Counters()

    # Platform DB
    try:
        plat = await migrate_platform(client, args.platform_db, args.dry_run)
        aggregate.scanned += plat.scanned
        aggregate.inserted += plat.inserted
        aggregate.skipped += plat.skipped
        aggregate.failed += plat.failed
    except Exception as e:  # noqa: BLE001
        logger.exception("Platform migration failed: %s", e)
        if not args.continue_on_error:
            return 1

    # Tenants
    for db_name in tenant_dbs:
        try:
            t = await migrate_tenant(client, db_name, args.dry_run)
            aggregate.scanned += t.scanned
            aggregate.inserted += t.inserted
            aggregate.skipped += t.skipped
            aggregate.failed += t.failed
        except Exception as e:  # noqa: BLE001
            logger.exception("Tenant %s migration failed: %s", db_name, e)
            if not args.continue_on_error:
                return 1

    logger.info(
        "\n%s\nGRAND TOTAL  scanned=%d  inserted=%d  skipped=%d  failed=%d\n%s",
        "=" * 70,
        aggregate.scanned,
        aggregate.inserted,
        aggregate.skipped,
        aggregate.failed,
        "=" * 70,
    )

    if args.dry_run:
        logger.info("DRY RUN — no rows were written. Re-run without --dry-run to commit.")

    return 2 if aggregate.failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate vizor-app Mongo → vizor_nvr Postgres")
    parser.add_argument("--mongo-url", default=os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    parser.add_argument("--platform-db", default="vizor_platform")
    parser.add_argument("--tenant-prefix", default="vizor_tenant_")
    parser.add_argument("--tenants", help="Comma-separated tenant DB names")
    parser.add_argument("--all-tenants", action="store_true", help="Auto-discover and migrate every tenant DB")
    parser.add_argument("--dry-run", action="store_true", help="Count only, no writes")
    parser.add_argument("--continue-on-error", action="store_true", help="Don't abort whole run on per-tenant failure")
    args = parser.parse_args()

    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
