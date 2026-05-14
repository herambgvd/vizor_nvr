# =============================================================================
# AI Domain Models — SQLAlchemy ORM
#
# Tables introduced by the phase10_ai_schema migration. Covers:
#   - ai_scenarios          — catalog of available AI capabilities
#   - camera_ai_configs     — per-camera scenario enablement + config
#   - frs_persons, frs_groups, frs_photos, frs_investigations, frs_attendance
#   - vq_captions, vq_attributes
#   - models, model_deployments
#   - inference_jobs
#   - webhook_subscriptions, webhook_deliveries
#   - metropolis_services   — registry of running Metropolis Microservice
#                             instances (health, version, capabilities)
# =============================================================================

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, JSON,
    String, Text,
)
from sqlalchemy.sql import func

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

class AIScenario(Base):
    """Catalog of AI capabilities the platform can run (FRS, PPE, LPR, etc.).

    Seeded at startup. Cameras opt-in to scenarios via camera_ai_configs.
    `default_config` provides safe baseline knobs (thresholds, ROI, etc.).

    Marketing/SKU metadata:
      - `category` groups for UI tabs (person/vehicle/behavior/safety/security/search)
      - `tier` gates by license (free/pro/business/enterprise)
      - `status` ga/beta/planned — drives "Coming Soon" UI badges
      - `metropolis_service` which Metropolis Microservice runs this
      - `use_cases` JSON array of strings for marketing pages + vertical packs
    """
    __tablename__ = "ai_scenarios"

    id = Column(String, primary_key=True, default=_uuid)
    slug = Column(String(50), nullable=False, unique=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    schema_version = Column(Integer, nullable=False, default=1)
    default_config = Column(JSON, nullable=False, default=dict)
    requires_models = Column(JSON, nullable=False, default=list)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())

    # SKU + marketing metadata
    category = Column(String(50), nullable=True)            # person, vehicle, behavior, safety, security, search
    tier = Column(String(20), nullable=False, default="pro")  # free | pro | business | enterprise
    status = Column(String(20), nullable=False, default="ga")  # ga | beta | planned
    metropolis_service = Column(String(50), nullable=True)   # perception, behavior_analytics, mtmc, visual_search, etc.
    use_cases = Column(JSON, nullable=True)                  # list of vertical-tagged use case strings


class CameraAIConfig(Base):
    """Per-camera scenario enablement + override config.

    Composite unique on (camera_id, scenario_id) ensures one row per pair.
    `config` JSONB merges over scenario.default_config at runtime.
    """
    __tablename__ = "camera_ai_configs"

    id = Column(String, primary_key=True, default=_uuid)
    camera_id = Column(String, ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False)
    scenario_id = Column(String, ForeignKey("ai_scenarios.id", ondelete="CASCADE"), nullable=False)
    config = Column(JSON, nullable=False, default=dict)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("uq_camera_scenario", "camera_id", "scenario_id", unique=True),
    )


# ---------------------------------------------------------------------------
# FRS
# ---------------------------------------------------------------------------

class FRSGroup(Base):
    __tablename__ = "frs_groups"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    color = Column(String(20), nullable=True)            # UI swatch
    created_at = Column(DateTime, server_default=func.now())


class FRSPerson(Base):
    __tablename__ = "frs_persons"

    id = Column(String, primary_key=True, default=_uuid)
    external_id = Column(String(100), nullable=True, index=True)  # customer's HR id, etc.
    name = Column(String(200), nullable=False)
    group_id = Column(String, ForeignKey("frs_groups.id", ondelete="SET NULL"), nullable=True, index=True)
    attributes = Column(JSON, nullable=True)              # department, role, badge_id, etc.
    enrolled_at = Column(DateTime, server_default=func.now())
    last_seen_at = Column(DateTime, nullable=True)


