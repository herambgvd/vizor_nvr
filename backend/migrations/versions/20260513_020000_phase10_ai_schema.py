"""
Phase 10 — AI Schema

Creates the AI domain tables consumed by absorbed vizor-app functionality:
  - ai_scenarios + camera_ai_configs (per-camera scenario enablement)
  - frs_groups, frs_persons, frs_photos, frs_investigations, frs_attendance
  - vq_captions, vq_attributes (Vizor Query semantic search domain)
  - models, model_deployments (model registry)
  - inference_jobs (re-analyze historical batch runs)
  - webhook_subscriptions, webhook_deliveries
  - metropolis_services (Metropolis Microservice instance registry)

Hypertables (Postgres + TimescaleDB only):
  - frs_attendance on `ts`
  - vq_captions on `created_at`
  - webhook_deliveries on `created_at`

Revision ID: phase10_ai_schema
Revises: phase9_timescale
Create Date: 2026-05-13
"""

from alembic import op
import sqlalchemy as sa


revision = "phase10_ai_schema"
down_revision = "phase9_timescale"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    # ── ai_scenarios ────────────────────────────────────────────────────
    op.create_table(
        "ai_scenarios",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("slug", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("default_config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("requires_models", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        # SKU + marketing metadata
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.Column("tier", sa.String(length=20), nullable=False, server_default="pro"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ga"),
        sa.Column("metropolis_service", sa.String(length=50), nullable=True),
        sa.Column("use_cases", sa.JSON(), nullable=True),
    )
    op.create_index("ix_ai_scenarios_slug", "ai_scenarios", ["slug"], unique=True)
    op.create_index("ix_ai_scenarios_category", "ai_scenarios", ["category"])
    op.create_index("ix_ai_scenarios_tier", "ai_scenarios", ["tier"])
    op.create_index("ix_ai_scenarios_status", "ai_scenarios", ["status"])

    # ── camera_ai_configs ──────────────────────────────────────────────
    op.create_table(
        "camera_ai_configs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("camera_id", sa.String(), sa.ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scenario_id", sa.String(), sa.ForeignKey("ai_scenarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("uq_camera_scenario", "camera_ai_configs", ["camera_id", "scenario_id"], unique=True)

    # ── frs_groups ─────────────────────────────────────────────────────
    op.create_table(
        "frs_groups",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("color", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    # ── frs_persons ────────────────────────────────────────────────────
    op.create_table(
        "frs_persons",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("external_id", sa.String(length=100), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("group_id", sa.String(), sa.ForeignKey("frs_groups.id", ondelete="SET NULL"), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=True),
        sa.Column("enrolled_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_frs_persons_external_id", "frs_persons", ["external_id"])
    op.create_index("ix_frs_persons_group_id", "frs_persons", ["group_id"])

    # ── frs_photos ─────────────────────────────────────────────────────
    op.create_table(
        "frs_photos",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("person_id", sa.String(), sa.ForeignKey("frs_persons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("qdrant_point_id", sa.String(), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_frs_photos_person_id", "frs_photos", ["person_id"])
    op.create_index("ix_frs_photos_qdrant_point_id", "frs_photos", ["qdrant_point_id"], unique=True)

    # ── frs_investigations ─────────────────────────────────────────────
    op.create_table(
        "frs_investigations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("person_id", sa.String(), sa.ForeignKey("frs_persons.id", ondelete="CASCADE"), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_frs_investigations_person_id", "frs_investigations", ["person_id"])

    # ── frs_attendance (hypertable in Postgres) ────────────────────────
    op.create_table(
        "frs_attendance",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("person_id", sa.String(), sa.ForeignKey("frs_persons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("camera_id", sa.String(), sa.ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True),
        sa.Column("ts", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("sighting_type", sa.String(length=20), nullable=False, server_default="seen"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("event_id", sa.String(), nullable=True),
    )
    op.create_index("ix_frs_attendance_person_ts", "frs_attendance", ["person_id", "ts"])
    op.create_index("ix_frs_attendance_camera_ts", "frs_attendance", ["camera_id", "ts"])

    # ── vq_captions (hypertable in Postgres) ───────────────────────────
    op.create_table(
        "vq_captions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("qdrant_point_id", sa.String(), nullable=False),
        sa.Column("embedding_model", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_vq_captions_event_id", "vq_captions", ["event_id"])
    op.create_index("ix_vq_captions_qdrant_point_id", "vq_captions", ["qdrant_point_id"], unique=True)

    # ── vq_attributes ──────────────────────────────────────────────────
    op.create_table(
        "vq_attributes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("value", sa.String(length=100), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_vq_attributes_event_id", "vq_attributes", ["event_id"])
    op.create_index("ix_vq_attributes_kind", "vq_attributes", ["kind"])

    # ── models ─────────────────────────────────────────────────────────
    op.create_table(
        "models",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("signature", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="staged"),
        sa.Column("ngc_resource_id", sa.String(length=200), nullable=True),
        sa.Column("storage_key", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_models_name", "models", ["name"])
    op.create_index("uq_model_name_version", "models", ["name", "version"], unique=True)

    # ── model_deployments ──────────────────────────────────────────────
    op.create_table(
        "model_deployments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("model_id", sa.String(), sa.ForeignKey("models.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scenario_id", sa.String(), sa.ForeignKey("ai_scenarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("deployed_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("deployed_by", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_model_deployments_model_id", "model_deployments", ["model_id"])
    op.create_index("ix_model_deployments_scenario_id", "model_deployments", ["scenario_id"])

    # ── inference_jobs ─────────────────────────────────────────────────
    op.create_table(
        "inference_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("camera_id", sa.String(), sa.ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True),
        sa.Column("start_ts", sa.DateTime(), nullable=False),
        sa.Column("end_ts", sa.DateTime(), nullable=False),
        sa.Column("model_id", sa.String(), sa.ForeignKey("models.id", ondelete="SET NULL"), nullable=True),
        sa.Column("scenario_slug", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("progress_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_inference_jobs_camera_id", "inference_jobs", ["camera_id"])

    # ── webhook_subscriptions ──────────────────────────────────────────
    op.create_table(
        "webhook_subscriptions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("secret", sa.String(length=128), nullable=True),
        sa.Column("headers", sa.JSON(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    # ── webhook_deliveries (hypertable in Postgres) ───────────────────
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("subscription_id", sa.String(), sa.ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.String(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_webhook_deliveries_subscription_id", "webhook_deliveries", ["subscription_id"])
    op.create_index("ix_webhook_deliveries_event_id", "webhook_deliveries", ["event_id"])
    op.create_index("ix_webhook_deliveries_status", "webhook_deliveries", ["status", "next_retry_at"])

    # ── metropolis_services ────────────────────────────────────────────
    op.create_table(
        "metropolis_services",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("service_type", sa.String(length=50), nullable=False),
        sa.Column("instance_url", sa.String(length=500), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=True),
        sa.Column("health_status", sa.String(length=20), nullable=False, server_default="unknown"),
        sa.Column("last_check_at", sa.DateTime(), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=True),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_metropolis_services_service_type", "metropolis_services", ["service_type"])

    # ── Convert time-series tables to hypertables (Postgres only) ─────
    # TimescaleDB requires the partitioning column to be part of every
    # unique index, including the primary key. We widen each PK + unique
    # index before converting. Same pattern used for `events` in
    # phase9_timescale.
    if _is_postgres():
        bind = op.get_bind()

        # frs_attendance — only PK needs widening
        bind.execute(sa.text("ALTER TABLE frs_attendance DROP CONSTRAINT IF EXISTS frs_attendance_pkey CASCADE"))
        bind.execute(sa.text("ALTER TABLE frs_attendance ADD CONSTRAINT frs_attendance_pkey PRIMARY KEY (id, ts)"))
        bind.execute(sa.text(
            "SELECT create_hypertable('frs_attendance', 'ts', "
            "if_not_exists => TRUE, migrate_data => TRUE)"
        ))

        # vq_captions — PK + unique qdrant_point_id index need widening
        bind.execute(sa.text("ALTER TABLE vq_captions DROP CONSTRAINT IF EXISTS vq_captions_pkey CASCADE"))
        bind.execute(sa.text("ALTER TABLE vq_captions ADD CONSTRAINT vq_captions_pkey PRIMARY KEY (id, created_at)"))
        bind.execute(sa.text("DROP INDEX IF EXISTS ix_vq_captions_qdrant_point_id"))
        bind.execute(sa.text(
            "CREATE UNIQUE INDEX ix_vq_captions_qdrant_point_id "
            "ON vq_captions (qdrant_point_id, created_at)"
        ))
        bind.execute(sa.text(
            "SELECT create_hypertable('vq_captions', 'created_at', "
            "if_not_exists => TRUE, migrate_data => TRUE)"
        ))

        # webhook_deliveries — only PK needs widening (no other uniques)
        bind.execute(sa.text("ALTER TABLE webhook_deliveries DROP CONSTRAINT IF EXISTS webhook_deliveries_pkey CASCADE"))
        bind.execute(sa.text("ALTER TABLE webhook_deliveries ADD CONSTRAINT webhook_deliveries_pkey PRIMARY KEY (id, created_at)"))
        bind.execute(sa.text(
            "SELECT create_hypertable('webhook_deliveries', 'created_at', "
            "if_not_exists => TRUE, migrate_data => TRUE)"
        ))

        # Retention: webhook deliveries kept 30 days, attendance 1 year,
        # captions follow events at 90 days.
        bind.execute(sa.text(
            "SELECT add_retention_policy('webhook_deliveries', INTERVAL '30 days', "
            "if_not_exists => TRUE)"
        ))
        bind.execute(sa.text(
            "SELECT add_retention_policy('frs_attendance', INTERVAL '365 days', "
            "if_not_exists => TRUE)"
        ))
        bind.execute(sa.text(
            "SELECT add_retention_policy('vq_captions', INTERVAL '90 days', "
            "if_not_exists => TRUE)"
        ))


def downgrade() -> None:
    if _is_postgres():
        bind = op.get_bind()
        for tbl in ("webhook_deliveries", "frs_attendance", "vq_captions"):
            try:
                bind.execute(sa.text(f"SELECT remove_retention_policy('{tbl}', if_exists => TRUE)"))
            except Exception:
                pass

    op.drop_index("ix_metropolis_services_service_type", table_name="metropolis_services")
    op.drop_table("metropolis_services")

    op.drop_index("ix_webhook_deliveries_status", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_event_id", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_subscription_id", table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
    op.drop_table("webhook_subscriptions")

    op.drop_index("ix_inference_jobs_camera_id", table_name="inference_jobs")
    op.drop_table("inference_jobs")

    op.drop_index("ix_model_deployments_scenario_id", table_name="model_deployments")
    op.drop_index("ix_model_deployments_model_id", table_name="model_deployments")
    op.drop_table("model_deployments")

    op.drop_index("uq_model_name_version", table_name="models")
    op.drop_index("ix_models_name", table_name="models")
    op.drop_table("models")

    op.drop_index("ix_vq_attributes_kind", table_name="vq_attributes")
    op.drop_index("ix_vq_attributes_event_id", table_name="vq_attributes")
    op.drop_table("vq_attributes")

    op.drop_index("ix_vq_captions_qdrant_point_id", table_name="vq_captions")
    op.drop_index("ix_vq_captions_event_id", table_name="vq_captions")
    op.drop_table("vq_captions")

    op.drop_index("ix_frs_attendance_camera_ts", table_name="frs_attendance")
    op.drop_index("ix_frs_attendance_person_ts", table_name="frs_attendance")
    op.drop_table("frs_attendance")

    op.drop_index("ix_frs_investigations_person_id", table_name="frs_investigations")
    op.drop_table("frs_investigations")

    op.drop_index("ix_frs_photos_qdrant_point_id", table_name="frs_photos")
    op.drop_index("ix_frs_photos_person_id", table_name="frs_photos")
    op.drop_table("frs_photos")

    op.drop_index("ix_frs_persons_group_id", table_name="frs_persons")
    op.drop_index("ix_frs_persons_external_id", table_name="frs_persons")
    op.drop_table("frs_persons")

    op.drop_table("frs_groups")

    op.drop_index("uq_camera_scenario", table_name="camera_ai_configs")
    op.drop_table("camera_ai_configs")

    op.drop_index("ix_ai_scenarios_status", table_name="ai_scenarios")
    op.drop_index("ix_ai_scenarios_tier", table_name="ai_scenarios")
    op.drop_index("ix_ai_scenarios_category", table_name="ai_scenarios")
    op.drop_index("ix_ai_scenarios_slug", table_name="ai_scenarios")
    op.drop_table("ai_scenarios")
