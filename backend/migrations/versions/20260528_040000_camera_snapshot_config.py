"""add snapshot_config JSON column to cameras

Revision ID: 20260528_040000
Revises: 20260527_010000
Create Date: 2026-05-28

Adds a nullable JSON column `snapshot_config` to cameras for per-camera
scheduled snapshot configuration:
  { "enabled": true, "interval_seconds": 60, "retention_days": 7 }
"""
from alembic import op
import sqlalchemy as sa

revision = "20260528_040000"
down_revision = "20260527_010000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("cameras")}
    if "snapshot_config" not in existing_cols:
        with op.batch_alter_table("cameras") as batch:
            batch.add_column(
                sa.Column("snapshot_config", sa.JSON(), nullable=True)
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("cameras")}
    if "snapshot_config" in existing_cols:
        with op.batch_alter_table("cameras") as batch:
            batch.drop_column("snapshot_config")
