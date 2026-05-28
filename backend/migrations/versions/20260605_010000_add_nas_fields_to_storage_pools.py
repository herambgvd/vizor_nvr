"""add NAS fields to storage_pools

Revision ID: 20260605_010000
Revises: 20260605_000000
Create Date: 2026-06-05

Adds NAS connection and mount-state columns to storage_pools.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260605_010000"
down_revision = "20260605_000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("storage_pools", sa.Column("nas_server", sa.String(200), nullable=True))
    op.add_column("storage_pools", sa.Column("nas_share", sa.String(200), nullable=True))
    op.add_column("storage_pools", sa.Column("nas_protocol", sa.String(10), nullable=True))
    op.add_column("storage_pools", sa.Column("nas_username", sa.String(200), nullable=True))
    op.add_column("storage_pools", sa.Column("nas_password", sa.String(500), nullable=True))
    op.add_column("storage_pools", sa.Column("nas_domain", sa.String(100), nullable=True))
    op.add_column(
        "storage_pools",
        sa.Column("nas_auto_mount", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("storage_pools", sa.Column("nas_mount_state", sa.String(20), nullable=True))
    op.add_column("storage_pools", sa.Column("nas_last_mount_error", sa.Text(), nullable=True))
    op.add_column("storage_pools", sa.Column("nas_last_mount_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("storage_pools", "nas_server")
    op.drop_column("storage_pools", "nas_share")
    op.drop_column("storage_pools", "nas_protocol")
    op.drop_column("storage_pools", "nas_username")
    op.drop_column("storage_pools", "nas_password")
    op.drop_column("storage_pools", "nas_domain")
    op.drop_column("storage_pools", "nas_auto_mount")
    op.drop_column("storage_pools", "nas_mount_state")
    op.drop_column("storage_pools", "nas_last_mount_error")
    op.drop_column("storage_pools", "nas_last_mount_at")