class FRSPhoto(Base):
    """A reference photo enrolling a face into Qdrant.

    `qdrant_point_id` is the UUID used as the vector id in Qdrant. We keep
    this row alive even after the photo is deleted from object storage so
    audits can prove the embedding was created from a real upload.
    """
    __tablename__ = "frs_photos"

    id = Column(String, primary_key=True, default=_uuid)
    person_id = Column(String, ForeignKey("frs_persons.id", ondelete="CASCADE"), nullable=False, index=True)
    storage_key = Column(String(500), nullable=False)
    qdrant_point_id = Column(String, nullable=False, unique=True, index=True)
    quality_score = Column(Float, nullable=True)
    uploaded_at = Column(DateTime, server_default=func.now())


class FRSInvestigation(Base):
    """Person-of-interest investigation across cameras + time.

    `person_id` is nullable: legacy investigations may be query-by-image
    (upload a face crop, search the archive) without an enrolled person.
    """
    __tablename__ = "frs_investigations"

    id = Column(String, primary_key=True, default=_uuid)
    person_id = Column(String, ForeignKey("frs_persons.id", ondelete="CASCADE"), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="pending")  # pending|running|complete|failed
    params = Column(JSON, nullable=False)                # camera_ids, time_range, threshold
    result = Column(JSON, nullable=True)                 # matched event ids + scores
    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime, nullable=True)


class FRSAttendance(Base):
    """Time-series log of person sightings — hypertable on `ts`."""
    __tablename__ = "frs_attendance"

    id = Column(String, primary_key=True, default=_uuid)
    person_id = Column(String, ForeignKey("frs_persons.id", ondelete="CASCADE"), nullable=False, index=True)
    camera_id = Column(String, ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True, index=True)
    ts = Column(DateTime, nullable=False, server_default=func.now())
    sighting_type = Column(String(20), nullable=False, default="seen")  # seen|entry|exit|absent
    confidence = Column(Float, nullable=True)
    event_id = Column(String, nullable=True)            # back-pointer to events.id

    __table_args__ = (
        Index("ix_frs_attendance_person_ts", "person_id", "ts"),
        Index("ix_frs_attendance_camera_ts", "camera_id", "ts"),
    )


# ---------------------------------------------------------------------------
# Vizor Query (semantic search by text / image)
# ---------------------------------------------------------------------------

class VQCaption(Base):
    """Generated caption + embedding for a detection event.

    Stored separately from `events` because not every event gets a caption
    (only those passed through the caption pipeline). Hypertable on
    `created_at` — caption row volume tracks event volume.
    """
    __tablename__ = "vq_captions"

    id = Column(String, primary_key=True, default=_uuid)
    event_id = Column(String, nullable=False, index=True)  # FK target events.id (cross-hypertable)
    caption = Column(Text, nullable=False)
    qdrant_point_id = Column(String, nullable=False, unique=True, index=True)
    embedding_model = Column(String(100), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class VQAttribute(Base):
    """Discrete attribute extracted from a detection (color, type, age band, etc.)."""
    __tablename__ = "vq_attributes"

    id = Column(String, primary_key=True, default=_uuid)
    event_id = Column(String, nullable=False, index=True)  # back-pointer to events.id
    kind = Column(String(50), nullable=False, index=True)  # vehicle_color, age_band, gender, etc.
    value = Column(String(100), nullable=False)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

class AIModel(Base):
    """Versioned record of an AI model deployment artifact.

    Includes signed manifest for integrity verification; workers refuse to
    boot if the signature doesn't match. `ngc_resource_id` lets us recover
    a model by pulling it again from NGC if local copies are lost.
    """
    __tablename__ = "models"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String(100), nullable=False, index=True)
    version = Column(String(50), nullable=False)
    manifest_json = Column(JSON, nullable=False)         # {files: [...], sha256s, runtime, batch_size}
    signature = Column(String(512), nullable=True)        # detached signature of manifest
    status = Column(String(20), nullable=False, default="staged")  # staged|active|retired
    ngc_resource_id = Column(String(200), nullable=True)
    storage_key = Column(String(500), nullable=True)      # RustFS/S3 key for the artifact bundle
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("uq_model_name_version", "name", "version", unique=True),
    )


