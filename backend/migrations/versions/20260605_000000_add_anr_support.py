"""add ANR (Automatic Network Replenishment) support

Revision ID: 20260605_000000
Revises: 20260529_000000
Create Date: 2026-06-05

Adds ANR configuration to cameras and a jobs table to track backfill
operations when cameras recover from network outages.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260605_000000"
down_revision = "20260528_090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ANR config on cameras
    op.add_column(
        "cameras",
        sa.Column(
            "anr_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "cameras",
        sa.Column(
            "anr_max_gap_hours",
            sa.Integer(),
            nullable=False,
            server_default="24",
        ),
    )
    op.add_column(
        "cameras",
        sa.Column(
            "anr_status",
            sa.String(20),
            nullable=True,
        ),
    )
    op.add_column(
        "cameras",
        sa.Column(
            "anr_last_run_at",
            sa.DateTime(),
            nullable=True,
        ),
    )

    # ANR jobs table
    op.create_table(
        "anr_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("camera_id", sa.String(), sa.ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("gap_start", sa.DateTime(), nullable=False),
        sa.Column("gap_end", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),  # pending/searching/downloading/completed/failed/cancelled
        sa.Column("segments_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("segments_downloaded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("segments_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_anr_jobs_status", "anr_jobs", ["status"])


def downgrade() -> None:
    op.drop_table("anr_jobs")
    op.drop_column("cameras", "anr_enabled")
    op.drop_column("cameras", "anr_max_gap_hours")
    op.drop_column("cameras", "anr_status")
    op.drop_column("cameras", "anr_last_run_at")
