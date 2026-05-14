# =============================================================================
# Event Ingest Router — Machine-to-machine endpoint for AI detection events.
#
# Used by vizor-gpu inference workers (FRS, PPE, Vizor Query, People Mgmt,
# LPR, Anomaly, etc.) to post detection batches into the NVR events table.
#
# Auth: API key with `events:ingest` scope, sent in X-Vizor-API-Key header.
# Idempotency: each event MUST set `dedup_key`. Duplicates are silently
# ignored (returned as `skipped` in the response).
#
# Schema: batch of up to MAX_BATCH events. Designed for high throughput;
# workers buffer locally and POST every 1–2 seconds.
# =============================================================================

import logging
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_keys import APIKey, require_scope
from app.core.metrics import (
    EVENTS_FAILED,
    EVENTS_INGESTED,
    EVENTS_SKIPPED,
    INGEST_BATCH_SIZE,
)
from app.database import get_db
from app.events.models import Event


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/events", tags=["events-ingest"])


MAX_BATCH = 500


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class IngestEvent(BaseModel):
    """A single AI detection event to ingest."""

    # Required for dedup. Workers compose this as:
    #   sha1(f"{camera_id}:{detection_type}:{track_id or hash(bbox)}:{time_bucket}")
    dedup_key: str = Field(..., max_length=128)

    camera_id: Optional[str] = None
    event_type: str = Field(..., max_length=50)
    severity: str = Field("info", max_length=20)
    title: str = Field(..., max_length=200)
    description: Optional[str] = None

    # AI-specific
    source_service: str = Field(..., max_length=50)        # "vizor-gpu-frs", etc.
    detection_type: Optional[str] = Field(None, max_length=50)
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    bbox: Optional[List[float]] = None                       # [x, y, w, h] normalized
    track_id: Optional[str] = Field(None, max_length=64)
    person_id: Optional[str] = None                          # FRS match → frs_persons.id
    attributes: Optional[Dict[str, Any]] = None

    # Optional links to NVR-native data
    snapshot_path: Optional[str] = None
    recording_id: Optional[str] = None

    # Wall-clock when the detection occurred on the worker side.
    triggered_at: Optional[datetime] = None


class IngestBatch(BaseModel):
    events: List[IngestEvent] = Field(..., min_length=1)


class IngestResult(BaseModel):
    inserted: int
    skipped: int           # duplicates ignored via dedup_key
    failed: int            # validation or DB errors per row
    ids: List[str]


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.post(
    "/ingest",
    response_model=IngestResult,
    status_code=status.HTTP_200_OK,
    summary="Batch ingest of AI detection events from inference workers",
)
async def ingest_events(
    payload: IngestBatch,
    key: APIKey = Depends(require_scope("events:ingest")),
    db: AsyncSession = Depends(get_db),
) -> IngestResult:
    if len(payload.events) > MAX_BATCH:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Batch size exceeds maximum of {MAX_BATCH}",
        )

    INGEST_BATCH_SIZE.observe(len(payload.events))

    inserted_ids: List[str] = []
    skipped = 0
    failed = 0

    for ev in payload.events:
        try:
            new_id = str(uuid.uuid4())
            stmt = (
                pg_insert(Event)
                .values(
                    id=new_id,
                    camera_id=ev.camera_id,
                    event_type=ev.event_type,
                    severity=ev.severity,
                    title=ev.title,
                    description=ev.description,
                    event_metadata=None,
                    snapshot_path=ev.snapshot_path,
                    recording_id=ev.recording_id,
                    acknowledged=False,
                    is_false_alarm=False,
                    triggered_at=ev.triggered_at or datetime.utcnow(),
                    source_service=ev.source_service,
                    detection_type=ev.detection_type,
                    confidence=ev.confidence,
                    bbox=ev.bbox,
                    track_id=ev.track_id,
                    person_id=ev.person_id,
                    attributes=ev.attributes,
                    dedup_key=ev.dedup_key,
                )
                .on_conflict_do_nothing(index_elements=["dedup_key"])
                .returning(Event.id)
            )
            result = await db.execute(stmt)
            row = result.fetchone()
            if row is None:
                skipped += 1
                EVENTS_SKIPPED.labels(source_service=ev.source_service).inc()
            else:
                inserted_ids.append(row[0])
                EVENTS_INGESTED.labels(
                    source_service=ev.source_service,
                    detection_type=ev.detection_type or "unknown",
                ).inc()
        except Exception:  # noqa: BLE001 — log per-row failure, continue batch
            logger.exception("Failed to ingest event with dedup_key=%s", ev.dedup_key)
            failed += 1
            EVENTS_FAILED.labels(source_service=ev.source_service).inc()

    await db.commit()

    if inserted_ids:
        logger.info(
            "Ingested %d events from key=%s (source=%s, skipped=%d, failed=%d)",
            len(inserted_ids),
            key.key_prefix,
            payload.events[0].source_service if payload.events else "?",
            skipped,
            failed,
        )

    return IngestResult(
        inserted=len(inserted_ids),
        skipped=skipped,
        failed=failed,
        ids=inserted_ids,
    )