class ModelDeployment(Base):
    """Which model version backs a scenario right now.

    Exactly one row per scenario should be active at a time.
    """
    __tablename__ = "model_deployments"

    id = Column(String, primary_key=True, default=_uuid)
    model_id = Column(String, ForeignKey("models.id", ondelete="CASCADE"), nullable=False, index=True)
    scenario_id = Column(String, ForeignKey("ai_scenarios.id", ondelete="CASCADE"), nullable=False, index=True)
    active = Column(Boolean, nullable=False, default=False)
    deployed_at = Column(DateTime, server_default=func.now())
    deployed_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


# ---------------------------------------------------------------------------
# Inference jobs (re-analyze historical footage, batch runs)
# ---------------------------------------------------------------------------

class InferenceJob(Base):
    __tablename__ = "inference_jobs"

    id = Column(String, primary_key=True, default=_uuid)
    camera_id = Column(String, ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True, index=True)
    start_ts = Column(DateTime, nullable=False)
    end_ts = Column(DateTime, nullable=False)
    model_id = Column(String, ForeignKey("models.id", ondelete="SET NULL"), nullable=True)
    scenario_slug = Column(String(50), nullable=True)
    status = Column(String(20), nullable=False, default="queued")  # queued|running|complete|failed|cancelled
    progress_pct = Column(Float, nullable=False, default=0.0)
    result = Column(JSON, nullable=True)                   # {events_created, errors, summary}
    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ---------------------------------------------------------------------------
# Webhook subscriptions + deliveries
# ---------------------------------------------------------------------------

class WebhookSubscription(Base):
    __tablename__ = "webhook_subscriptions"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String(100), nullable=False)
    url = Column(String(500), nullable=False)
    events = Column(JSON, nullable=False, default=list)    # list of event_type filters
    secret = Column(String(128), nullable=True)            # HMAC signing key
    headers = Column(JSON, nullable=True)                  # extra headers to include
    enabled = Column(Boolean, nullable=False, default=True)
    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class WebhookDelivery(Base):
    """Hypertable on `created_at` — tracks every delivery attempt."""
    __tablename__ = "webhook_deliveries"

    id = Column(String, primary_key=True, default=_uuid)
    subscription_id = Column(String, ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"), nullable=False, index=True)
    event_id = Column(String, nullable=True, index=True)
    payload = Column(JSON, nullable=False)
    status = Column(String(20), nullable=False, default="pending")  # pending|success|failed|abandoned
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    response_status = Column(Integer, nullable=True)
    next_retry_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_webhook_deliveries_status", "status", "next_retry_at"),
    )


# ---------------------------------------------------------------------------
# Metropolis service registry
# ---------------------------------------------------------------------------

class MetropolisService(Base):
    """Health + version registry for Metropolis Microservice instances.

    Allows the NVR backend to know which services are reachable and route
    requests accordingly. Updated by a background poller that hits each
    service's /health endpoint.
    """
    __tablename__ = "metropolis_services"

    id = Column(String, primary_key=True, default=_uuid)
    service_type = Column(String(50), nullable=False, index=True)
    # Examples: "vst" "perception" "mtmc" "behavior_analytics" "event"
    #           "visual_search" "spatial_intelligence" "mmj"
    instance_url = Column(String(500), nullable=False)
    version = Column(String(50), nullable=True)
    health_status = Column(String(20), nullable=False, default="unknown")  # ok|degraded|down|unknown
    last_check_at = Column(DateTime, nullable=True)
    capabilities = Column(JSON, nullable=True)            # service-reported features
    config = Column(JSON, nullable=True)                  # connection params we pass to the service
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())
