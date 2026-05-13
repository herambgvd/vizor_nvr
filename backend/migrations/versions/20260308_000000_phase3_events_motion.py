"""Phase 3 — events, event linkage rules, privacy masks, motion config

Revision ID: 007_phase3_events
Revises: 006_phase2_bookmarks
Create Date: 2026-03-08 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "007_phase3_events"
down_revision = "006_phase2_bookmarks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Events table ────────────────────────────────────────────────────
    op.create_table(
        "events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("camera_id", sa.String(), nullable=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="info"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("snapshot_path", sa.String(500), nullable=True),
        sa.Column("recording_id", sa.String(), nullable=True),
        sa.Column("acknowledged", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("acknowledged_by", sa.String(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("is_false_alarm", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "triggered_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["recording_id"], ["recordings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["acknowledged_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_events_camera_id", "events", ["camera_id"])
    op.create_index("ix_events_event_type", "events", ["event_type"])
    op.create_index("ix_events_severity", "events", ["severity"])
    op.create_index("ix_events_triggered_at", "events", ["triggered_at"])
    op.create_index("ix_events_acknowledged", "events", ["acknowledged"])

    # ── Event linkage rules table ───────────────────────────────────────
    op.create_table(
        "event_linkage_rules",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("trigger_type", sa.String(50), nullable=False),
        sa.Column("trigger_config", sa.JSON(), nullable=True),
        sa.Column("actions", sa.JSON(), nullable=False),
        sa.Column("camera_ids", sa.JSON(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("schedule", sa.JSON(), nullable=True),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False, server_default=sa.text("30")),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_event_linkage_rules_trigger_type", "event_linkage_rules", ["trigger_type"])

    # ── Add privacy_masks and motion_config columns to cameras ──────────
    op.add_column("cameras", sa.Column("privacy_masks", sa.JSON(), nullable=True))
    op.add_column("cameras", sa.Column("motion_config", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("cameras", "motion_config")
    op.drop_column("cameras", "privacy_masks")
    op.drop_index("ix_event_linkage_rules_trigger_type", table_name="event_linkage_rules")
    op.drop_table("event_linkage_rules")
    op.drop_index("ix_events_acknowledged", table_name="events")
    op.drop_index("ix_events_triggered_at", table_name="events")
    op.drop_index("ix_events_severity", table_name="events")
    op.drop_index("ix_events_event_type", table_name="events")
    op.drop_index("ix_events_camera_id", table_name="events")
    op.drop_table("events")
