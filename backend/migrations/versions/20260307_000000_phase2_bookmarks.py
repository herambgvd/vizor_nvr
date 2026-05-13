"""Phase 2 — bookmarks table and trigger_type on recordings

Revision ID: 006_phase2_bookmarks
Revises: 005_fix_recordings_schema
Create Date: 2026-03-07 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "006_phase2_bookmarks"
down_revision = "005_fix_recordings_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Bookmarks table ─────────────────────────────────────────────────
    op.create_table(
        "bookmarks",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("camera_id", sa.String(), nullable=False),
        sa.Column("recording_id", sa.String(), nullable=True),
        sa.Column("timestamp", sa.Float(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["camera_id"], ["cameras.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["recording_id"], ["recordings.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bookmarks_camera_id", "bookmarks", ["camera_id"])
    op.create_index("ix_bookmarks_recording_id", "bookmarks", ["recording_id"])
    op.create_index("ix_bookmarks_user_id", "bookmarks", ["user_id"])

    # ── Add trigger_type to recordings ──────────────────────────────────
    op.add_column(
        "recordings",
        sa.Column(
            "trigger_type",
            sa.String(length=30),
            nullable=True,
            server_default="continuous",
        ),
    )


def downgrade() -> None:
    op.drop_column("recordings", "trigger_type")
    op.drop_index("ix_bookmarks_user_id", table_name="bookmarks")
    op.drop_index("ix_bookmarks_recording_id", table_name="bookmarks")
    op.drop_index("ix_bookmarks_camera_id", table_name="bookmarks")
    op.drop_table("bookmarks")
