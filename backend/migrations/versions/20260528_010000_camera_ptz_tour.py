"""add ptz_tour_config and ptz_tour_enabled to cameras

Revision ID: 20260528_010000
Revises: 20260527_010000
Create Date: 2026-05-28

Adds two nullable columns on the cameras table:
  - ptz_tour_config  JSON   — { presets:[{token, dwell_seconds}], loop:true }
  - ptz_tour_enabled BOOLEAN DEFAULT false
Both columns are added idempotently.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260528_010000"
down_revision = "20260527_010000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("cameras")}
    with op.batch_alter_table("cameras") as batch:
        if "ptz_tour_config" not in existing_cols:
            batch.add_column(
                sa.Column("ptz_tour_config", sa.JSON, nullable=True)
            )
        if "ptz_tour_enabled" not in existing_cols:
            batch.add_column(
                sa.Column(
                    "ptz_tour_enabled",
                    sa.Boolean,
                    nullable=False,
                    server_default="0",
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("cameras")}
    with op.batch_alter_table("cameras") as batch:
        if "ptz_tour_enabled" in existing_cols:
            batch.drop_column("ptz_tour_enabled")
        if "ptz_tour_config" in existing_cols:
            batch.drop_column("ptz_tour_config")
