"""add per-camera storage cap (max_storage_gb) to cameras

Revision ID: 20260620_010000
Revises: 20260620_000000
Create Date: 2026-06-20

Adds a nullable integer column holding a hard per-camera footage cap in GB.
When set and exceeded, retention deletes that camera's OLDEST segments until
under the cap, so a single high-bitrate camera cannot evict other cameras'
footage. NULL / 0 = no per-camera cap (global + pool limits still apply).
"""
from alembic import op
import sqlalchemy as sa

revision = "20260620_010000"
down_revision = "20260620_000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column("max_storage_gb", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cameras", "max_storage_gb")
