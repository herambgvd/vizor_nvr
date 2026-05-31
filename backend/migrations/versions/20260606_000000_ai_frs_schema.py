"""AI scenario + FRS schema, and AI columns on events

Adds:
  * ai_scenarios          — scenario catalog (FRS, PPE, …)
  * camera_ai_configs     — per-(camera,scenario) enablement + bridge state
  * frs_groups            — person groups
  * frs_persons           — enrolled person metadata (embeddings live in scenario)
  * frs_photos            — enrollment photos + scenario embedding refs
  * frs_attendance        — sighting/attendance log
  * events.<ai columns>   — detection_type, confidence, bbox, person_id,
                            track_id, attributes (for recognition events)

Revision ID: 20260606_000000
Revises: 20260605_050000
Create Date: 2026-06-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260606_000000"
down_revision: Union[str, None] = "20260605_050000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── ai_scenarios ────────────────────────────────────────────────────
    op.create_table(
        "ai_scenarios",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("slug", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(50), nullable=True),
        sa.Column("icon", sa.String(50), nullable=True),
        sa.Column("grpc_endpoint", sa.String(200), nullable=True),
        sa.Column("licensed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("camera_limit", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("module_tabs", sa.JSON(), nullable=True),
        sa.Column("camera_config_schema", sa.JSON(), nullable=True),
        sa.Column("event_types", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_ai_scenarios_slug", "ai_scenarios", ["slug"])

    # ── camera_ai_configs ───────────────────────────────────────────────
    op.create_table(
        "camera_ai_configs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("camera_id", sa.String(), nullable=False),
        sa.Column("scenario_id", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("stream_state", sa.String(20), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scenario_id"], ["ai_scenarios.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("camera_id", "scenario_id", name="uq_camera_scenario"),
    )
    op.create_index("ix_camera_ai_scenario", "camera_ai_configs", ["scenario_id", "enabled"])

    # ── frs_groups ──────────────────────────────────────────────────────
    op.create_table(
        "frs_groups",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("group_type", sa.String(50), nullable=True),
        sa.Column("color_code", sa.String(20), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("alert_sound", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # ── frs_persons ─────────────────────────────────────────────────────
    op.create_table(
        "frs_persons",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=True),
        sa.Column("group_id", sa.String(), nullable=True),
        sa.Column("category", sa.String(20), nullable=False, server_default="standard"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enrollment_status", sa.String(20), nullable=False, server_default="unenrolled"),
        sa.Column("photo_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enrolled_photo_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("thumbnail_key", sa.String(500), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["group_id"], ["frs_groups.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id"),
    )
    op.create_index("ix_frs_persons_group", "frs_persons", ["group_id"])
    op.create_index("ix_frs_persons_category", "frs_persons", ["category"])

    # ── frs_photos ──────────────────────────────────────────────────────
    op.create_table(
        "frs_photos",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("person_id", sa.String(), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=True),
        sa.Column("thumbnail_key", sa.String(500), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("embedding_id", sa.String(100), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("liveness_score", sa.Float(), nullable=True),
        sa.Column("sharpness_score", sa.Float(), nullable=True),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["person_id"], ["frs_persons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_frs_photos_person", "frs_photos", ["person_id"])

    # ── frs_attendance ──────────────────────────────────────────────────
    op.create_table(
        "frs_attendance",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("person_id", sa.String(), nullable=False),
        sa.Column("camera_id", sa.String(), nullable=True),
        sa.Column("day_key", sa.String(10), nullable=False),
        sa.Column("check_in_at", sa.DateTime(), nullable=True),
        sa.Column("check_out_at", sa.DateTime(), nullable=True),
        sa.Column("sighting_type", sa.String(20), nullable=True),
        # events is a TimescaleDB hypertable (no usable unique PK for an FK),
        # so event_id is a soft reference (plain column, no FK constraint).
        sa.Column("event_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["person_id"], ["frs_persons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("person_id", "day_key", name="uq_person_day"),
    )
    op.create_index("ix_frs_attendance_day", "frs_attendance", ["day_key"])

    # ── AI columns on events ────────────────────────────────────────────
    op.add_column("events", sa.Column("detection_type", sa.String(50), nullable=True))
    op.add_column("events", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column("events", sa.Column("bbox", sa.JSON(), nullable=True))
    op.add_column("events", sa.Column("person_id", sa.String(), nullable=True))
    op.add_column("events", sa.Column("track_id", sa.String(50), nullable=True))
    op.add_column("events", sa.Column("attributes", sa.JSON(), nullable=True))
    op.create_index("ix_events_person", "events", ["person_id"])
    op.create_index("ix_events_detection_type", "events", ["detection_type"])


def downgrade() -> None:
    op.drop_index("ix_events_detection_type", "events")
    op.drop_index("ix_events_person", "events")
    for col in ("attributes", "track_id", "person_id", "bbox", "confidence", "detection_type"):
        op.drop_column("events", col)
    op.drop_table("frs_attendance")
    op.drop_table("frs_photos")
    op.drop_table("frs_persons")
    op.drop_table("frs_groups")
    op.drop_table("camera_ai_configs")
    op.drop_table("ai_scenarios")
