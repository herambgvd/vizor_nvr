"""Phase 4 — ONVIF compliance, JWT revocation, camera snapshots, recording mode

Revision ID: 008_phase4_onvif_complete
Revises: 007_phase3_events
Create Date: 2026-03-09 00:00:00

Changes:
  - cameras: recording_mode, onvif_events_enabled, onvif_event_topics,
             relay_outputs, digital_inputs
  - refresh_tokens: new table for JWT revocation
  - camera_snapshots: new table for periodic + event snapshots
"""
from alembic import op
import sqlalchemy as sa

revision = "008_phase4_onvif_complete"
down_revision = "007_phase3_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cameras: new ONVIF + recording fields ──────────────────────────
    op.add_column(
        "cameras",
        sa.Column("recording_mode", sa.String(20), nullable=False, server_default="continuous"),
    )
    op.add_column(
        "cameras",
        sa.Column("onvif_events_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "cameras",
        sa.Column("onvif_event_topics", sa.JSON(), nullable=True),
    )
    op.add_column(
        "cameras",
        sa.Column("relay_outputs", sa.JSON(), nullable=True),
    )
    op.add_column(
        "cameras",
        sa.Column("digital_inputs", sa.JSON(), nullable=True),
    )

    # ── refresh_tokens ──────────────────────────────────────────────────
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column(
            "issued_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"])
    op.create_index("ix_refresh_tokens_revoked", "refresh_tokens", ["revoked"])

    # ── camera_snapshots ────────────────────────────────────────────────
    op.create_table(
        "camera_snapshots",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("camera_id", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("trigger", sa.String(20), nullable=False, server_default="periodic"),
        sa.Column("event_id", sa.String(), nullable=True),
        sa.Column(
            "captured_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_camera_snapshots_camera_id", "camera_snapshots", ["camera_id"])
    op.create_index("ix_camera_snapshots_captured_at", "camera_snapshots", ["captured_at"])
    op.create_index("ix_camera_snapshots_trigger", "camera_snapshots", ["trigger"])


def downgrade() -> None:
    op.drop_index("ix_camera_snapshots_trigger", table_name="camera_snapshots")
    op.drop_index("ix_camera_snapshots_captured_at", table_name="camera_snapshots")
    op.drop_index("ix_camera_snapshots_camera_id", table_name="camera_snapshots")
    op.drop_table("camera_snapshots")

    op.drop_index("ix_refresh_tokens_revoked", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_token_hash", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

    op.drop_column("cameras", "digital_inputs")
    op.drop_column("cameras", "relay_outputs")
    op.drop_column("cameras", "onvif_event_topics")
    op.drop_column("cameras", "onvif_events_enabled")
    op.drop_column("cameras", "recording_mode")
