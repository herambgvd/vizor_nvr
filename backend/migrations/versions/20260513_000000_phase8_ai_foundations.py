"""
Phase 8 — AI Foundations

Adds the machine-to-machine API key auth surface and extends the events
table with AI-detection metadata. This is the first migration in the
absorption track that pulls vizor-app functionality into vizor_nvr.

Revision ID: phase8_ai_foundations
Revises: phase7_nvr_completion
Create Date: 2026-05-13

Adds:
  - api_keys table (m2m auth for vizor-gpu workers and integrations)
  - events.source_service, detection_type, confidence, bbox,
    track_id, person_id, attributes, dedup_key columns
  - Composite indexes for AI event query patterns
"""

from alembic import op
import sqlalchemy as sa


revision = "phase8_ai_foundations"
down_revision = "phase7_nvr_completion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── api_keys ─────────────────────────────────────────────────────────
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("key_prefix", sa.String(length=12), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_ip", sa.String(length=45), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_api_keys_name", "api_keys", ["name"])
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)
    op.create_index("ix_api_keys_enabled", "api_keys", ["enabled"])

    # ── events: AI detection columns ─────────────────────────────────────
    op.add_column("events", sa.Column("source_service", sa.String(length=50), nullable=True))
    op.add_column("events", sa.Column("detection_type", sa.String(length=50), nullable=True))
    op.add_column("events", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column("events", sa.Column("bbox", sa.JSON(), nullable=True))
    op.add_column("events", sa.Column("track_id", sa.String(length=64), nullable=True))
    op.add_column("events", sa.Column("person_id", sa.String(), nullable=True))
    op.add_column("events", sa.Column("attributes", sa.JSON(), nullable=True))
    op.add_column("events", sa.Column("dedup_key", sa.String(length=128), nullable=True))

    op.create_index("ix_events_source_service", "events", ["source_service"])
    op.create_index("ix_events_detection_type", "events", ["detection_type"])
    op.create_index("ix_events_track_id", "events", ["track_id"])
    op.create_index("ix_events_person_id", "events", ["person_id"])
    op.create_index("ix_events_dedup_key", "events", ["dedup_key"], unique=True)
    op.create_index("ix_events_camera_triggered", "events", ["camera_id", "triggered_at"])
    op.create_index("ix_events_source_triggered", "events", ["source_service", "triggered_at"])


def downgrade() -> None:
    op.drop_index("ix_events_source_triggered", table_name="events")
    op.drop_index("ix_events_camera_triggered", table_name="events")
    op.drop_index("ix_events_dedup_key", table_name="events")
    op.drop_index("ix_events_person_id", table_name="events")
    op.drop_index("ix_events_track_id", table_name="events")
    op.drop_index("ix_events_detection_type", table_name="events")
    op.drop_index("ix_events_source_service", table_name="events")

    op.drop_column("events", "dedup_key")
    op.drop_column("events", "attributes")
    op.drop_column("events", "person_id")
    op.drop_column("events", "track_id")
    op.drop_column("events", "bbox")
    op.drop_column("events", "confidence")
    op.drop_column("events", "detection_type")
    op.drop_column("events", "source_service")

    op.drop_index("ix_api_keys_enabled", table_name="api_keys")
    op.drop_index("ix_api_keys_key_hash", table_name="api_keys")
    op.drop_index("ix_api_keys_name", table_name="api_keys")
    op.drop_table("api_keys")
