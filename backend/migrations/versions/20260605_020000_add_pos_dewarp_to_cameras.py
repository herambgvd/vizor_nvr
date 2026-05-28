"""add POS overlay and fisheye dewarp to cameras

Revision ID: 20260605_020000
Revises: 20260605_010000
Create Date: 2026-06-05
"""
from alembic import op
import sqlalchemy as sa

revision = "20260605_020000"
down_revision = "20260605_010000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cameras", sa.Column("pos_overlay_config", sa.JSON(), nullable=True))
    op.add_column("cameras", sa.Column("dewarp_config", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("cameras", "pos_overlay_config")
    op.drop_column("cameras", "dewarp_config")
